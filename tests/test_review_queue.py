import pytest
from types import SimpleNamespace
from typing import Any

from hermes_curator_evolver.candidates import (
    CANDIDATE_TYPE_MEMORY,
    CANDIDATE_TYPE_REPLAY_BENCHMARK,
    Candidate,
)
from hermes_curator_evolver.review_queue import ReviewQueue


def _candidate(t: str, *, title: str = "t", evidence_refs=None) -> Candidate:
    return Candidate(
        candidate_type=t,
        title=title,
        rationale="r",
        confidence=0.9,
        evidence_refs=list(evidence_refs or ["s:1"]),
    )


def test_review_queue_initializes_schema(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")

    assert q.db_path.exists()
    assert q.list_candidates() == []


def test_enqueue_is_idempotent_on_same_id(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    c = _candidate(CANDIDATE_TYPE_MEMORY)

    first = q.enqueue(c)
    second = q.enqueue(c)

    assert first is True
    assert second is False
    rows = q.list_candidates()
    assert len(rows) == 1
    assert rows[0]["candidate_type"] == CANDIDATE_TYPE_MEMORY
    assert rows[0]["status"] == "pending"
    assert rows[0]["id"] == c.id


def test_enqueued_row_preserves_safety_defaults(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    c = _candidate(CANDIDATE_TYPE_MEMORY)

    q.enqueue(c)

    row = q.list_candidates()[0]
    assert row["auto_apply_allowed"] is False
    assert row["requires_human_review"] is True


def test_queue_refuses_auto_apply_even_if_candidate_object_is_bypassed(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    unsafe: Any = SimpleNamespace(
        id="unsafe",
        candidate_type=CANDIDATE_TYPE_MEMORY,
        title="unsafe",
        rationale="unsafe",
        confidence=0.9,
        evidence_refs=["s:unsafe"],
        target_skill=None,
        auto_apply_allowed=True,
        requires_human_review=True,
        metadata={},
    )

    with pytest.raises(ValueError, match="auto_apply_allowed"):
        q.enqueue(unsafe)

    assert q.list_candidates() == []


def test_queue_refuses_non_human_review_candidate_if_constructor_is_bypassed(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    unsafe: Any = SimpleNamespace(
        id="unsafe-review",
        candidate_type=CANDIDATE_TYPE_MEMORY,
        title="unsafe",
        rationale="unsafe",
        confidence=0.9,
        evidence_refs=["s:unsafe"],
        target_skill=None,
        auto_apply_allowed=False,
        requires_human_review=False,
        metadata={},
    )

    with pytest.raises(ValueError, match="requires_human_review"):
        q.enqueue(unsafe)

    assert q.list_candidates() == []


def test_list_candidates_filters_by_status_and_type(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    a = _candidate(CANDIDATE_TYPE_MEMORY, title="A", evidence_refs=["s:a"])
    b = _candidate(
        CANDIDATE_TYPE_REPLAY_BENCHMARK, title="B", evidence_refs=["s:b"]
    )

    q.enqueue(a)
    q.enqueue(b)
    q.update_status(a.id, "accepted")

    accepted = q.list_candidates(status="accepted")
    assert [row["id"] for row in accepted] == [a.id]

    pending = q.list_candidates(status="pending")
    assert [row["id"] for row in pending] == [b.id]

    by_type = q.list_candidates(candidate_type=CANDIDATE_TYPE_MEMORY)
    assert [row["id"] for row in by_type] == [a.id]


def test_update_status_validates_value(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")
    c = _candidate(CANDIDATE_TYPE_MEMORY)
    q.enqueue(c)

    with pytest.raises(ValueError):
        q.update_status(c.id, "bogus")

    assert q.update_status(c.id, "rejected") is True
    rows = q.list_candidates(status="rejected")
    assert rows and rows[0]["id"] == c.id


def test_update_status_unknown_id_returns_false(tmp_path):
    q = ReviewQueue(tmp_path / "queue.sqlite")

    assert q.update_status("nope", "accepted") is False


def test_review_queue_persists_across_instances(tmp_path):
    db = tmp_path / "queue.sqlite"
    first = ReviewQueue(db)
    c = _candidate(CANDIDATE_TYPE_MEMORY)
    first.enqueue(c)

    second = ReviewQueue(db)
    rows = second.list_candidates()

    assert len(rows) == 1
    assert rows[0]["id"] == c.id
