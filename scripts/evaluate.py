"""Fixture regression matrix, not an LLM or real-world benchmark."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from yanzhen.cli import wait
from yanzhen.models import DEFAULT_REQUIREMENTS

EXPECTED = {
    "healthy": {"pass": 5, "fail": 0, "blocked": 0, "unclear": 0},
    "broken": {"pass": 2, "fail": 3, "blocked": 0, "unclear": 0},
    "auth_bug": {"pass": 4, "fail": 1, "blocked": 0, "unclear": 0},
    "state_bug": {"pass": 4, "fail": 1, "blocked": 0, "unclear": 0},
    "persistence_bug": {"pass": 4, "fail": 1, "blocked": 0, "unclear": 0},
    "locator_drift": {"pass": 5, "fail": 0, "blocked": 0, "unclear": 0},
    "environment_down": {"pass": 0, "fail": 0, "blocked": 5, "unclear": 0},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", default="http://127.0.0.1:8765")
    parser.add_argument("--api-only", action="store_true")
    args = parser.parse_args()
    results = []
    with httpx.Client(base_url=args.origin, timeout=100, trust_env=False) as client:
        response = client.post("/api/analyze", json={"requirements": DEFAULT_REQUIREMENTS, "provider": "offline"})
        response.raise_for_status()
        bundle = response.json()
        client.post(f"/api/bundles/{bundle['id']}/freeze", json={"digest": bundle["digest"]}).raise_for_status()
        for scenario, expected in EXPECTED.items():
            response = client.post("/api/runs", json={"bundle_id": bundle["id"], "scenario": scenario, "browser": not args.api_only})
            response.raise_for_status()
            report = wait(client, response.json()["id"])
            match = report["status"] == "completed" and report["summary"] == expected
            row = {"scenario": scenario, "id": report["id"], "expected": expected, "actual": report["summary"], "matches": match}
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        original = next(row for row in results if row["scenario"] == "broken")
        response = client.post(f"/api/runs/{original['id']}/replay")
        response.raise_for_status()
        replay = wait(client, response.json()["id"])
        comparison = replay.get("replay_comparison", {})
        outcome = {"scope": "controlled_fixture_regression_only", "provider": "offline", "browser": not args.api_only, "created_at": datetime.now(timezone.utc).isoformat(), "cases": results, "replay": {"id": replay["id"], **comparison}, "all_match": all(row["matches"] for row in results) and bool(comparison.get("matches"))}
        path = Path(__file__).resolve().parent.parent / ".artifacts" / "evaluation.json"
        path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"all_match": outcome["all_match"], "report": str(path)}, ensure_ascii=False))
        raise SystemExit(0 if outcome["all_match"] else 1)


if __name__ == "__main__":
    main()
