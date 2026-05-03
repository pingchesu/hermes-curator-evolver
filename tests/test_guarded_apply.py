import json
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
