# Curator Evolver installed

The Hermes plugin has been cloned and enabled. Restart Hermes so the plugin hooks/tools are loaded:

```bash
hermes gateway restart
```

## Optional standalone CLI

Hermes directory-plugin install currently clones the repo into `~/.hermes/plugins/curator-evolver` but does not install Python console scripts automatically.

To use `hermes-curator-evolver ...`, install an editable CLI entrypoint into the Hermes venv:

```bash
uv pip install --python ~/.hermes/hermes-agent/venv/bin/python -e ~/.hermes/plugins/curator-evolver
hermes-curator-evolver status
```

Without installing the entrypoint, you can still smoke-test the package directly from the plugin clone:

```bash
PYTHONPATH=~/.hermes/plugins/curator-evolver \
  ~/.hermes/hermes-agent/venv/bin/python -m hermes_curator_evolver status
```
