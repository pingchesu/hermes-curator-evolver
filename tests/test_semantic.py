from pathlib import Path

from hermes_curator_evolver.semantic import find_skill_candidates, semantic_model_plan


def test_lexical_candidate_generation_ranks_matching_skill(tmp_path):
    skills = tmp_path / "skills"
    (skills / "hermes-agent").mkdir(parents=True)
    (skills / "hermes-agent" / "SKILL.md").write_text(
        "# Hermes Agent\n\nTroubleshoot gateway restart and plugin CLI wiring.",
        encoding="utf-8",
    )
    (skills / "spotify").mkdir()
    (skills / "spotify" / "SKILL.md").write_text(
        "# Spotify\n\nMusic playback controls.",
        encoding="utf-8",
    )

    result = find_skill_candidates(
        query="gateway plugin restart troubleshooting",
        skills_dir=skills,
        semantic=False,
        limit=2,
    )

    assert result["mode"] == "lexical"
    assert result["models"]["embedding"] == "not-used"
    assert result["candidates"][0]["skill_name"] == "hermes-agent"
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]


def test_semantic_mode_is_explicit_opt_in_without_download(tmp_path):
    skills = tmp_path / "skills"
    skills.mkdir()

    result = find_skill_candidates(
        query="anything",
        skills_dir=skills,
        semantic=True,
        limit=5,
    )

    assert result["mode"] == "semantic-plan"
    assert result["models"]["embedding"] == "Qwen3-Embedding-0.6B"
    assert result["models"]["reranker"] == "bge-reranker-v2-m3"
    assert result["model_downloaded"] is False
    assert result["candidates"] == []


def test_semantic_model_plan_names_candidate_generation_models():
    plan = semantic_model_plan()

    assert plan["embedding"] == "Qwen3-Embedding-0.6B"
    assert plan["reranker"] == "bge-reranker-v2-m3"
    assert "candidate" in plan["purpose"].lower()
