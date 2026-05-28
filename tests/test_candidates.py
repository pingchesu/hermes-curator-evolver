import pytest

from hermes_curator_evolver.candidates import (
    CANDIDATE_TYPE_IGNORE,
    CANDIDATE_TYPE_MEMORY,
    CANDIDATE_TYPE_REPLAY_BENCHMARK,
    CANDIDATE_TYPE_SKILL_NEW,
    CANDIDATE_TYPE_SKILL_UPDATE,
    CANDIDATE_TYPES,
    Candidate,
    candidate_id,
    classify_record,
    mine_candidates,
)


def test_candidate_type_constants_match_required_strings():
    assert CANDIDATE_TYPES == {
        "memory",
        "skill_update",
        "skill_new",
        "replay_benchmark",
        "ignore",
    }


def test_candidate_dataclass_defaults_are_safe():
    c = Candidate(
        candidate_type=CANDIDATE_TYPE_MEMORY,
        title="user safety preference",
        rationale="evidence shows preference",
        confidence=0.9,
        evidence_refs=["session:abc"],
    )

    assert c.auto_apply_allowed is False
    assert c.requires_human_review is True
    assert c.metadata == {}
    assert c.target_skill is None
    assert isinstance(c.id, str) and len(c.id) >= 16


def test_candidate_dataclass_refuses_non_human_review_candidates():
    with pytest.raises(ValueError, match="requires_human_review"):
        Candidate(
            candidate_type=CANDIDATE_TYPE_MEMORY,
            title="unsafe",
            rationale="unsafe",
            confidence=0.9,
            evidence_refs=["session:abc"],
            requires_human_review=False,
        )


def test_candidate_id_is_deterministic_and_evidence_order_independent():
    a = candidate_id(CANDIDATE_TYPE_MEMORY, "title", ["a", "b"])
    b = candidate_id(CANDIDATE_TYPE_MEMORY, "title", ["b", "a"])
    c = candidate_id(CANDIDATE_TYPE_MEMORY, "different", ["a", "b"])
    d = candidate_id(CANDIDATE_TYPE_SKILL_NEW, "title", ["a", "b"])

    assert a == b
    assert a != c
    assert a != d


def test_user_preference_safety_text_becomes_memory_candidate():
    text = (
        "curator-evolver may auto-apply only agent-created non-core skills "
        "and must not modify core/official/external skills"
    )

    candidate = classify_record({"text": text, "evidence_ref": "session:abc"})

    assert candidate is not None
    assert candidate.candidate_type == CANDIDATE_TYPE_MEMORY
    assert candidate.confidence >= 0.8
    assert candidate.auto_apply_allowed is False
    assert candidate.requires_human_review is True
    assert "session:abc" in candidate.evidence_refs


def test_chinese_memory_policy_text_becomes_memory_not_ignored():
    text = (
        "durable memory 只存精簡宣告事實；流程/步驟/SOP 進 skill；"
        "不存 task progress / PR / SHA / 短期狀態"
    )

    candidate = classify_record({"text": text, "evidence_ref": "session:memory-policy"})

    assert candidate.candidate_type == CANDIDATE_TYPE_MEMORY
    assert candidate.confidence >= 0.8
    assert candidate.auto_apply_allowed is False
    assert candidate.requires_human_review is True


def test_workflow_text_with_target_skill_becomes_skill_update():
    text = (
        "Workflow to bootstrap curator-evolver: 1. First run "
        "`hermes-curator-evolver backfill-sessions`. "
        "2. Then run `hermes-curator-evolver install-auto --schedule daily`. "
        "3. Finally invoke `hermes-curator-evolver auto-run --apply-low-risk`."
    )

    candidate = classify_record(
        {
            "text": text,
            "evidence_ref": "session:xyz",
            "target_skill": "curator-evolution",
        }
    )

    assert candidate.candidate_type == CANDIDATE_TYPE_SKILL_UPDATE
    assert candidate.target_skill == "curator-evolution"
    assert candidate.auto_apply_allowed is False
    assert candidate.requires_human_review is True


def test_workflow_text_without_target_skill_becomes_skill_new():
    text = (
        "Setup workflow: 1. start the gateway. 2. run `cli ingest`. "
        "3. then verify the output. 4. finally restart."
    )

    candidate = classify_record({"text": text, "evidence_ref": "session:xyz"})

    assert candidate.candidate_type == CANDIDATE_TYPE_SKILL_NEW
    assert candidate.target_skill is None
    assert candidate.auto_apply_allowed is False


def test_chinese_workflow_text_becomes_skill_candidate():
    text = (
        "候選歸納流程：先查 evidence，再產生 redacted trajectory，"
        "最後寫入 review queue；流程/步驟/SOP 進 skill。"
    )

    candidate = classify_record({"text": text, "evidence_ref": "session:zh-workflow"})

    assert candidate.candidate_type == CANDIDATE_TYPE_SKILL_NEW
    assert candidate.confidence >= 0.6


def test_tool_error_event_becomes_replay_benchmark():
    record = {
        "text": "read_file not_found /tmp/missing.md",
        "evidence_ref": "session:err",
        "tool_name": "read_file",
        "is_error": True,
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_REPLAY_BENCHMARK
    assert candidate.requires_human_review is True
    assert candidate.auto_apply_allowed is False


def test_skill_manage_size_cap_failure_becomes_replay_benchmark():
    record = {
        "text": "skill" + "_" + "manage size cap exceeded: SKILL.md too large",
        "evidence_ref": "session:size",
        "tool_name": "skill" + "_" + "manage",
        "is_error": True,
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_REPLAY_BENCHMARK


def test_terminal_nonzero_exit_text_becomes_replay_benchmark():
    record = {
        "text": "Traceback: command failed with exit code 2",
        "evidence_ref": "session:term",
        "tool_name": "terminal",
        "is_error": True,
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_REPLAY_BENCHMARK


def test_ephemeral_pr_progress_text_is_ignored():
    record = {
        "text": "merged PR #1234 at abc1234def into main",
        "evidence_ref": "session:eph",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_IGNORE
    assert candidate.auto_apply_allowed is False
    assert candidate.requires_human_review is True


def test_short_issue_number_only_is_ignored():
    record = {"text": "#42", "evidence_ref": "session:short"}

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_IGNORE


def test_short_sha_only_is_ignored():
    record = {"text": "abc1234def", "evidence_ref": "session:sha"}

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_IGNORE


def test_near_cap_skill_md_becomes_human_review_with_direct_append_disallowed():
    record = {
        "text": "SKILL.md size is approximately 99500 bytes, near 100k cap",
        "evidence_ref": "session:cap",
        "target_skill": "curator-evolution",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type in {
        CANDIDATE_TYPE_SKILL_UPDATE,
        CANDIDATE_TYPE_REPLAY_BENCHMARK,
    }
    assert candidate.requires_human_review is True
    assert candidate.auto_apply_allowed is False
    assert candidate.metadata.get("direct_append_allowed") is False


def test_over_cap_skill_md_size_field_triggers_human_review_metadata():
    record = {
        "text": "skill is large",
        "evidence_ref": "session:cap2",
        "target_skill": "curator-evolution",
        "skill_md_size": 101000,
    }

    candidate = classify_record(record)

    assert candidate.candidate_type in {
        CANDIDATE_TYPE_SKILL_UPDATE,
        CANDIDATE_TYPE_REPLAY_BENCHMARK,
    }
    assert candidate.requires_human_review is True
    assert candidate.auto_apply_allowed is False
    assert candidate.metadata.get("direct_append_allowed") is False


def test_low_confidence_unknown_text_defaults_to_ignore():
    record = {"text": "qwerty lorem ipsum", "evidence_ref": "session:unknown"}

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_IGNORE
    assert candidate.auto_apply_allowed is False
    assert candidate.requires_human_review is True


def test_json_wrapped_summary_is_unwrapped_before_classification():
    record = {
        "text": '{"results":[{"summary":"durable memory 只存精簡宣告事實；不存 task progress / PR / SHA / 短期狀態"}]}',
        "evidence_ref": "session:wrapped",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_MEMORY
    assert not candidate.rationale.startswith("{")
    assert "durable memory" in candidate.rationale


def test_json_wrapped_workflow_rationale_is_reviewer_readable():
    record = {
        "text": '{"results":[{"summary":"Workflow: 1. First run `ingest`. 2. Then run `mine`. 3. Finally review."}]}',
        "evidence_ref": "session:wrapped-workflow",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_SKILL_NEW
    assert not candidate.rationale.startswith("{")
    assert "Workflow:" in candidate.rationale


def test_line_numbered_source_dump_is_ignored_not_workflow():
    record = {
        "text": '{"content":" 1|Workflow to bootstrap: 1. First run `cmd`.\\n 2|Then run `other`.\\n 3|Finally verify."}',
        "evidence_ref": "session:source-dump",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_IGNORE


def test_json_exit_code_failure_becomes_replay_without_is_error_flag():
    record = {
        "text": '{"exit_code":1,"output":"command returned stderr but no explicit failed word"}',
        "evidence_ref": "session:json-error",
        "tool_name": "terminal",
    }

    candidate = classify_record(record)

    assert candidate.candidate_type == CANDIDATE_TYPE_REPLAY_BENCHMARK


def test_classify_never_returns_auto_apply_allowed_true():
    records = [
        {"text": "curator-evolver may auto-apply only agent-created non-core skills"},
        {"text": "Workflow: 1. step one 2. step two", "target_skill": "x"},
        {"text": "Traceback: failed", "is_error": True},
        {"text": "merged PR #1"},
        {"text": "qwerty"},
    ]

    for r in records:
        c = classify_record(r)
        assert c.auto_apply_allowed is False


def test_mine_candidates_classifies_each_record():
    records = [
        {"text": "merged PR #1", "evidence_ref": "s:1"},
        {"text": "Traceback: oops", "evidence_ref": "s:2", "is_error": True},
        {
            "text": "curator-evolver may auto-apply only agent-created non-core skills",
            "evidence_ref": "s:3",
        },
    ]

    results = mine_candidates(records)

    assert len(results) == 3
    types = {c.candidate_type for c in results}
    assert {CANDIDATE_TYPE_IGNORE, CANDIDATE_TYPE_REPLAY_BENCHMARK, CANDIDATE_TYPE_MEMORY} <= types
