from hermes_curator_evolver.__main__ import build_parser


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
        "--format",
        "json",
    ])
    install_auto = parser.parse_args([
        "install-auto",
        "--schedule",
        "daily",
        "--semantic-candidates",
        "--rerank-candidates",
    ])
    rerank_only_auto = parser.parse_args(["auto-run", "--skills-dir", "skills", "--rerank-candidates"])
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
    assert install_auto.curator_evolver_command == "install-auto"
    assert install_auto.schedule == "daily"
    assert install_auto.semantic_candidates is True
    assert install_auto.rerank_candidates is True
    assert rerank_only_auto.rerank_candidates is True
    assert uninstall_auto.curator_evolver_command == "uninstall-auto"
