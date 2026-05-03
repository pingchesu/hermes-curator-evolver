import json

from hermes_curator_evolver.__main__ import build_parser
from hermes_curator_evolver.cli import handle_cli


def test_standalone_cli_parser_accepts_report_command():
    parser = build_parser()

    args = parser.parse_args(["report", "--days", "3", "--format", "json"])

    assert args.curator_evolver_command == "report"
    assert args.days == 3
    assert args.format == "json"


def test_standalone_cli_parser_accepts_roadmap_commands():
    parser = build_parser()

    propose = parser.parse_args([
        "propose",
        "--skill",
        "hermes-agent",
        "--skill-file",
        "SKILL.md",
        "--output",
        "proposal.md",
        "--draft-with-model",
        "--model-timeout",
        "12",
    ])
    verify = parser.parse_args(["verify", "--proposal-file", "proposal.json"])
    candidates = parser.parse_args([
        "candidates",
        "--query",
        "gateway restart",
        "--skills-dir",
        "skills",
        "--semantic",
        "--execute-semantic",
        "--rerank",
    ])
    apply = parser.parse_args([
        "apply",
        "--target",
        "SKILL.md",
        "--content-file",
        "proposal.md",
        "--expected-sha256",
        "abc",
        "--approve",
    ])
    rollback = parser.parse_args(["rollback", "--manifest", "manifest.json"])
    auto_run = parser.parse_args([
        "auto-run",
        "--skills-dir",
        "skills",
        "--semantic-candidates",
        "--rerank-candidates",
        "--apply-low-risk",
        "--approve-auto-apply",
        "--allow-auto-apply-skill",
        "hermes-agent",
        "--block-auto-apply-skill",
        "github-*",
        "--format",
        "json",
    ])
    install_auto = parser.parse_args([
        "install-auto",
        "--schedule",
        "daily",
        "--semantic-candidates",
        "--rerank-candidates",
        "--block-auto-apply-skill",
        "github-*",
    ])
    rerank_only_auto = parser.parse_args(["auto-run", "--skills-dir", "skills", "--rerank-candidates"])
    bootstrap = parser.parse_args([
        "bootstrap",
        "--days",
        "14",
        "--sessions-dir",
        "sessions",
        "--skills-dir",
        "skills",
        "--schedule",
        "hourly",
        "--semantic",
        "--format",
        "json",
    ])
    backfill = parser.parse_args([
        "backfill-sessions",
        "--sessions-dir",
        "sessions",
        "--days",
        "30",
        "--limit",
        "10",
        "--format",
        "json",
    ])
    uninstall_auto = parser.parse_args(["uninstall-auto"])

    assert propose.curator_evolver_command == "propose"
    assert propose.draft_with_model is True
    assert propose.model_timeout == 12
    assert verify.curator_evolver_command == "verify"
    assert candidates.curator_evolver_command == "candidates"
    assert candidates.semantic is True
    assert candidates.execute_semantic is True
    assert candidates.rerank is True
    assert apply.curator_evolver_command == "apply"
    assert apply.approve is True
    assert rollback.curator_evolver_command == "rollback"
    assert auto_run.curator_evolver_command == "auto-run"
    assert auto_run.semantic_candidates is True
    assert auto_run.rerank_candidates is True
    assert auto_run.apply_low_risk is True
    assert auto_run.approve_auto_apply is True
    assert auto_run.protect_core_skills is True
    assert auto_run.allow_auto_apply_skill == ["hermes-agent"]
    assert auto_run.block_auto_apply_skill == ["github-*"]
    assert install_auto.curator_evolver_command == "install-auto"
    assert install_auto.schedule == "daily"
    assert install_auto.semantic_candidates is True
    assert install_auto.rerank_candidates is True
    assert install_auto.protect_core_skills is True
    assert install_auto.block_auto_apply_skill == ["github-*"]
    assert rerank_only_auto.rerank_candidates is True
    assert bootstrap.curator_evolver_command == "bootstrap"
    assert bootstrap.days == 14
    assert bootstrap.sessions_dir == "sessions"
    assert bootstrap.skills_dir == "skills"
    assert bootstrap.schedule == "hourly"
    assert bootstrap.semantic is True
    assert bootstrap.enable is True
    assert bootstrap.format == "json"
    assert backfill.curator_evolver_command == "backfill-sessions"
    assert backfill.sessions_dir == "sessions"
    assert backfill.days == 30
    assert backfill.limit == 10
    assert backfill.format == "json"
    assert uninstall_auto.curator_evolver_command == "uninstall-auto"


def test_bootstrap_command_runs_backfill_and_installs_auto_timer(monkeypatch, capsys):
    parser = build_parser()
    calls = {}

    def fake_backfill_sessions(*, sessions_dir, days, limit=None):
        calls["backfill"] = {"sessions_dir": sessions_dir, "days": days, "limit": limit}
        return {
            "sessions_dir": sessions_dir,
            "sessions_seen": 5,
            "sessions_imported": 4,
            "tool_events_imported": 12,
            "turn_events_imported": 3,
            "session_events_imported": 4,
            "files_failed": 0,
        }

    def fake_install_auto_timer(**kwargs):
        calls["install_auto"] = kwargs
        return {
            "installed": True,
            "enabled": kwargs["enable"],
            "schedule": kwargs["schedule"],
            "command": "python -m hermes_curator_evolver auto-run ...",
            "auto_apply_policy": "local-agent-created-skills-only",
        }

    monkeypatch.setattr("hermes_curator_evolver.cli.backfill_sessions", fake_backfill_sessions)
    monkeypatch.setattr("hermes_curator_evolver.cli.install_auto_timer", fake_install_auto_timer)

    args = parser.parse_args([
        "bootstrap",
        "--days",
        "14",
        "--sessions-dir",
        "sessions",
        "--skills-dir",
        "skills",
        "--schedule",
        "hourly",
        "--semantic",
        "--format",
        "json",
    ])

    handle_cli(args)

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "bootstrap"
    assert payload["backfill"]["sessions_imported"] == 4
    assert payload["auto_timer"]["auto_apply_policy"] == "local-agent-created-skills-only"
    assert payload["next_steps"][0].startswith("Restart Hermes gateway")
    assert calls["backfill"] == {"sessions_dir": "sessions", "days": 14, "limit": None}
    assert calls["install_auto"]["schedule"] == "hourly"
    assert calls["install_auto"]["skills_dir"] == "skills"
    assert calls["install_auto"]["enable"] is True
    assert calls["install_auto"]["semantic_candidates"] is True
    assert calls["install_auto"]["rerank_candidates"] is True
