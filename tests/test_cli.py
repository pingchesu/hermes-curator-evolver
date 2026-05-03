from hermes_curator_evolver.__main__ import build_parser


def test_standalone_cli_parser_accepts_report_command():
    parser = build_parser()

    args = parser.parse_args(["report", "--days", "3", "--format", "json"])

    assert args.curator_evolver_command == "report"
    assert args.days == 3
    assert args.format == "json"
