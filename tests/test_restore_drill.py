import json
import sqlite3
from pathlib import Path

import pytest

from hermes_curator_evolver.__main__ import build_parser
from hermes_curator_evolver.auto_evolve import AutoEvolveConfig, run_auto_evolve
from hermes_curator_evolver.cli import handle_cli
from hermes_curator_evolver.guarded_apply import (
    apply_guarded_patch,
    register_support_file_in_manifest,
    sha256_file,
)
from hermes_curator_evolver.restore_drill import (
    DRILL_REPORT_FILENAME,
    DRILL_STATE_FILENAME,
    default_state_path_for_manifest,
    evaluate_restore_drill_gate,
    read_drill_state,
    run_restore_drill,
)
from hermes_curator_evolver.storage import EvidenceStore


def _write_skill(root: Path, name: str, body: str = "Use this skill for gateway troubleshooting.") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def _apply_for_drill(tmp_path: Path, *, target_body: str = "old content\n") -> dict:
    target = tmp_path / "SKILL.md"
    target.write_text(target_body, encoding="utf-8")
    return apply_guarded_patch(
        target_path=target,
        new_content="new content\n",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        skill_name="store-playbook",
        provenance={"source": "local-agent-created", "writable": True},
        evidence_refs={"db_path": str(tmp_path / "evidence.sqlite"), "session_ids": ["s1"]},
        scheduler_refs={"service_path": str(tmp_path / "fake.service")},
    )


def test_guarded_apply_records_drill_metadata_and_state(tmp_path):
    result = _apply_for_drill(tmp_path)

    assert result["applied"] is True
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "0.6"
    assert manifest["skill_name"] == "store-playbook"
    assert manifest["provenance"] == {
        "source": "local-agent-created",
        "writable": True,
        "skill_name": "store-playbook",
    }
    assert manifest["evidence"]["db_path"].endswith("evidence.sqlite")
    assert manifest["scheduler"]["service_path"].endswith("fake.service")
    assert manifest["support_files"] == []

    state = read_drill_state(result["drill_state_path"])
    assert state["last_apply"]["manifest_path"] == result["manifest_path"]
    assert state["last_apply"]["skill_name"] == "store-playbook"
    assert "last_drill" not in state


def test_register_support_file_snapshots_and_lists_in_manifest(tmp_path):
    result = _apply_for_drill(tmp_path)
    skill_dir = tmp_path / "skills" / "store-playbook"
    skill_dir.mkdir(parents=True)
    support_file = skill_dir / "references" / "evidence.md"
    support_file.parent.mkdir(parents=True)
    support_file.write_text("# evidence body\n", encoding="utf-8")

    recorded = register_support_file_in_manifest(
        result["manifest_path"],
        source_path=support_file,
        relative_path="references/evidence.md",
        kind="reference-spillover",
    )

    assert recorded["recorded"] is True
    entry = recorded["entry"]
    snapshot_path = Path(entry["backup_path"])
    assert snapshot_path.exists()
    assert snapshot_path.read_text(encoding="utf-8") == "# evidence body\n"
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert len(manifest["support_files"]) == 1
    assert manifest["support_files"][0]["path"] == "references/evidence.md"


def test_register_support_file_rejects_unsafe_relative_paths(tmp_path):
    result = _apply_for_drill(tmp_path)
    payload = tmp_path / "payload.md"
    payload.write_text("payload\n", encoding="utf-8")

    unsafe = register_support_file_in_manifest(
        result["manifest_path"],
        source_path=payload,
        relative_path="../escape.md",
    )
    absolute = register_support_file_in_manifest(
        result["manifest_path"],
        source_path=payload,
        relative_path=str(tmp_path / "absolute.md"),
    )

    assert unsafe["recorded"] is False
    assert unsafe["reason"] == "unsafe-relative-path"
    assert absolute["recorded"] is False
    assert absolute["reason"] == "unsafe-relative-path"


def test_run_restore_drill_passes_for_clean_manifest(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    skill_dir = tmp_path / "skills" / "store-playbook"
    support_file = skill_dir / "references" / "evidence.md"
    support_file.parent.mkdir(parents=True)
    support_file.write_text("# evidence body\n", encoding="utf-8")
    register_support_file_in_manifest(
        apply_result["manifest_path"],
        source_path=support_file,
        relative_path="references/evidence.md",
        kind="reference-spillover",
    )
    # Real SQLite DB so the evidence reference check passes.
    db_path = tmp_path / "evidence.sqlite"
    sqlite3.connect(str(db_path)).close()
    # Real fake scheduler path so the scheduler reference check passes.
    (tmp_path / "fake.service").write_text("[Service]\n", encoding="utf-8")
    drill_target = tmp_path / "drill-root"

    report = run_restore_drill(apply_result["manifest_path"], target_dir=drill_target)

    assert report["status"] == "pass"
    assert report["drill_target"] == str(drill_target)
    assert (drill_target / "SKILL.md").read_text(encoding="utf-8") == "old content\n"
    assert (drill_target / "references" / "evidence.md").read_text(encoding="utf-8") == "# evidence body\n"
    by_name = {check["name"]: check for check in report["checks"]}
    assert by_name["target-recovery"]["status"] == "pass"
    assert by_name["support-files-recovery"]["status"] == "pass"
    assert by_name["evidence-references"]["status"] == "pass"
    assert by_name["provenance-metadata"]["status"] == "pass"
    assert by_name["scheduler-references"]["status"] == "pass"
    # The drill must not touch the live SKILL file in the original path.
    assert (tmp_path / "SKILL.md").read_text(encoding="utf-8") == "new content\n"
    state = read_drill_state(default_state_path_for_manifest(apply_result["manifest_path"]))
    assert state["last_drill"]["manifest_path"] == apply_result["manifest_path"]
    assert state["last_drill"]["status"] == "pass"
    report_path = Path(report["report_path"])
    assert report_path.name == DRILL_REPORT_FILENAME
    assert report_path.exists()


def test_run_restore_drill_fails_when_backup_corrupted(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    backup = Path(apply_result["backup_path"])
    backup.write_text("CORRUPTED\n", encoding="utf-8")
    drill_target = tmp_path / "drill-root"

    report = run_restore_drill(apply_result["manifest_path"], target_dir=drill_target)

    assert report["status"] == "fail"
    target_check = next(c for c in report["checks"] if c["name"] == "target-recovery")
    assert target_check["status"] == "fail"
    assert target_check["reason"] == "sha256-mismatch"
    assert any(err.startswith("target-recovery:") for err in report["errors"])
    state = read_drill_state(default_state_path_for_manifest(apply_result["manifest_path"]))
    assert state["last_drill"]["status"] == "fail"


def test_run_restore_drill_fails_when_support_backup_missing(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    skill_dir = tmp_path / "skills" / "store-playbook"
    support_file = skill_dir / "references" / "evidence.md"
    support_file.parent.mkdir(parents=True)
    support_file.write_text("# evidence body\n", encoding="utf-8")
    register_support_file_in_manifest(
        apply_result["manifest_path"],
        source_path=support_file,
        relative_path="references/evidence.md",
        kind="reference-spillover",
    )
    # Now blow away the snapshot directory to simulate corruption.
    backup_dir = Path(apply_result["manifest_path"]).parent / "support"
    for path in backup_dir.rglob("*"):
        if path.is_file():
            path.unlink()

    report = run_restore_drill(apply_result["manifest_path"], target_dir=tmp_path / "drill")

    support_check = next(c for c in report["checks"] if c["name"] == "support-files-recovery")
    assert support_check["status"] == "fail"
    assert report["status"] == "fail"


def test_run_restore_drill_warns_and_does_not_escape_for_unsafe_support_paths(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    manifest_path = Path(apply_result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_payload = manifest_path.parent / "support" / "payload.md"
    backup_payload.parent.mkdir(parents=True)
    backup_payload.write_text("payload\n", encoding="utf-8")
    manifest["support_files"] = [
        {
            "path": "../escaped.md",
            "kind": "malicious",
            "sha256": sha256_file(backup_payload),
            "backup_path": str(backup_payload),
        },
        {
            "path": str(tmp_path / "absolute.md"),
            "kind": "malicious",
            "sha256": sha256_file(backup_payload),
            "backup_path": str(backup_payload),
        },
    ]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = run_restore_drill(manifest_path, target_dir=tmp_path / "drill")

    support_check = next(c for c in report["checks"] if c["name"] == "support-files-recovery")
    assert support_check["status"] == "warn"
    assert all(entry["reason"] == "unsafe-or-incomplete-entry" for entry in support_check["entries"])
    assert not (tmp_path / "escaped.md").exists()
    assert not (tmp_path / "absolute.md").exists()


def test_run_restore_drill_warns_when_scheduler_paths_missing(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    # Provide an SQLite DB so evidence check passes; leave scheduler path missing.
    db_path = tmp_path / "evidence.sqlite"
    sqlite3.connect(str(db_path)).close()

    report = run_restore_drill(apply_result["manifest_path"], target_dir=tmp_path / "drill")

    scheduler_check = next(c for c in report["checks"] if c["name"] == "scheduler-references")
    assert scheduler_check["status"] == "warn"
    assert "scheduler-references" in " ".join(report["warnings"])
    assert report["status"] == "partial"


def test_evaluate_restore_drill_gate_blocks_only_when_required(tmp_path):
    state_path = tmp_path / DRILL_STATE_FILENAME
    state_path.write_text(
        json.dumps(
            {
                "last_apply": {"manifest_path": "m.json", "applied_at": "t1"},
                "last_drill": {"manifest_path": "older.json", "status": "pass", "drill_at": "t0"},
            }
        ),
        encoding="utf-8",
    )

    warn_gate = evaluate_restore_drill_gate(state_path, require=False)
    block_gate = evaluate_restore_drill_gate(state_path, require=True)

    assert warn_gate["allowed"] is True
    assert warn_gate["reason"] == "restore-drill-stale-warning"
    assert block_gate["allowed"] is False
    assert block_gate["reason"] == "restore-drill-stale"


def test_evaluate_restore_drill_gate_blocks_unreadable_state_when_required(tmp_path):
    state_path = tmp_path / DRILL_STATE_FILENAME
    state_path.write_text("{not-json", encoding="utf-8")

    warn_gate = evaluate_restore_drill_gate(state_path, require=False)
    block_gate = evaluate_restore_drill_gate(state_path, require=True)

    assert warn_gate["allowed"] is True
    assert warn_gate["reason"] == "restore-drill-state-unreadable-warning"
    assert block_gate["allowed"] is False
    assert block_gate["reason"] == "restore-drill-state-unreadable"
    assert block_gate["state_error"].startswith("state-unreadable:")


def test_run_restore_drill_fails_without_overwriting_non_empty_target_dir(tmp_path):
    apply_result = _apply_for_drill(tmp_path)
    drill_target = tmp_path / "drill"
    drill_target.mkdir()
    existing = drill_target / "SKILL.md"
    existing.write_text("operator data\n", encoding="utf-8")

    report = run_restore_drill(apply_result["manifest_path"], target_dir=drill_target)

    assert report["status"] == "fail"
    assert "drill-target-not-empty" in report["errors"]
    assert existing.read_text(encoding="utf-8") == "operator data\n"


def test_run_restore_drill_records_failed_state_for_unreadable_manifest(tmp_path):
    manifest = tmp_path / "backups" / "run1" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{not-json", encoding="utf-8")

    report = run_restore_drill(manifest, target_dir=tmp_path / "drill")

    assert report["status"] == "fail"
    assert any(err.startswith("manifest-not-readable:") for err in report["errors"])
    state = read_drill_state(default_state_path_for_manifest(manifest))
    assert state["last_drill"]["manifest_path"] == str(manifest.resolve())
    assert state["last_drill"]["status"] == "fail"


def test_auto_run_warns_when_drill_missing_and_still_applies(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    backups = tmp_path / "backups"
    _write_skill(skills, "store-playbook")
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "store-playbook"},
        result={"success": True},
        session_id="s1",
    )

    first = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            backup_dir=backups,
            days=30,
            min_evidence=1,
            apply_low_risk=True,
            approve_auto_apply=True,
        )
    )
    second = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            backup_dir=backups,
            days=30,
            min_evidence=1,
            apply_low_risk=True,
            approve_auto_apply=True,
        )
    )

    assert first["summary"]["applied"] == 1
    # First pass had no prior apply, gate ends after this run reporting last_apply.
    gate_after_first = first["safety"]["restore_drill_gate"]
    assert gate_after_first["last_apply"]["skill_name"] == "store-playbook"
    # Second pass should warn but still apply (require_restore_drill default False).
    second_gate = second["safety"]["restore_drill_gate"]
    assert second_gate["allowed"] is True
    assert second_gate["reason"].endswith("-warning")
    assert second["summary"]["applied"] == 1


def test_auto_run_blocks_subsequent_apply_when_drill_required(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    backups = tmp_path / "backups"
    skill_a = _write_skill(skills, "store-playbook")
    skill_b = _write_skill(skills, "deploy-playbook")
    original_a = skill_a.read_text(encoding="utf-8")
    original_b = skill_b.read_text(encoding="utf-8")
    for name in ("store-playbook", "deploy-playbook"):
        store.record_tool_call(
            tool_name="skill_view",
            args={"name": name},
            result={"success": True},
            session_id=f"s-{name}",
        )

    first = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            backup_dir=backups,
            days=30,
            min_evidence=1,
            max_skills=5,
            apply_low_risk=True,
            approve_auto_apply=True,
            require_restore_drill=True,
        )
    )

    # First skill applies (no prior apply yet, so the gate allows it).
    # The act of applying the first skill makes the gate fail for the second.
    statuses = {c["skill_name"]: c["status"] for c in first["candidates"]}
    reasons = {c["skill_name"]: c.get("reason") for c in first["candidates"]}
    assert "applied" in statuses.values()
    skipped_for_drill = [name for name, status in statuses.items() if status == "skipped" and reasons[name] == "restore-drill-required"]
    assert skipped_for_drill, "second skill in the same pass should be blocked by the drill gate"
    blocked_name = skipped_for_drill[0]
    blocked_path = {"deploy-playbook": skill_b, "store-playbook": skill_a}[blocked_name]
    blocked_original = {"deploy-playbook": original_b, "store-playbook": original_a}[blocked_name]
    assert blocked_path.read_text(encoding="utf-8") == blocked_original
    # safety reflects the require flag and shows the post-apply gate failure.
    assert first["safety"]["require_restore_drill"] is True
    assert first["safety"]["restore_drill_gate"]["require"] is True


def test_auto_run_blocks_first_apply_when_drill_missing_after_prior_apply(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    backups = tmp_path / "backups"
    _write_skill(skills, "store-playbook")
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "store-playbook"},
        result={"success": True},
        session_id="s1",
    )

    # First pass: apply once without requiring drill.
    run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            backup_dir=backups,
            days=30,
            min_evidence=1,
            apply_low_risk=True,
            approve_auto_apply=True,
        )
    )

    # Second pass with require_restore_drill must block because no drill ran.
    second = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            backup_dir=backups,
            days=30,
            min_evidence=1,
            apply_low_risk=True,
            approve_auto_apply=True,
            require_restore_drill=True,
        )
    )

    candidate = second["candidates"][0]
    assert candidate["status"] == "skipped"
    assert candidate["reason"] == "restore-drill-required"
    assert second["summary"]["applied"] == 0


def test_cli_restore_drill_emits_json_and_handles_missing_manifest(tmp_path, capsys):
    apply_result = _apply_for_drill(tmp_path)
    parser = build_parser()
    args = parser.parse_args([
        "restore-drill",
        "--manifest",
        apply_result["manifest_path"],
        "--target-dir",
        str(tmp_path / "drill-cli"),
        "--format",
        "json",
    ])

    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest_path"].endswith("manifest.json")
    assert payload["drill_target"] == str(tmp_path / "drill-cli")
    assert payload["status"] in {"pass", "partial", "fail"}


def test_cli_restore_drill_reports_missing_manifest(tmp_path, capsys):
    parser = build_parser()
    missing_manifest = tmp_path / "does-not-exist" / "manifest.json"
    args = parser.parse_args([
        "restore-drill",
        "--manifest",
        str(missing_manifest),
        "--format",
        "json",
    ])

    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fail"
    assert "manifest-not-found" in payload["errors"]


def test_cli_parser_accepts_restore_drill_subcommand():
    parser = build_parser()
    args = parser.parse_args([
        "restore-drill",
        "--manifest",
        "manifest.json",
        "--target-dir",
        "drill",
        "--state-file",
        "state.json",
        "--format",
        "json",
    ])
    assert args.curator_evolver_command == "restore-drill"
    assert args.manifest == "manifest.json"
    assert args.target_dir == "drill"
    assert args.state_file == "state.json"
    assert args.format == "json"


def test_cli_parser_accepts_require_restore_drill_flag():
    parser = build_parser()
    args = parser.parse_args([
        "auto-run",
        "--skills-dir",
        "skills",
        "--apply-low-risk",
        "--approve-auto-apply",
        "--require-restore-drill",
        "--restore-drill-state-file",
        "state.json",
    ])
    assert args.require_restore_drill is True
    assert args.restore_drill_state_file == "state.json"
