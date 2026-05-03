"""Standalone CLI for Hermes Curator Evolver.

This is intentionally provided in addition to plugin registration because the
current Hermes CLI lists/enables general plugins but only wires memory-provider
plugin subcommands into the top-level parser. The plugin still registers
`curator-evolver` through `ctx.register_cli_command()` for forward compatibility.
"""

from __future__ import annotations

import argparse

from .cli import handle_cli, setup_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-curator-evolver",
        description="Evidence-driven reports, one-command bootstrap, historical session backfill, proposals, and optional semantic/rerank automatic skill evolution for Hermes.",
    )
    setup_cli(parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handle_cli(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
