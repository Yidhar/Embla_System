"""API server package exports.

Keep `app` lazily resolved to avoid import cycles while modules import
`apiserver.*` utilities.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app"]


def __getattr__(name: str) -> Any:
    if name == "app":
        from .api_server import app

        return app
    raise AttributeError(name)
