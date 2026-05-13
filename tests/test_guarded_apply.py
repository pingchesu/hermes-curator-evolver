import json
import sys
from pathlib import Path

from hermes_curator_evolver.guarded_apply import (
    apply_guarded_patch,
    rollback_guarded_patch,
    sha256_file,
)


def test_guarded_apply_requires_explicit_approval(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=False,
        backup_root=tmp_path / "backups",
    )

    assert result["applied"] is False
    assert result["reason"] == "approval-required"
    assert target.read_text(encoding="utf-8") == "old"


def test_guarded_apply_rejects_hash_mismatch(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256="wrong",
        approved=True,
        backup_root=tmp_path / "backups",
    )

    assert result["applied"] is False
    assert result["reason"] == "hash-mismatch"
    assert target.read_text(encoding="utf-8") == "old"


def test_guarded_apply_creates_backup_and_rollback_restores(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    original_hash = sha256_file(target)

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=original_hash,
        approved=True,
        backup_root=tmp_path / "backups",
    )

    assert result["applied"] is True
    assert target.read_text(encoding="utf-8") == "new"
    manifest = Path(result["manifest_path"])
    assert manifest.exists()
    assert Path(result["backup_path"]).read_text(encoding="utf-8") == "old"

    rollback = rollback_guarded_patch(manifest)

    assert rollback["rolled_back"] is True
    assert target.read_text(encoding="utf-8") == "old"
    assert json.loads(manifest.read_text(encoding="utf-8"))["rolled_back"] is True


def test_guarded_apply_rolls_back_when_verify_command_fails(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    original_hash = sha256_file(target)

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=original_hash,
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command="exit 7",
        verify_cwd=tmp_path,
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "old"
    assert result["verify"]["exit_code"] == 7


def test_guarded_apply_rolls_back_when_verify_command_errors(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    original_hash = sha256_file(target)

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=original_hash,
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command="echo should-not-run",
        verify_cwd=tmp_path / "missing",
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "old"
    assert result["verify"]["passed"] is False


def test_rollback_refuses_to_clobber_post_apply_changes_without_force(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
    )
    target.write_text("manual edit after apply", encoding="utf-8")

    rollback = rollback_guarded_patch(result["manifest_path"])

    assert rollback["rolled_back"] is False
    assert rollback["reason"] == "target-changed"
    assert target.read_text(encoding="utf-8") == "manual edit after apply"

    forced = rollback_guarded_patch(result["manifest_path"], force=True)

    assert forced["rolled_back"] is True
    assert target.read_text(encoding="utf-8") == "old"


def test_staged_verify_runs_cheap_stage_then_expensive_when_cheap_passes(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    marker = tmp_path / "expensive-ran.txt"

    result = apply_guarded_patch(
        target_path=target,
        new_content="new content",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command=f"{sys.executable} -c \"open('{marker}', 'w').write('ran')\"",
        verify_cwd=tmp_path,
        staged_verify=True,
    )

    assert result["applied"] is True
    assert marker.exists(), "expensive stage should run when cheap stage passes"
    verify = result["verify"]
    assert verify["staged"] is True
    stage_names = [stage["name"] for stage in verify["stages"]]
    assert stage_names == ["builtin-structural", "verify-command"]
    assert all(stage["passed"] for stage in verify["stages"])


def test_staged_verify_skips_expensive_stage_when_cheap_stage_fails(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    marker = tmp_path / "expensive-ran.txt"
    huge_content = "<!-- curator-evolver:auto:start -->\n" + ("X" * 200_000) + "\n<!-- curator-evolver:auto:end -->\n"

    result = apply_guarded_patch(
        target_path=target,
        new_content=huge_content,
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command=f"{sys.executable} -c \"open('{marker}', 'w').write('ran')\"",
        verify_cwd=tmp_path,
        staged_verify=True,
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "old", "rollback should restore the original file"
    assert not marker.exists(), "expensive stage must not run when cheap stage fails"
    verify = result["verify"]
    assert verify["staged"] is True
    assert verify["failed_stage"] == "builtin-structural"
    assert verify["stages"][0]["passed"] is False


def test_staged_verify_rolls_back_when_expensive_stage_fails(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")

    result = apply_guarded_patch(
        target_path=target,
        new_content="new content",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command="exit 9",
        verify_cwd=tmp_path,
        staged_verify=True,
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "old"
    verify = result["verify"]
    assert verify["staged"] is True
    assert verify["failed_stage"] == "verify-command"
    assert verify["exit_code"] == 9
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["rolled_back"] is True
    assert manifest["rollback_failed_stage"] == "verify-command"


def test_staged_verify_runs_pre_verify_command_before_expensive(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    pre_marker = tmp_path / "pre.txt"
    expensive_marker = tmp_path / "expensive.txt"

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        pre_verify_command=f"{sys.executable} -c \"open('{pre_marker}','w').write('p')\"",
        verify_command=f"{sys.executable} -c \"open('{expensive_marker}','w').write('e')\"",
        verify_cwd=tmp_path,
    )

    assert result["applied"] is True
    assert pre_marker.exists() and expensive_marker.exists()
    stage_names = [stage["name"] for stage in result["verify"]["stages"]]
    assert stage_names == ["builtin-structural", "pre-verify-command", "verify-command"]


def test_staged_verify_pre_command_failure_skips_expensive_stage(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    expensive_marker = tmp_path / "expensive.txt"

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        pre_verify_command="exit 3",
        verify_command=f"{sys.executable} -c \"open('{expensive_marker}','w').write('e')\"",
        verify_cwd=tmp_path,
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "old"
    assert not expensive_marker.exists()
    assert result["verify"]["failed_stage"] == "pre-verify-command"


def test_non_staged_verify_remains_backward_compatible(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command="true",
        verify_cwd=tmp_path,
    )

    verify = result["verify"]
    assert result["applied"] is True
    assert verify["passed"] is True
    assert "stages" not in verify
    assert verify.get("staged") is not True


def test_guarded_apply_exposes_target_context_to_verify_command(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("old", encoding="utf-8")
    seen = tmp_path / "seen.json"
    verifier = tmp_path / "verify_env.py"
    verifier.write_text(
        "import json, os, pathlib\n"
        f"pathlib.Path({str(seen)!r}).write_text(json.dumps({{\n"
        "    'target': os.environ.get('HERMES_CURATOR_TARGET_PATH'),\n"
        "    'backup': os.environ.get('HERMES_CURATOR_BACKUP_PATH'),\n"
        "    'manifest': os.environ.get('HERMES_CURATOR_MANIFEST_PATH'),\n"
        "    'new_sha': os.environ.get('HERMES_CURATOR_NEW_SHA256'),\n"
        "}))\n",
        encoding="utf-8",
    )

    result = apply_guarded_patch(
        target_path=target,
        new_content="new",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command=f"{sys.executable} {verifier}",
        verify_cwd=tmp_path,
    )

    assert result["applied"] is True
    data = json.loads(seen.read_text(encoding="utf-8"))
    assert data["target"] == str(target)
    assert data["backup"] == result["backup_path"]
    assert data["manifest"] == result["manifest_path"]
    assert data["new_sha"] == result["new_sha256"]


def test_staged_verify_rolls_back_invalid_yaml_frontmatter(tmp_path):
    target = tmp_path / "SKILL.md"
    target.write_text("---\nname: old\n---\n\n# Old\n", encoding="utf-8")
    marker = tmp_path / "expensive-ran.txt"

    result = apply_guarded_patch(
        target_path=target,
        new_content="---\nname: [\n---\n\n# Broken\n",
        expected_sha256=sha256_file(target),
        approved=True,
        backup_root=tmp_path / "backups",
        verify_command=f"{sys.executable} -c \"open('{marker}', 'w').write('ran')\"",
        verify_cwd=tmp_path,
        staged_verify=True,
    )

    assert result["applied"] is False
    assert result["reason"] == "verify-failed"
    assert target.read_text(encoding="utf-8") == "---\nname: old\n---\n\n# Old\n"
    assert not marker.exists(), "expensive stage must not run after invalid frontmatter"
    verify = result["verify"]
    assert verify["failed_stage"] == "builtin-structural"
    assert verify["stages"][0]["passed"] is False
    assert "frontmatter-not-parseable" in verify["stages"][0]["reason"]
