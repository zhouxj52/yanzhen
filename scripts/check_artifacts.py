"""Inspect actual trace archives and the executed locator-repair audit."""
import json
import re
import zipfile

from yanzhen.settings import ARTIFACTS
from yanzhen.exports import verify_evidence


def main():
    evaluation = json.loads((ARTIFACTS / "evaluation.json").read_text(encoding="utf-8"))
    drift = next(row for row in evaluation["cases"] if row["scenario"] == "locator_drift")
    report = json.loads((ARTIFACTS / "runs" / drift["id"] / "report.json").read_text(encoding="utf-8"))
    repairs = [e for result in report["results"] for e in result["evidence"] if e["kind"] == "repair"]
    assert repairs and repairs[0]["data"]["unchanged_contract"]
    token_pattern = re.compile(rb'Bearer [A-Za-z0-9_-]{15,}|"token"\s*:\s*"[A-Za-z0-9_-]{15,}')
    traces = list((ARTIFACTS / "runs").glob("*/trace-*.zip"))
    assert traces
    for path in traces:
        with zipfile.ZipFile(path) as archive:
            assert all(not token_pattern.search(archive.read(name)) for name in archive.namelist()), str(path)
    packages = list((ARTIFACTS / "runs").glob("*/evidence.zip"))
    manifests_checked = 0
    for path in packages:
        with zipfile.ZipFile(path) as archive:
            assert "demo.sqlite" not in archive.namelist()
            assert {"contract.json", "report.json", "replay.py"}.issubset(archive.namelist())
            if "manifest.json" in archive.namelist():
                assert verify_evidence(path)["valid"], str(path)
                manifests_checked += 1
    assert manifests_checked, "No new-format evidence package was verified"
    outcome = {"status": "passed", "trace_archives_checked": len(traces), "evidence_packages_checked": len(packages), "manifests_checked": manifests_checked, "unredacted_tokens_found": 0, "locator_repair_preserved_contract": True}
    (ARTIFACTS / "artifact-check.json").write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(outcome, ensure_ascii=False))


if __name__ == "__main__":
    main()
