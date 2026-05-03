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
