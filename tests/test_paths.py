from pathlib import Path

import hermes_curator_evolver.paths as paths
import hermes_curator_evolver.skill_sources as skill_sources


def test_platform_default_hermes_home_uses_local_appdata_on_windows(tmp_path, monkeypatch):
    local_appdata = tmp_path / "AppData" / "Local"
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    assert paths._platform_default_hermes_home() == local_appdata / "hermes"


def test_skill_source_default_uses_shared_hermes_home(tmp_path, monkeypatch):
    active_home = tmp_path / "profiles" / "review"
    monkeypatch.setattr(skill_sources, "hermes_home", lambda: active_home)

    assert skill_sources.default_hermes_home() == active_home.resolve()


def test_explicit_skills_dir_still_identifies_its_parent_as_hermes_home(tmp_path):
    skills_dir = tmp_path / "custom-profile" / "skills"

    assert skill_sources.default_hermes_home(skills_dir) == Path(skills_dir).resolve().parent
