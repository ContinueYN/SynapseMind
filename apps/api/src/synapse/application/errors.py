"""Use-case errors shared by the session entry points.

They live here rather than in ``factory`` so the resolver and the factory can
both raise them without importing each other; ``factory`` re-exports them for
the HTTP layer's existing import path.
"""

from __future__ import annotations


class ProblemNotSupported(ValueError):
    """The submitted stem cannot be served (unknown, or generation failed)."""


class UnsupportedMode(ValueError):
    """Only learning mode is available in the walking skeleton."""
