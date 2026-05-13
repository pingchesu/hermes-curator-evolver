"""Guarded apply and rollback helpers for reviewed skill patches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


_MANAGED_BLOCK_START = "<!-- curator-evolver:auto:start -->"
_MANAGED_BLOCK_END = "<!-- curator-evolver:auto:end -->"
_BUILTIN_HARD_CAP_CHARS = 100_000


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _run_verify(command: str | None, cwd: Path | None, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not command:
        return {"enabled": False, "passed": True, "exit_code": 0, "output": ""}
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "enabled": True,
            "passed": False,
            "exit_code": 124,
            "output": f"verification timed out after {exc.timeout} seconds",
        }
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {
            "enabled": True,
            "passed": False,
            "exit_code": 125,
            "output": f"verification failed to start: {exc}",
        }
    return {
        "enabled": True,
        "passed": completed.returncode == 0,
        "exit_code": completed.returncode,
        "output": completed.stdout[-4000:],
    }


def _run_builtin_cheap_check(target: Path) -> dict[str, Any]:
    """In-process structural check for the post-write SKILL.md.

    This is the cheap stage of the staged verifier gate. It enforces invariants
    the plugin already promises (size cap and managed-block boundedness) so an
    expensive `verify_command` only runs when the file at least looks sane.
    """

    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {
            "name": "builtin-structural",
            "enabled": True,
            "passed": False,
            "reason": f"read-failed: {exc}",
        }
    failures: list[str] = []
    if len(text) > _BUILTIN_HARD_CAP_CHARS:
        failures.append(f"over-hard-cap:{len(text)}>{_BUILTIN_HARD_CAP_CHARS}")
    start_count = text.count(_MANAGED_BLOCK_START)
    end_count = text.count(_MANAGED_BLOCK_END)
    if start_count != end_count:
        failures.append(f"unbalanced-managed-block-markers:{start_count}!={end_count}")
    if start_count > 1:
        failures.append(f"duplicate-managed-block:{start_count}")
    if start_count == 1:
        if text.find(_MANAGED_BLOCK_END) <= text.find(_MANAGED_BLOCK_START):
            failures.append("managed-block-end-before-start")
    if text.startswith("---"):
        match = re.match(r"^---\s*\n(?P<body>.*?)\n---\s*\n", text, re.DOTALL)
        if not match:
            failures.append("frontmatter-not-parseable")
        else:
            try:
                parsed = yaml.safe_load(match.group("body")) or {}
            except yaml.YAMLError as exc:
                failures.append(f"frontmatter-not-parseable:{exc.__class__.__name__}")
            else:
                if not isinstance(parsed, dict):
                    failures.append("frontmatter-not-mapping")
    return {
        "name": "builtin-structural",
        "enabled": True,
        "passed": not failures,
        "reason": "ok" if not failures else ",".join(failures),
        "content_chars": len(text),
    }


def _run_staged_verify(
    *,
    target: Path,
    pre_verify_command: str | None,
    verify_command: str | None,
    verify_cwd: Path | None,
    env: dict[str, str],
) -> dict[str, Any]:
    """Run the cheap-then-expensive verifier chain.

    The aggregate result is returned in a backward-compatible shape:
    ``passed`` / ``exit_code`` / ``output`` reflect the first failing stage,
    or the final stage if all passed. A ``stages`` list exposes each stage's
    individual result. ``enabled`` is True if any stage actually ran.
    """

    stages: list[dict[str, Any]] = []

    cheap = _run_builtin_cheap_check(target)
    stages.append(cheap)
    if not cheap["passed"]:
        return {
            "enabled": True,
            "staged": True,
            "passed": False,
            "exit_code": 1,
            "output": f"builtin-structural check failed: {cheap.get('reason')}",
            "failed_stage": cheap["name"],
            "stages": stages,
        }

    if pre_verify_command:
        pre = _run_verify(pre_verify_command, verify_cwd, env=env)
        pre_stage = {"name": "pre-verify-command", **pre}
        stages.append(pre_stage)
        if not pre["passed"]:
            return {
                "enabled": True,
                "staged": True,
                "passed": False,
                "exit_code": pre["exit_code"],
                "output": pre["output"],
                "failed_stage": pre_stage["name"],
                "stages": stages,
            }

    if verify_command:
        expensive = _run_verify(verify_command, verify_cwd, env=env)
        expensive_stage = {"name": "verify-command", **expensive}
        stages.append(expensive_stage)
        if not expensive["passed"]:
            return {
                "enabled": True,
                "staged": True,
                "passed": False,
                "exit_code": expensive["exit_code"],
                "output": expensive["output"],
                "failed_stage": expensive_stage["name"],
                "stages": stages,
            }
        return {
            "enabled": True,
            "staged": True,
            "passed": True,
            "exit_code": expensive["exit_code"],
            "output": expensive["output"],
            "stages": stages,
        }

    return {
        "enabled": True,
        "staged": True,
        "passed": True,
        "exit_code": 0,
        "output": "",
        "stages": stages,
    }


def apply_guarded_patch(
    *,
    target_path: str | Path,
    new_content: str,
    expected_sha256: str,
    approved: bool,
    backup_root: str | Path,
    verify_command: str | None = None,
    verify_cwd: str | Path | None = None,
    pre_verify_command: str | None = None,
    staged_verify: bool = False,
) -> dict[str, Any]:
    """Apply a reviewed patch with approval/hash/backup/verify gates.

    When ``staged_verify`` is set (or a ``pre_verify_command`` is provided), a
    cheap in-process structural check runs first, then an optional cheap
    ``pre_verify_command``, then the existing ``verify_command``. The expensive
    stage is skipped entirely if any earlier stage fails, and any failure after
    the write triggers the same rollback path callers already rely on. The
    returned ``verify`` dict keeps ``passed`` / ``exit_code`` / ``output`` for
    backward compatibility and adds a ``stages`` list when staged verification
    is in use.
    """

    target = Path(target_path)
    if not approved:
        return {"applied": False, "reason": "approval-required"}
    if not target.exists() or not target.is_file():
        return {"applied": False, "reason": "target-not-found", "target_path": str(target)}
    current_hash = sha256_file(target)
    if current_hash != expected_sha256:
        return {
            "applied": False,
            "reason": "hash-mismatch",
            "target_path": str(target),
            "current_sha256": current_hash,
            "expected_sha256": expected_sha256,
        }

    backup_dir = Path(backup_root) / _timestamp()
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_path = backup_dir / target.name
    shutil.copy2(target, backup_path)
    manifest_path = backup_dir / "manifest.json"
    manifest = {
        "schema_version": "0.5",
        "target_path": str(target),
        "backup_path": str(backup_path),
        "original_sha256": current_hash,
        "new_sha256": None,
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rolled_back": False,
        "verify": None,
    }
    _write_manifest(manifest_path, manifest)

    target.write_text(new_content, encoding="utf-8")
    manifest["new_sha256"] = sha256_file(target)
    verify_env = {
        "HERMES_CURATOR_TARGET_PATH": str(target),
        "HERMES_CURATOR_BACKUP_PATH": str(backup_path),
        "HERMES_CURATOR_MANIFEST_PATH": str(manifest_path),
        "HERMES_CURATOR_ORIGINAL_SHA256": current_hash,
        "HERMES_CURATOR_NEW_SHA256": str(manifest["new_sha256"]),
    }
    use_staged = bool(staged_verify or pre_verify_command)
    if use_staged:
        verify = _run_staged_verify(
            target=target,
            pre_verify_command=pre_verify_command,
            verify_command=verify_command,
            verify_cwd=Path(verify_cwd) if verify_cwd else target.parent,
            env=verify_env,
        )
    else:
        verify = _run_verify(
            verify_command,
            Path(verify_cwd) if verify_cwd else target.parent,
            env=verify_env,
        )
    manifest["verify"] = verify
    if not verify["passed"]:
        shutil.copy2(backup_path, target)
        manifest["rolled_back"] = True
        manifest["rollback_reason"] = "verify-failed"
        if verify.get("failed_stage"):
            manifest["rollback_failed_stage"] = verify["failed_stage"]
        _write_manifest(manifest_path, manifest)
        return {
            "applied": False,
            "reason": "verify-failed",
            "target_path": str(target),
            "backup_path": str(backup_path),
            "manifest_path": str(manifest_path),
            "verify": verify,
        }

    _write_manifest(manifest_path, manifest)
    return {
        "applied": True,
        "reason": "applied",
        "target_path": str(target),
        "backup_path": str(backup_path),
        "manifest_path": str(manifest_path),
        "new_sha256": manifest["new_sha256"],
        "verify": verify,
    }


def rollback_guarded_patch(manifest_path: str | Path, *, force: bool = False) -> dict[str, Any]:
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    target = Path(manifest["target_path"])
    backup = Path(manifest["backup_path"])
    if not backup.exists():
        return {"rolled_back": False, "reason": "backup-not-found"}
    expected_current = manifest.get("new_sha256")
    if target.exists() and expected_current and sha256_file(target) != expected_current and not force:
        return {
            "rolled_back": False,
            "reason": "target-changed",
            "target_path": str(target),
            "expected_sha256": expected_current,
            "current_sha256": sha256_file(target),
        }
    shutil.copy2(backup, target)
    manifest["rolled_back"] = True
    manifest["rolled_back_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_manifest(manifest_file, manifest)
    return {
        "rolled_back": True,
        "reason": "rolled-back",
        "target_path": str(target),
        "backup_path": str(backup),
        "manifest_path": str(manifest_file),
    }
