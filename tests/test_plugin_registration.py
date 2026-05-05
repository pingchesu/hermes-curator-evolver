import importlib.util
import shutil
import sys
from pathlib import Path

import hermes_curator_evolver


class FakeCtx:
    def __init__(self):
        self.tools = []
        self.hooks = []
        self.cli_commands = []
        self.commands = []
        self.skills = []

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools.append((name, toolset, schema, handler, kwargs))

    def register_hook(self, name, callback):
        self.hooks.append((name, callback))

    def register_cli_command(self, name, help, setup_fn, handler_fn=None, description=""):
        self.cli_commands.append((name, help, setup_fn, handler_fn, description))

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands.append((name, handler, description, args_hint))

    def register_skill(self, name, path):
        self.skills.append((name, Path(path)))


def test_register_wires_tool_hooks_cli_slash_and_skill():
    ctx = FakeCtx()

    hermes_curator_evolver.register(ctx)

    assert [t[0] for t in ctx.tools] == ["curator_evidence_report"]
    assert {h[0] for h in ctx.hooks} == {"post_tool_call", "post_llm_call", "on_session_end"}
    assert [c[0] for c in ctx.cli_commands] == ["curator-evolver"]
    assert [c[0] for c in ctx.commands] == ["curator-evolver"]
    assert ctx.skills[0][0] == "curator-evolution"
    assert ctx.skills[0][1].name == "SKILL.md"


def test_tool_handler_returns_json_string(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_CURATOR_EVOLVER_DB", str(tmp_path / "evidence.sqlite"))
    ctx = FakeCtx()
    hermes_curator_evolver.register(ctx)
    handler = ctx.tools[0][3]

    result = handler({"days": 1, "format": "json"})

    assert isinstance(result, str)
    assert "summary" in result


def test_directory_plugin_shim_uses_relative_package_import(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    plugin_dir = tmp_path / "curator-evolver"
    shutil.copytree(repo_root / "hermes_curator_evolver", plugin_dir / "hermes_curator_evolver")
    shutil.copy2(repo_root / "__init__.py", plugin_dir / "__init__.py")

    removed_paths = []
    for entry in list(sys.path):
        try:
            if Path(entry or ".").resolve() == repo_root:
                removed_paths.append(entry)
                sys.path.remove(entry)
        except OSError:
            pass
    monkeypatch.setattr(sys, "path", sys.path)
    sys.modules.pop("hermes_curator_evolver", None)
    try:
        spec = importlib.util.spec_from_file_location(
            "hermes_plugins.curator_evolver",
            plugin_dir / "__init__.py",
            submodule_search_locations=[str(plugin_dir)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        module.__package__ = "hermes_plugins.curator_evolver"
        module.__path__ = [str(plugin_dir)]
        sys.modules["hermes_plugins.curator_evolver"] = module
        spec.loader.exec_module(module)
    finally:
        for entry in reversed(removed_paths):
            sys.path.insert(0, entry)

    assert callable(module.register)
