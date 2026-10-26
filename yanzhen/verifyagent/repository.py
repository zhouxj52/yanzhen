"""Versioned, immutable contract snapshots and process-local atomic persistence."""
from __future__ import annotations

import json
from pathlib import Path

from .. import store
from ..store import safe_id, write_json, LOCK
from .schema import Bundle, Run, Target, now


def path(kind: str, identifier: str) -> Path:
    if kind not in {"bundles", "targets", "runs"}:
        raise ValueError("Invalid storage kind")
    return store.ARTIFACTS / "verifyagent" / kind / safe_id(identifier)


def save_target(target: Target):
    with LOCK:
        destination = path("targets", target.id) / "target.json"
        if destination.exists():
            raise ValueError("Targets are immutable; register a new target revision")
        write_json(destination, target.model_dump(mode="json"))


def load_target(identifier: str) -> Target:
    return Target.model_validate_json((path("targets", identifier) / "target.json").read_text(encoding="utf-8"))


def save_bundle(bundle: Bundle):
    with LOCK:
        destination = path("bundles", bundle.id) / "bundle.json"
        if destination.exists() and Bundle.model_validate_json(destination.read_text(encoding="utf-8")).frozen:
            raise ValueError("A frozen contract version cannot be overwritten")
        write_json(destination, bundle.model_dump(mode="json"))


def load_bundle(identifier: str) -> Bundle:
    return Bundle.model_validate_json((path("bundles", identifier) / "bundle.json").read_text(encoding="utf-8"))


def freeze(identifier: str, expected_digest: str, reviewer: str, accept_assumptions=False) -> Bundle:
    with LOCK:
        bundle = load_bundle(identifier)
        if expected_digest != bundle.calculate_digest():
            raise ValueError("Stale contract approval; review this exact version")
        if bundle.frozen:
            bundle.assert_frozen()
            return bundle
        if bundle.clarification_questions or not bundle.contracts:
            raise ValueError("Resolve clarification questions in a new revision before freezing")
        assumptions = any(c.assumptions or any(p.source.basis == "assumption" for p in c.preconditions + c.postconditions + c.invariants) for c in bundle.contracts)
        if assumptions and not accept_assumptions:
            raise ValueError("Derived assumptions require explicit approval")
        if not reviewer.strip():
            raise ValueError("An explicit reviewer is required")
        bundle.frozen, bundle.digest, bundle.reviewed_by = True, expected_digest, reviewer[:120]
        save_bundle(bundle)
        return bundle


def save_run(run: Run):
    write_json(path("runs", run.id) / "report.json", run.model_dump(mode="json"))


def load_run(identifier: str) -> Run:
    return Run.model_validate_json((path("runs", identifier) / "report.json").read_text(encoding="utf-8"))


def event(run: Run, phase: str, message: str, **data):
    run.events.append({"timestamp": now(), "phase": phase, "message": message, **data})
    save_run(run)


def list_runs(limit: int | None = 100):
    root = store.ARTIFACTS / "verifyagent" / "runs"
    rows = []
    for item in sorted(root.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
            rows.append({k: data[k] for k in ("id", "bundle_id", "target_id", "planner", "status", "created_at")})
        except (ValueError, KeyError):
            continue
    return rows[:limit] if limit is not None else rows
