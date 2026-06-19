import json
from pathlib import Path

from hermes_curator_evolver.__main__ import build_parser
from hermes_curator_evolver.cli import handle_cli
from hermes_curator_evolver.skill_audit import (
    audit_skill_library,
    check_consolidation_capacity,
    inspect_skill_structure,
)


def _write_skill(root: Path, name: str, body: str = "Use this skill.") -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def test_audit_flags_large_skill_without_references(tmp_path):
    skills = tmp_path / "skills"
    skill = _write_skill(skills, "invenco-demo", "A" * 33_000)

    report = audit_skill_library(skills)
    audited = report["skills"][0]

    assert report["summary"]["risk_counts"]["high"] == 1
    assert audited["path"] == str(skill)
    assert audited["risk"] == "high"
    assert {issue["code"] for issue in audited["issues"]} >= {
        "large-main-content-size",
        "large-skill-without-references",
    }


def test_audit_excludes_archive_by_default(tmp_path):
    skills = tmp_path / "skills"
    _write_skill(skills / ".archive", "old-large", "A" * 70_000)
    _write_skill(skills, "active-small")

    active_only = audit_skill_library(skills)
    with_archive = audit_skill_library(skills, include_archive=True)

    assert active_only["total_skills"] == 1
    assert active_only["summary"]["risk_counts"]["critical"] == 0
    assert with_archive["total_skills"] == 2
    assert with_archive["summary"]["risk_counts"]["critical"] == 1


def test_inspect_skill_structure_records_executable_capacity(tmp_path):
    skills = tmp_path / "skills"
    skill = _write_skill(skills, "sangfor-devices")
    script = skill.parent / "scripts" / "probe.py"
    script.parent.mkdir()
    script.write_text("print('probe')\n", encoding="utf-8")

    structure = inspect_skill_structure(skill)

    assert structure.has_executable_capacity is True
    assert structure.executable_file_count == 1
    assert structure.executable_dirs == ["scripts"]
    assert structure.executable_paths == ["scripts/probe.py"]


def test_consolidation_check_blocks_scripted_source_into_non_executable_umbrella(tmp_path):
    skills = tmp_path / "skills"
    source = _write_skill(skills, "sangfor-devices")
    script = source.parent / "scripts" / "probe.py"
    script.parent.mkdir()
    script.write_text("print('probe')\n", encoding="utf-8")
    target = _write_skill(skills, "infrastructure")
    refs = target.parent / "references" / "network.md"
    refs.parent.mkdir()
    refs.write_text("# network\n", encoding="utf-8")

    check = check_consolidation_capacity(source.parent, target.parent)

    assert check["allowed"] is False
    assert check["missing_executable_dirs"] == ["scripts"]
    assert "source has executable capacity" in check["failures"][0]


def test_consolidation_check_allows_when_target_has_equivalent_executable_capacity(tmp_path):
    skills = tmp_path / "skills"
    source = _write_skill(skills, "network-switch-inspect")
    source_script = source.parent / "scripts" / "probe.py"
    source_script.parent.mkdir()
    source_script.write_text("print('probe')\n", encoding="utf-8")
    target = _write_skill(skills, "infrastructure")
    target_script = target.parent / "scripts" / "runner.py"
    target_script.parent.mkdir()
    target_script.write_text("print('runner')\n", encoding="utf-8")

    check = check_consolidation_capacity(source.parent, target.parent)

    assert check["allowed"] is True
    assert check["failures"] == []


def test_cli_audit_skills_emits_json(tmp_path, capsys):
    skills = tmp_path / "skills"
    _write_skill(skills, "large-router", "A" * 33_000)
    parser = build_parser()
    args = parser.parse_args(["audit-skills", "--skills-dir", str(skills), "--format", "json"])

    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["total_skills"] == 1
    assert payload["summary"]["risk_counts"]["high"] == 1


def test_cli_merge_check_emits_capacity_failure_json(tmp_path, capsys):
    skills = tmp_path / "skills"
    source = _write_skill(skills, "vmware-vcenter-ops")
    script = source.parent / "scripts" / "probe.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    target = _write_skill(skills, "infrastructure")
    parser = build_parser()
    args = parser.parse_args([
        "merge-check",
        "--source",
        str(source.parent),
        "--target",
        str(target.parent),
        "--format",
        "json",
    ])

    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["allowed"] is False
    assert payload["source"]["name"] == "vmware-vcenter-ops"
    assert payload["target"]["name"] == "infrastructure"
