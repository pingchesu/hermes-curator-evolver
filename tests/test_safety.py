from pathlib import Path


def test_source_does_not_call_hermes_skill_manage_or_patch_core():
    root = Path(__file__).resolve().parents[1] / "hermes_curator_evolver"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))

    assert "skill_manage" not in source
    assert "hermes_cli.main" not in source
    assert "run_agent.py" not in source


def test_auto_mutation_requires_explicit_low_risk_flags():
    auto_evolve = (Path(__file__).resolve().parents[1] / "hermes_curator_evolver" / "auto_evolve.py").read_text()

    assert "apply_low_risk" in auto_evolve
    assert "approve_auto_apply" in auto_evolve
    assert "auto-approval-required" in auto_evolve
    assert "append-only-managed-block" in auto_evolve
