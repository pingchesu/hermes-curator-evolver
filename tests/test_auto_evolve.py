import json
from pathlib import Path

from hermes_curator_evolver.auto_evolve import (
    AutoEvolveConfig,
    build_low_risk_skill_update,
    discover_skill_files,
    run_auto_evolve,
)
from hermes_curator_evolver.guarded_apply import sha256_file
from hermes_curator_evolver.storage import EvidenceStore


def _write_skill(root: Path, name: str, body: str = "Use this skill for gateway troubleshooting.") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_discover_skill_files_uses_frontmatter_name(tmp_path):
    skills = tmp_path / "skills"
    skill_file = _write_skill(skills, "hermes-agent")

    discovered = discover_skill_files(skills)

    assert discovered["hermes-agent"] == skill_file


def test_low_risk_update_preserves_existing_skill_and_appends_managed_block(tmp_path):
    skill_file = _write_skill(tmp_path, "hermes-agent")
    original = skill_file.read_text(encoding="utf-8")
    evidence = [
        {
            "created_at": "2026-05-03T10:00:00+00:00",
            "tool_name": "terminal",
            "is_error": True,
            "result_preview": "exit_code 1: gateway restart failed",
        }
    ]

    updated = build_low_risk_skill_update(
        skill_name="hermes-agent",
        skill_text=original,
        days=7,
        summary={"tool_events": 3, "skill_events": 2, "error_events": 1},
        evidence_rows=evidence,
    )

    assert updated.startswith(original)
    assert "<!-- curator-evolver:auto:start -->" in updated
    assert "gateway restart failed" in updated
    assert "Low-risk append-only auto-curation" in updated


def test_auto_evolve_dry_run_plans_low_risk_updates_without_writing(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    skill_file = _write_skill(skills, "hermes-agent")
    original_hash = sha256_file(skill_file)
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result={"success": True},
        session_id="s1",
    )
    store.record_tool_call(
        tool_name="terminal",
        args={"skills": ["hermes-agent"]},
        result={"exit_code": 1, "output": "restart failed"},
        session_id="s1",
    )

    result = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            days=30,
            min_evidence=1,
            apply_low_risk=False,
            approve_auto_apply=False,
        )
    )

    assert result["mode"] == "dry-run"
    assert result["summary"]["planned"] == 1
    assert result["summary"]["applied"] == 0
    assert result["candidates"][0]["skill_name"] == "hermes-agent"
    assert result["candidates"][0]["risk"] == "low"
    assert sha256_file(skill_file) == original_hash


def test_auto_evolve_apply_low_risk_updates_skill_with_backup(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    backups = tmp_path / "backups"
    skill_file = _write_skill(skills, "hermes-agent")
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result={"success": True},
        session_id="s1",
    )

    result = run_auto_evolve(
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

    updated = skill_file.read_text(encoding="utf-8")
    assert result["mode"] == "apply-low-risk"
    assert result["summary"]["applied"] == 1
    assert result["candidates"][0]["apply_result"]["applied"] is True
    assert "Auto-curated evidence notes" in updated
    assert Path(result["candidates"][0]["apply_result"]["manifest_path"]).exists()


def test_auto_evolve_refuses_apply_without_auto_approval(tmp_path):
    db = tmp_path / "evidence.sqlite"
    store = EvidenceStore(db)
    skills = tmp_path / "skills"
    skill_file = _write_skill(skills, "hermes-agent")
    original_hash = sha256_file(skill_file)
    store.record_tool_call(
        tool_name="skill_view",
        args={"name": "hermes-agent"},
        result={"success": True},
        session_id="s1",
    )

    result = run_auto_evolve(
        AutoEvolveConfig(
            db_path=db,
            skills_dir=skills,
            days=30,
            min_evidence=1,
            apply_low_risk=True,
            approve_auto_apply=False,
        )
    )

    assert result["summary"]["applied"] == 0
    assert result["candidates"][0]["apply_result"]["reason"] == "auto-approval-required"
    assert sha256_file(skill_file) == original_hash


def test_auto_evolve_json_serializable(tmp_path):
    db = tmp_path / "evidence.sqlite"
    skills = tmp_path / "skills"
    _write_skill(skills, "empty-skill")

    result = run_auto_evolve(AutoEvolveConfig(db_path=db, skills_dir=skills))

    json.dumps(result, ensure_ascii=False, sort_keys=True)
