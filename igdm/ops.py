"""Operation catalog: GraphQL operation name -> doc_id + full variables template.

Built from captured browser traffic (tools/build_catalog.py). Templates carry the exact variable shape
Instagram's web client sends, including the many `__relay_internal__pv__*` provider flags the server
expects; callers override only the fields that matter (ids, cursors, counts).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.ops: dict = json.loads(path.read_text()) if path.exists() else {}

    def __contains__(self, name):
        return name in self.ops

    def doc_id(self, name: str) -> str | None:
        return (self.ops.get(name) or {}).get("doc_id") or None

    def variables(self, name: str, overrides: dict | None = None, drop: tuple = ()) -> dict:
        """Template variables for `name`, deep-merged with `overrides`; keys in `drop` are removed first."""
        base = copy.deepcopy((self.ops.get(name) or {}).get("variables") or {})
        for k in drop:
            base.pop(k, None)
        return _merge(base, overrides or {})


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = _merge(base[k], v)
        else:
            base[k] = v
    return base
