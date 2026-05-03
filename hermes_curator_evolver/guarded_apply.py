"""Guarded apply and rollback helpers for reviewed skill patches."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _run_verify(command: str | None, cwd: Path | None) -> dict[str, Any]:
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


def apply_guarded_patch(
    *,
    target_path: str | Path,
    new_content: str,
    expected_sha256: str,
    approved: bool,
    backup_root: str | Path,
    verify_command: str | None = None,
    verify_cwd: str | Path | None = None,
) -> dict[str, Any]:
    """Apply a reviewed patch with approval/hash/backup/verify gates."""

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
        "schema_version": "0.4",
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
    verify = _run_verify(verify_command, Path(verify_cwd) if verify_cwd else target.parent)
    manifest["verify"] = verify
    if not verify["passed"]:
        shutil.copy2(backup_path, target)
        manifest["rolled_back"] = True
        manifest["rollback_reason"] = "verify-failed"
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
