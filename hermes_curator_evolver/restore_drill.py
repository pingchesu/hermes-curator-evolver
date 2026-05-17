"""Non-destructive restore drill for guarded-apply rollback manifests.

A rollback manifest proves the plugin *could* rewrite a skill back to its
prior state. The restore drill is the trust line: it actually performs that
restore into a clean temp directory (or an explicit drill target) and
emits a machine-readable pass/fail report.

The drill is non-destructive — it never touches the live Hermes home, the
actual target skill file, or any support files inside the live skills tree.
It only writes inside the supplied drill target directory.

Auto-run mutating apply can be gated on the drill state so a scheduled
loop refuses (or warns) to mutate further skills when the last drill
failed or has not run since the last apply.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DRILL_STATE_FILENAME = "restore-drill-state.json"
DRILL_REPORT_FILENAME = "restore-drill-report.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def default_state_path_for_manifest(manifest_path: str | Path) -> Path:
    """Return the conventional drill-state path for a manifest's backup root.

    Each guarded apply lives in ``<backup_root>/<timestamp>/manifest.json``,
    so the drill state file is stored as
    ``<backup_root>/restore-drill-state.json``.
    """

    manifest = Path(manifest_path).resolve()
    return manifest.parent.parent / DRILL_STATE_FILENAME


def read_drill_state(state_path: str | Path) -> dict[str, Any]:
    """Read the drill state file. Missing file → empty dict."""

    state, _error = _read_drill_state_with_error(state_path)
    return state


def _read_drill_state_with_error(state_path: str | Path) -> tuple[dict[str, Any], str | None]:
    """Read drill state and preserve parse errors for safety gates."""

    path = Path(state_path)
    if not path.exists():
        return {}, None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, f"state-unreadable:{exc.__class__.__name__}"
    if not isinstance(parsed, dict):
        return {}, "state-unreadable:not-a-json-object"
    return parsed, None


def write_drill_state(state_path: str | Path, state: dict[str, Any]) -> None:
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def record_apply_in_state(
    state_path: str | Path,
    *,
    manifest_path: str | Path,
    applied_at: str | None,
    target_path: str | None = None,
    skill_name: str | None = None,
) -> dict[str, Any]:
    """Mark a new mutating apply in the drill state file.

    The next mutating auto-apply can be gated on whether a successful drill
    has run against this manifest yet.
    """

    state = read_drill_state(state_path)
    state["last_apply"] = {
        "manifest_path": str(manifest_path),
        "applied_at": applied_at or _utc_now(),
        "target_path": target_path,
        "skill_name": skill_name,
    }
    write_drill_state(state_path, state)
    return state


def record_drill_in_state(
    state_path: str | Path,
    *,
    manifest_path: str | Path,
    status: str,
    drill_at: str | None = None,
    restored_target: str | None = None,
    report_path: str | None = None,
) -> dict[str, Any]:
    """Record a completed drill into the state file."""

    state = read_drill_state(state_path)
    state["last_drill"] = {
        "manifest_path": str(manifest_path),
        "status": status,
        "drill_at": drill_at or _utc_now(),
        "restored_target": restored_target,
        "report_path": report_path,
    }
    write_drill_state(state_path, state)
    return state


def evaluate_restore_drill_gate(
    state_path: str | Path,
    *,
    require: bool = False,
) -> dict[str, Any]:
    """Decide whether the next mutating auto-apply is allowed.

    The default policy is non-blocking: callers always get a snapshot of
    drill state and a textual reason. When ``require`` is ``True`` the gate
    returns ``allowed=False`` if the last apply has no matching successful
    drill, so unattended auto-apply can refuse to widen risk.
    """

    state, state_error = _read_drill_state_with_error(state_path)
    last_apply = state.get("last_apply") if isinstance(state.get("last_apply"), dict) else None
    last_drill = state.get("last_drill") if isinstance(state.get("last_drill"), dict) else None
    snapshot = {
        "state_path": str(state_path),
        "last_apply": last_apply,
        "last_drill": last_drill,
        "require": bool(require),
    }
    if state_error:
        snapshot["state_error"] = state_error
        if require:
            return {**snapshot, "allowed": False, "reason": "restore-drill-state-unreadable"}
        return {**snapshot, "allowed": True, "reason": "restore-drill-state-unreadable-warning"}
    if not last_apply:
        return {**snapshot, "allowed": True, "reason": "no-prior-apply"}
    if last_drill is None:
        if require:
            return {**snapshot, "allowed": False, "reason": "restore-drill-missing"}
        return {**snapshot, "allowed": True, "reason": "restore-drill-missing-warning"}
    if last_drill.get("manifest_path") != last_apply.get("manifest_path"):
        if require:
            return {**snapshot, "allowed": False, "reason": "restore-drill-stale"}
        return {**snapshot, "allowed": True, "reason": "restore-drill-stale-warning"}
    if last_drill.get("status") != "pass":
        if require:
            return {**snapshot, "allowed": False, "reason": "restore-drill-failed"}
        return {**snapshot, "allowed": True, "reason": "restore-drill-failed-warning"}
    return {**snapshot, "allowed": True, "reason": "restore-drill-passed"}


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _restore_target_file(
    *,
    backup_path: Path,
    drill_root: Path,
    target_relative_name: str,
    expected_sha256: str | None,
) -> dict[str, Any]:
    """Restore the main target file into the drill root and verify it."""

    check: dict[str, Any] = {
        "name": "target-recovery",
        "status": "fail",
        "backup_path": str(backup_path),
        "restored_path": None,
        "expected_sha256": expected_sha256,
        "actual_sha256": None,
    }
    if not backup_path.exists():
        check["reason"] = "backup-missing"
        return check
    restored_path = drill_root / target_relative_name
    restored_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, restored_path)
    actual = _sha256_file(restored_path)
    check["restored_path"] = str(restored_path)
    check["actual_sha256"] = actual
    if expected_sha256 and actual != expected_sha256:
        check["reason"] = "sha256-mismatch"
        return check
    check["status"] = "pass"
    check["reason"] = "ok"
    return check


def _restore_support_files(
    *,
    support_files: list[dict[str, Any]],
    drill_root: Path,
) -> dict[str, Any]:
    """Restore any recorded support files (references/templates/scripts/assets)."""

    check: dict[str, Any] = {
        "name": "support-files-recovery",
        "status": "skipped",
        "entries": [],
    }
    if not support_files:
        check["reason"] = "no-support-files-in-manifest"
        return check
    entries: list[dict[str, Any]] = []
    failures = 0
    warnings = 0
    for raw in support_files:
        if not isinstance(raw, dict):
            warnings += 1
            entries.append({"status": "warn", "reason": "malformed-entry"})
            continue
        relative_path = str(raw.get("path") or "").strip()
        backup_path_raw = raw.get("backup_path")
        expected_sha = raw.get("sha256")
        kind = raw.get("kind") or "support"
        entry: dict[str, Any] = {
            "path": relative_path,
            "kind": kind,
            "backup_path": str(backup_path_raw) if backup_path_raw else None,
            "expected_sha256": expected_sha,
            "actual_sha256": None,
            "restored_path": None,
        }
        safe_relative = Path(relative_path)
        if (
            not relative_path
            or not backup_path_raw
            or safe_relative.is_absolute()
            or any(part == ".." for part in safe_relative.parts)
        ):
            entry["status"] = "warn"
            entry["reason"] = "unsafe-or-incomplete-entry"
            warnings += 1
            entries.append(entry)
            continue
        backup_path = Path(backup_path_raw)
        if not backup_path.exists():
            entry["status"] = "fail"
            entry["reason"] = "backup-missing"
            failures += 1
            entries.append(entry)
            continue
        restored_path = drill_root / relative_path
        restored_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, restored_path)
        actual = _sha256_file(restored_path)
        entry["actual_sha256"] = actual
        entry["restored_path"] = str(restored_path)
        if expected_sha and actual != expected_sha:
            entry["status"] = "fail"
            entry["reason"] = "sha256-mismatch"
            failures += 1
        else:
            entry["status"] = "pass"
            entry["reason"] = "ok"
        entries.append(entry)
    check["entries"] = entries
    if failures:
        check["status"] = "fail"
        check["reason"] = f"failed-entries:{failures}"
    elif warnings and not entries:
        check["status"] = "warn"
        check["reason"] = "no-restorable-entries"
    elif warnings:
        check["status"] = "warn"
        check["reason"] = f"warned-entries:{warnings}"
    else:
        check["status"] = "pass"
        check["reason"] = "ok"
    return check


def _check_evidence_refs(evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Check evidence/session store metadata recorded in the manifest.

    The drill must not mutate the live evidence database — it just verifies
    references in the manifest are well-formed and the pointed-to file
    looks like an actual SQLite database when present.
    """

    check: dict[str, Any] = {
        "name": "evidence-references",
        "status": "skipped",
    }
    if not evidence or not isinstance(evidence, dict):
        check["reason"] = "no-evidence-metadata"
        return check
    db_path = evidence.get("db_path")
    session_ids = evidence.get("session_ids") or []
    check["db_path"] = db_path
    check["session_ids"] = list(session_ids) if isinstance(session_ids, list) else None
    if not db_path:
        check["status"] = "warn"
        check["reason"] = "no-db-path"
        return check
    path = Path(str(db_path))
    if not path.exists():
        check["status"] = "warn"
        check["reason"] = "db-path-missing"
        return check
    try:
        connection = sqlite3.connect(str(path))
        try:
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        check["status"] = "fail"
        check["reason"] = f"db-not-readable:{exc.__class__.__name__}"
        return check
    check["status"] = "pass"
    check["reason"] = "ok"
    return check


def _check_provenance(provenance: dict[str, Any] | None) -> dict[str, Any]:
    """Check provenance/source metadata recorded in the manifest."""

    check: dict[str, Any] = {
        "name": "provenance-metadata",
        "status": "skipped",
    }
    if not provenance or not isinstance(provenance, dict):
        check["reason"] = "no-provenance-metadata"
        return check
    source = provenance.get("source")
    check["source"] = source
    check["writable"] = provenance.get("writable")
    check["skill_name"] = provenance.get("skill_name")
    if not source:
        check["status"] = "warn"
        check["reason"] = "missing-source"
        return check
    check["status"] = "pass"
    check["reason"] = "ok"
    return check


def _check_scheduler(scheduler: dict[str, Any] | None) -> dict[str, Any]:
    """Check scheduler/cron references recorded in the manifest."""

    check: dict[str, Any] = {
        "name": "scheduler-references",
        "status": "skipped",
    }
    if not scheduler or not isinstance(scheduler, dict):
        check["reason"] = "no-scheduler-metadata"
        return check
    paths: dict[str, str] = {}
    for key in ("service_path", "timer_path", "plist_path", "cron_path"):
        value = scheduler.get(key)
        if value:
            paths[key] = str(value)
    check["paths"] = paths
    if not paths:
        check["status"] = "warn"
        check["reason"] = "no-scheduler-paths"
        return check
    missing = [name for name, raw in paths.items() if not Path(raw).exists()]
    check["missing"] = missing
    if missing:
        check["status"] = "warn"
        check["reason"] = "scheduler-paths-missing"
    else:
        check["status"] = "pass"
        check["reason"] = "ok"
    return check


def run_restore_drill(
    manifest_path: str | Path,
    *,
    target_dir: str | Path | None = None,
    state_path: str | Path | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    """Restore a guarded-apply manifest into a clean directory and report.

    By default the drill restores into a fresh ``tempfile.mkdtemp`` and
    leaves the directory in place so the operator can inspect it. Supply
    ``target_dir`` to control the destination. The live skill file, the
    live evidence DB, and any live scheduler units are never touched.
    """

    manifest_file = Path(manifest_path).resolve()
    started = _utc_now()
    report: dict[str, Any] = {
        "schema_version": "0.1",
        "manifest_path": str(manifest_file),
        "drill_started_at": started,
        "drill_finished_at": None,
        "drill_target": None,
        "status": "fail",
        "checks": [],
        "warnings": [],
        "errors": [],
    }

    if state_path is None:
        state_path = default_state_path_for_manifest(manifest_file)

    if not manifest_file.exists():
        report["errors"].append("manifest-not-found")
        report["drill_finished_at"] = _utc_now()
        record_drill_in_state(
            state_path,
            manifest_path=manifest_file,
            status=report["status"],
            drill_at=report["drill_finished_at"],
        )
        return report

    try:
        manifest = _load_manifest(manifest_file)
    except (OSError, json.JSONDecodeError) as exc:
        report["errors"].append(f"manifest-not-readable:{exc.__class__.__name__}")
        report["drill_finished_at"] = _utc_now()
        record_drill_in_state(
            state_path,
            manifest_path=manifest_file,
            status=report["status"],
            drill_at=report["drill_finished_at"],
        )
        return report

    if target_dir is None:
        drill_root = Path(tempfile.mkdtemp(prefix="hermes-curator-evolver-drill-"))
    else:
        drill_root = Path(target_dir)
        drill_root.mkdir(parents=True, exist_ok=True)
    report["drill_target"] = str(drill_root)
    if any(drill_root.iterdir()):
        report["errors"].append("drill-target-not-empty")
        report["drill_finished_at"] = _utc_now()
        record_drill_in_state(
            state_path,
            manifest_path=manifest_file,
            status=report["status"],
            drill_at=report["drill_finished_at"],
            restored_target=None,
        )
        return report

    target_path_raw = manifest.get("target_path")
    backup_path_raw = manifest.get("backup_path")
    expected_sha = manifest.get("original_sha256")
    target_name = Path(str(target_path_raw)).name if target_path_raw else "restored-target"
    if not backup_path_raw:
        report["errors"].append("manifest-missing-backup-path")
        target_check = {
            "name": "target-recovery",
            "status": "fail",
            "reason": "manifest-missing-backup-path",
        }
    else:
        target_check = _restore_target_file(
            backup_path=Path(str(backup_path_raw)),
            drill_root=drill_root,
            target_relative_name=target_name,
            expected_sha256=expected_sha,
        )
    report["checks"].append(target_check)
    report["restored_target"] = target_check.get("restored_path")

    support_files = manifest.get("support_files")
    if not isinstance(support_files, list):
        support_files = []
    support_check = _restore_support_files(
        support_files=support_files,
        drill_root=drill_root,
    )
    report["checks"].append(support_check)

    evidence_check = _check_evidence_refs(manifest.get("evidence"))
    report["checks"].append(evidence_check)

    provenance_check = _check_provenance(manifest.get("provenance"))
    report["checks"].append(provenance_check)

    scheduler_check = _check_scheduler(manifest.get("scheduler"))
    report["checks"].append(scheduler_check)

    statuses = [check["status"] for check in report["checks"]]
    if "fail" in statuses:
        report["status"] = "fail"
    elif all(status in {"pass", "skipped"} for status in statuses):
        report["status"] = "pass"
    else:
        report["status"] = "partial"

    for check in report["checks"]:
        if check["status"] == "warn":
            report["warnings"].append(f"{check['name']}:{check.get('reason', 'warn')}")
        elif check["status"] == "fail":
            report["errors"].append(f"{check['name']}:{check.get('reason', 'fail')}")

    report["drill_finished_at"] = _utc_now()

    report_path: str | None = None
    if write_report:
        try:
            report_file = drill_root / DRILL_REPORT_FILENAME
            report_file.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            report_path = str(report_file)
        except OSError as exc:
            report["warnings"].append(f"report-write-failed:{exc.__class__.__name__}")
    report["report_path"] = report_path

    record_drill_in_state(
        state_path,
        manifest_path=manifest_file,
        status=report["status"],
        drill_at=report["drill_finished_at"],
        restored_target=report["restored_target"],
        report_path=report_path,
    )

    return report


def format_drill_report(report: dict[str, Any], *, output_format: str = "json") -> str:
    if output_format == "json":
        return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    lines = [
        "# Hermes Curator Evolver restore drill",
        "",
        f"- Manifest: `{report.get('manifest_path')}`",
        f"- Drill target: `{report.get('drill_target')}`",
        f"- Status: **{report.get('status', 'unknown')}**",
        f"- Started: {report.get('drill_started_at')}",
        f"- Finished: {report.get('drill_finished_at')}",
        "",
        "## Checks",
        "",
    ]
    for check in report.get("checks") or []:
        lines.append(f"- `{check.get('name')}` — {check.get('status')} ({check.get('reason', '')})")
    if report.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in report["warnings"])
    if report.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in report["errors"])
    return "\n".join(lines)
