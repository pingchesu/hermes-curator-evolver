"""Skill source provenance for safe unattended auto-apply.

The evolver must not rely on skill-name globs alone. Hermes already tracks which
skills came from bundled/official sources and the skills hub; user config may also
expose shared read-only trees via ``skills.external_dirs``. This module mirrors
that provenance locally so the plugin can keep Hermes core untouched while only
mutating local agent-created skills.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is present in Hermes envs.
    yaml = None  # type: ignore[assignment]

SOURCE_LOCAL_AGENT_CREATED = "local-agent-created"
SOURCE_BUNDLED = "bundled"
SOURCE_HUB_INSTALLED = "hub-installed"
SOURCE_EXTERNAL_DIR = "external-dir"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class SkillSourceContext:
    """Resolved source metadata for one auto-evolve pass."""

    hermes_home: Path
    local_skills_dir: Path
    bundled_names: frozenset[str]
    hub_installed_names: frozenset[str]
    external_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class SkillSourceInfo:
    """Source classification for a single SKILL.md file."""

    source: str
    writable: bool


def default_hermes_home(skills_dir: str | Path | None = None) -> Path:
    """Return the active Hermes home, inferring from explicit ``skills_dir`` first."""

    if skills_dir is not None:
        candidate = Path(skills_dir).expanduser()
        try:
            candidate = candidate.resolve()
        except OSError:
            pass
        if candidate.name == "skills":
            return candidate.parent

    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        return Path(os.path.expanduser(os.path.expandvars(env_home))).resolve()

    return (Path.home() / ".hermes").resolve()


def _read_bundled_manifest_names(local_skills_dir: Path) -> frozenset[str]:
    manifest = local_skills_dir / ".bundled_manifest"
    if not manifest.exists():
        return frozenset()
    names: set[str] = set()
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            name = stripped.split(":", 1)[0].strip()
            if name:
                names.add(name)
    except OSError:
        return frozenset()
    return frozenset(names)


def _read_hub_installed_names(local_skills_dir: Path) -> frozenset[str]:
    lock_path = local_skills_dir / ".hub" / "lock.json"
    if not lock_path.exists():
        return frozenset()
    try:
        parsed = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return frozenset()
    if not isinstance(parsed, dict):
        return frozenset()
    installed = parsed.get("installed")
    if not isinstance(installed, dict):
        return frozenset()
    return frozenset(str(name) for name in installed.keys() if str(name).strip())


def _load_config(hermes_home: Path) -> dict[str, Any]:
    config_path = hermes_home / "config.yaml"
    if not config_path.exists() or yaml is None:
        return {}
    try:
        parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _read_external_dirs(hermes_home: Path, local_skills_dir: Path) -> tuple[Path, ...]:
    config = _load_config(hermes_home)
    skills_cfg = config.get("skills")
    if not isinstance(skills_cfg, dict):
        return ()
    raw_dirs = skills_cfg.get("external_dirs")
    if not raw_dirs:
        return ()
    if isinstance(raw_dirs, str):
        raw_entries = [raw_dirs]
    elif isinstance(raw_dirs, list):
        raw_entries = raw_dirs
    else:
        return ()

    result: list[Path] = []
    seen: set[Path] = set()
    try:
        local_resolved = local_skills_dir.resolve()
    except OSError:
        local_resolved = local_skills_dir

    for raw_entry in raw_entries:
        entry = str(raw_entry).strip()
        if not entry:
            continue
        expanded = os.path.expanduser(os.path.expandvars(entry))
        path = Path(expanded)
        if not path.is_absolute():
            path = hermes_home / path
        try:
            path = path.resolve()
        except OSError:
            continue
        if path == local_resolved or path in seen:
            continue
        if not path.is_dir():
            continue
        seen.add(path)
        result.append(path)
    return tuple(result)


def build_skill_source_context(skills_dir: str | Path | None = None) -> SkillSourceContext:
    """Build provenance context for the current Hermes profile."""

    hermes_home = default_hermes_home(skills_dir)
    local_skills_dir = hermes_home / "skills"
    return SkillSourceContext(
        hermes_home=hermes_home,
        local_skills_dir=local_skills_dir,
        bundled_names=_read_bundled_manifest_names(local_skills_dir),
        hub_installed_names=_read_hub_installed_names(local_skills_dir),
        external_dirs=_read_external_dirs(hermes_home, local_skills_dir),
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def classify_skill_source(
    *,
    skill_name: str,
    skill_file: str | Path,
    context: SkillSourceContext,
) -> SkillSourceInfo:
    """Classify a skill file and whether unattended auto-apply may write it."""

    path = Path(skill_file)
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path

    for external_dir in context.external_dirs:
        if _is_relative_to(resolved, external_dir):
            return SkillSourceInfo(source=SOURCE_EXTERNAL_DIR, writable=False)

    if skill_name in context.bundled_names:
        return SkillSourceInfo(source=SOURCE_BUNDLED, writable=False)

    if skill_name in context.hub_installed_names:
        return SkillSourceInfo(source=SOURCE_HUB_INSTALLED, writable=False)

    try:
        local_skills_dir = context.local_skills_dir.resolve()
    except OSError:
        local_skills_dir = context.local_skills_dir
    if _is_relative_to(resolved, local_skills_dir):
        return SkillSourceInfo(source=SOURCE_LOCAL_AGENT_CREATED, writable=True)

    return SkillSourceInfo(source=SOURCE_UNKNOWN, writable=False)
