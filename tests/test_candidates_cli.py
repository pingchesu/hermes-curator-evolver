import json

import pytest

from hermes_curator_evolver.__main__ import build_parser
from hermes_curator_evolver.cli import handle_cli
from hermes_curator_evolver.review_queue import ReviewQueue


def _write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records),
        encoding="utf-8",
    )


def test_candidates_mine_subcommand_persists_to_queue_and_emits_json(tmp_path, capsys):
    jsonl = tmp_path / "in.jsonl"
    db = tmp_path / "queue.sqlite"
    _write_jsonl(
        jsonl,
        [
            {
                "text": "curator-evolver may auto-apply only agent-created non-core skills",
                "evidence_ref": "s:1",
            },
            {"text": "merged PR #99 abc1234", "evidence_ref": "s:2"},
            {
                "text": "Traceback: command failed",
                "evidence_ref": "s:3",
                "tool_name": "terminal",
                "is_error": True,
            },
        ],
    )

    parser = build_parser()
    args = parser.parse_args(
        [
            "candidates-mine",
            "--input-jsonl",
            str(jsonl),
            "--queue-db",
            str(db),
            "--format",
            "json",
        ]
    )
    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 3
    types = {c["candidate_type"] for c in payload["candidates"]}
    assert {"memory", "ignore", "replay_benchmark"} <= types

    queue = ReviewQueue(db)
    rows = queue.list_candidates()
    assert len(rows) == 3
    assert all(row["status"] == "pending" for row in rows)
    assert all(row["auto_apply_allowed"] is False for row in rows)


def test_candidates_mine_is_idempotent_on_repeated_run(tmp_path, capsys):
    jsonl = tmp_path / "in.jsonl"
    db = tmp_path / "queue.sqlite"
    _write_jsonl(
        jsonl,
        [
            {"text": "merged PR #99 abc1234", "evidence_ref": "s:dup"},
        ],
    )

    parser = build_parser()
    for _ in range(2):
        args = parser.parse_args(
            [
                "candidates-mine",
                "--input-jsonl",
                str(jsonl),
                "--queue-db",
                str(db),
                "--format",
                "json",
            ]
        )
        handle_cli(args)
        capsys.readouterr()

    queue = ReviewQueue(db)
    assert len(queue.list_candidates()) == 1


def test_candidates_list_subcommand_returns_pending_in_json(tmp_path, capsys):
    db = tmp_path / "queue.sqlite"
    jsonl = tmp_path / "in.jsonl"
    _write_jsonl(
        jsonl,
        [{"text": "merged PR #99 abc1234", "evidence_ref": "s:1"}],
    )

    parser = build_parser()
    mine_args = parser.parse_args(
        [
            "candidates-mine",
            "--input-jsonl",
            str(jsonl),
            "--queue-db",
            str(db),
            "--format",
            "json",
        ]
    )
    handle_cli(mine_args)
    capsys.readouterr()

    list_args = parser.parse_args(
        [
            "candidates-list",
            "--queue-db",
            str(db),
            "--format",
            "json",
        ]
    )
    handle_cli(list_args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["candidates"][0]["candidate_type"] == "ignore"
    assert payload["candidates"][0]["status"] == "pending"


def test_candidates_list_does_not_create_missing_queue_db(tmp_path):
    db = tmp_path / "missing" / "queue.sqlite"
    parser = build_parser()
    args = parser.parse_args(
        [
            "candidates-list",
            "--queue-db",
            str(db),
            "--format",
            "json",
        ]
    )

    with pytest.raises(FileNotFoundError):
        handle_cli(args)

    assert not db.exists()
    assert not db.parent.exists()


def test_candidates_list_markdown_includes_safety_disclaimer(tmp_path, capsys):
    db = tmp_path / "queue.sqlite"
    jsonl = tmp_path / "in.jsonl"
    _write_jsonl(
        jsonl,
        [
            {
                "text": "curator-evolver may auto-apply only agent-created non-core skills",
                "evidence_ref": "s:safe",
            }
        ],
    )

    parser = build_parser()
    handle_cli(
        parser.parse_args(
            [
                "candidates-mine",
                "--input-jsonl",
                str(jsonl),
                "--queue-db",
                str(db),
                "--format",
                "markdown",
            ]
        )
    )
    capsys.readouterr()

    handle_cli(
        parser.parse_args(
            [
                "candidates-list",
                "--queue-db",
                str(db),
                "--format",
                "markdown",
            ]
        )
    )
    out = capsys.readouterr().out
    assert "memory" in out
    assert "human review" in out.lower()
