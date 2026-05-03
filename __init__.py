"""Directory-plugin shim for Hermes Curator Evolver.

Hermes directory plugins load `__init__.py` from the plugin root. The real
package lives in `hermes_curator_evolver` so the same code also works when
installed through the `hermes_agent.plugins` entry point.
"""

from hermes_curator_evolver import register

__all__ = ["register"]
