"""Validate SKILL.md files after guarded curator-evolver applies.

This module is intentionally deterministic and local-only. It is designed to be
used as a `--verify-command` target after each guarded apply. When the guarded
apply layer provides `HERMES_CURATOR_TARGET_PATH`, only that changed skill is
validated so unrelated pre-existing skill issues do not block rollback decisions.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml

AUTO_START = "<!-- curator-evolver:auto:start -->"
AUTO_END = "<!-- curator-evolver:auto:end -->"


def _frontmatter(text: str) -> tuple[dict[str, Any] | None, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, "missing opening YAML frontmatter delimiter"
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return None, "missing closing YAML frontmatter delimiter"
    raw = "\n".join(lines[1:end_index])
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        return None, f"invalid YAML frontmatter: {exc}"
    if not isinstance(data, dict):
        return None, "YAML frontmatter must be a mapping"
    return data, None


def validate_skill_file(path: str | Path) -> dict[str, Any]:
    skill = Path(path)
    errors: list[str] = []
    if not skill.exists() or not skill.is_file():
        return {"path": str(skill), "ok": False, "errors": ["skill file not found"]}
    if skill.name != "SKILL.md":
        errors.append("target must be named SKILL.md")
    try:
        text = skill.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return {"path": str(skill), "ok": False, "errors": [f"not valid UTF-8: {exc}"]}
    if "\x00" in text:
        errors.append("contains NUL byte")
    meta, err = _frontmatter(text)
    if err:
        errors.append(err)
        meta = {}
    for key in ("name", "description"):
        value = (meta or {}).get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"frontmatter.{key} is required")
    start_count = text.count(AUTO_START)
    end_count = text.count(AUTO_END)
    if start_count != end_count:
        errors.append("curator-evolver auto block markers are unbalanced")
    if start_count > 1:
        errors.append("multiple curator-evolver auto blocks found")
    return {
        "path": str(skill),
        "ok": not errors,
        "name": (meta or {}).get("name"),
        "description_present": bool((meta or {}).get("description")),
        "auto_block_count": start_count,
        "errors": errors,
    }


def _expand_targets(paths: list[str]) -> list[Path]:
    targets: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            targets.extend(sorted(path.rglob("SKILL.md")))
        else:
            targets.append(path)
    return targets


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Hermes SKILL.md files for curator-evolver guarded apply")
    parser.add_argument("paths", nargs="*", help="SKILL.md files or directories; defaults to HERMES_CURATOR_TARGET_PATH or cwd")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)

    env_target = os.environ.get("HERMES_CURATOR_TARGET_PATH")
    raw_targets = args.paths or ([env_target] if env_target else [os.getcwd()])
    targets = _expand_targets([str(p) for p in raw_targets if p])
    results = [validate_skill_file(path) for path in targets]
    ok = bool(results) and all(item["ok"] for item in results)
    payload = {
        "ok": ok,
        "checked": len(results),
        "target_from_env": bool(env_target and not args.paths),
        "results": results,
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"ok={ok} checked={len(results)}")
        for item in results:
            status = "ok" if item["ok"] else "failed"
            print(f"{status}: {item['path']}")
            for error in item.get("errors") or []:
                print(f"  - {error}")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
