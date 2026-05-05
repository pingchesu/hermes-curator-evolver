"""Directory-plugin shim for Hermes Curator Evolver.

Hermes directory plugins load `__init__.py` from the plugin root. The real
package lives in `hermes_curator_evolver` so the same code also works when
installed through the `hermes_agent.plugins` entry point.
"""

try:
    from .hermes_curator_evolver import register
except ImportError:  # Support pytest/top-level imports and older loaders.
    import sys
    from pathlib import Path

    plugin_dir = Path(__file__).resolve().parent
    if str(plugin_dir) not in sys.path:
        sys.path.insert(0, str(plugin_dir))
    from hermes_curator_evolver import register

__all__ = ["register"]
