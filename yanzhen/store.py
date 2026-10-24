from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from .models import Bundle, Run
from .settings import ARTIFACTS

LOCK = threading.RLock()


def safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("无效编号")
    return value


def write_json(path: Path, data: dict) -> None:
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows readers and antivirus scanners may briefly deny replacement.
        for attempt in range(8):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(.01 * (attempt + 1))


def bundle_path(identifier: str) -> Path:
    return ARTIFACTS / "bundles" / f"{safe_id(identifier)}.json"


def run_dir(identifier: str) -> Path:
    return ARTIFACTS / "runs" / safe_id(identifier)


def save_bundle(bundle: Bundle) -> None:
    write_json(bundle_path(bundle.id), bundle.model_dump(mode="json"))


def load_bundle(identifier: str) -> Bundle:
    with LOCK:
        return Bundle.model_validate_json(bundle_path(identifier).read_text(encoding="utf-8"))


def freeze_bundle(identifier: str, expected_digest: str) -> Bundle:
    with LOCK:
        bundle = load_bundle(identifier)
        digest = bundle.calculate_digest()
        if expected_digest != digest:
            raise ValueError("需求或契约已经变化，请重新审阅")
        if bundle.frozen:
            bundle.assert_frozen()
            return bundle
        bundle.digest = digest
        bundle.frozen = True
        save_bundle(bundle)
        return bundle


def save_run(run: Run) -> None:
    data = run.model_dump(mode="json")
    data["summary"] = run.summary()
    write_json(run_dir(run.id) / "report.json", data)


def load_run(identifier: str) -> Run:
    with LOCK:
        data = json.loads((run_dir(identifier) / "report.json").read_text(encoding="utf-8"))
    data.pop("summary", None)
    return Run.model_validate(data)


def report_bytes(identifier: str) -> bytes:
    """Read a short-lived snapshot; normalize platform newlines to ZIP's UTF-8 format."""
    with LOCK:
        return (run_dir(identifier) / "report.json").read_text(encoding="utf-8").encode("utf-8")


def list_runs(limit: int | None = 50, include_internal: bool = False) -> list[dict]:
    if limit is not None and limit <= 0:
        return []
    paths = sorted((ARTIFACTS / "runs").glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    output = []
    for path in paths:
        try:
            with LOCK:
                data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("internal_trial") and not include_internal:
                continue
            output.append({**{k: data[k] for k in ("id", "bundle_id", "scenario", "status", "created_at", "summary", "parent_run")}, "target":data.get("target","reimbursement")})
            if limit is not None and len(output) >= limit:
                break
        except (ValueError, KeyError):
            continue
    return output
