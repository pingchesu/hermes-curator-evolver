from hermes_curator_evolver.semantic import find_skill_candidates, semantic_model_plan


class FakeEmbeddingBackend:
    def __init__(self):
        self.texts = []
        self.kwargs = {}

    def encode(self, texts, **kwargs):
        self.texts = list(texts)
        self.kwargs = dict(kwargs)
        vectors = []
        for text in texts:
            lowered = text.lower()
            if "gateway" in lowered or "restart" in lowered:
                vectors.append([1.0, 0.0])
            elif "music" in lowered:
                vectors.append([0.0, 1.0])
            else:
                vectors.append([0.2, 0.2])
        return vectors


class FakeRerankerBackend:
    def predict(self, pairs):
        scores = []
        for _query, text in pairs:
            scores.append(10.0 if "plugin" in text.lower() else 1.0)
        return scores


class FailingEmbeddingBackend:
    def encode(self, texts, **kwargs):
        raise RuntimeError("simulated model OOM")


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


def test_semantic_mode_executes_with_injected_embedding_backend(tmp_path):
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
        query="gateway restart",
        skills_dir=skills,
        semantic=True,
        limit=2,
        embedding_backend=FakeEmbeddingBackend(),
    )

    assert result["mode"] == "semantic"
    assert result["model_executed"] is True
    assert result["model_downloaded"] is False
    assert result["candidates"][0]["skill_name"] == "hermes-agent"
    assert result["candidates"][0]["score"] > result["candidates"][1]["score"]


def test_semantic_mode_can_rerank_with_injected_reranker_backend(tmp_path):
    skills = tmp_path / "skills"
    (skills / "plain-gateway").mkdir(parents=True)
    (skills / "plain-gateway" / "SKILL.md").write_text(
        "# Gateway\n\nTroubleshoot gateway restart.",
        encoding="utf-8",
    )
    (skills / "plugin-gateway").mkdir()
    (skills / "plugin-gateway" / "SKILL.md").write_text(
        "# Plugin Gateway\n\nTroubleshoot gateway restart and plugin CLI wiring.",
        encoding="utf-8",
    )

    result = find_skill_candidates(
        query="gateway restart plugin",
        skills_dir=skills,
        semantic=True,
        limit=2,
        embedding_backend=FakeEmbeddingBackend(),
        reranker_backend=FakeRerankerBackend(),
    )

    assert result["mode"] == "semantic-reranked"
    assert result["reranker_executed"] is True
    assert result["candidates"][0]["skill_name"] == "plugin-gateway"


def test_semantic_model_plan_names_candidate_generation_models():
    plan = semantic_model_plan()

    assert plan["embedding"] == "Qwen3-Embedding-0.6B"
    assert plan["reranker"] == "bge-reranker-v2-m3"
    assert plan["runtime_device"] == "auto"
    assert int(plan["text_limit_chars"]) >= 200
    assert "candidate" in plan["purpose"].lower()


def test_semantic_execution_truncates_text_and_uses_small_batches(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CURATOR_EVOLVER_SEMANTIC_TEXT_LIMIT", "240")
    skills = tmp_path / "skills"
    (skills / "long-skill").mkdir(parents=True)
    (skills / "long-skill" / "SKILL.md").write_text(
        "# Long\n\n" + ("gateway restart plugin " * 500),
        encoding="utf-8",
    )
    backend = FakeEmbeddingBackend()

    result = find_skill_candidates(
        query="gateway restart",
        skills_dir=skills,
        semantic=True,
        limit=1,
        embedding_backend=backend,
    )

    assert result["runtime"]["device"] == "auto"
    assert result["runtime"]["text_limit_chars"] == 240
    assert backend.kwargs["batch_size"] == 1
    assert backend.kwargs["convert_to_tensor"] is False
    assert len(backend.texts[1]) < 320
    assert "truncated" in backend.texts[1]


def test_semantic_execution_failure_returns_unavailable_instead_of_crashing(tmp_path):
    skills = tmp_path / "skills"
    (skills / "hermes-agent").mkdir(parents=True)
    (skills / "hermes-agent" / "SKILL.md").write_text("# Hermes\n\nGateway plugin.", encoding="utf-8")

    result = find_skill_candidates(
        query="gateway plugin",
        skills_dir=skills,
        semantic=True,
        limit=1,
        embedding_backend=FailingEmbeddingBackend(),
    )

    assert result["mode"] == "semantic-execution-unavailable"
    assert result["model_executed"] is False
    assert result["candidates"] == []
    assert "simulated model OOM" in result["error"]
