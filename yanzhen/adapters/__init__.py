"""Explicit target registry. Never imports modules or executes paths supplied by a client."""
from __future__ import annotations

import re

from .base import TargetAdapter
from .reimbursement import ReimbursementAdapter
from .todomvc import TodoAdapter

_adapters: dict[str, TargetAdapter] = {}


def register_adapter(adapter: TargetAdapter) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,39}", adapter.key):
        raise ValueError("目标适配器名称无效")
    if adapter.key in _adapters:
        raise ValueError("目标适配器已注册：" + adapter.key)
    _adapters[adapter.key] = adapter


def get_adapter(key: str) -> TargetAdapter:
    try:
        return _adapters[key]
    except KeyError:
        raise ValueError("未知目标适配器：" + key) from None


def list_adapters() -> list[dict]:
    return [{"key": a.key, "label": a.label, "supported_kinds": sorted(a.supported_kinds)} for a in _adapters.values()]


register_adapter(ReimbursementAdapter())
register_adapter(TodoAdapter())
