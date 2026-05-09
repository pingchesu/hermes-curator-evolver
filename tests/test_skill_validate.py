import json

from hermes_curator_evolver.skill_validate import main, validate_skill_file


def test_validate_skill_file_accepts_valid_skill(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        encoding="utf-8",
    )

    result = validate_skill_file(skill)

    assert result["ok"] is True
    assert result["name"] == "demo"


def test_validate_skill_file_rejects_broken_auto_block(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\n<!-- curator-evolver:auto:start -->\n",
        encoding="utf-8",
    )

    result = validate_skill_file(skill)

    assert result["ok"] is False
    assert "curator-evolver auto block markers are unbalanced" in result["errors"]


def test_main_prefers_guarded_apply_target_env(tmp_path, monkeypatch, capsys):
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_CURATOR_TARGET_PATH", str(skill))

    assert main([]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["target_from_env"] is True
    assert payload["checked"] == 1
