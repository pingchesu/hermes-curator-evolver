from pathlib import Path


def test_v0_1_source_has_no_skill_mutation_calls():
    root = Path(__file__).resolve().parents[1] / "hermes_curator_evolver"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))

    assert "skill_manage" not in source
    assert ".hermes/skills" not in source
