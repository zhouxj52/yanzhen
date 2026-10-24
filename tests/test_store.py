import asyncio
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from yanzhen.engine import cleanup
from yanzhen.models import Run
from yanzhen.store import load_run, run_dir, save_run, write_json


def test_windows_atomic_write_retries_transient_file_locks(tmp_path, monkeypatch):
    original = Path.replace
    calls = []

    def temporarily_locked(self, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError("simulated Windows reader lock")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    path = tmp_path / "report.json"
    write_json(path, {"status": "completed"})
    assert json.loads(path.read_text())["status"] == "completed"
    assert len(calls) == 3


def test_concurrent_polling_does_not_lose_the_final_run_state():
    run = Run(id="b"*32, bundle_id="c"*32, digest="test", scenario="healthy", browser_requested=False)
    save_run(run)

    def poll():
        for _ in range(80):
            assert load_run(run.id).id == run.id

    def update():
        for index in range(20):
            run.events.append({"message": str(index)})
            save_run(run)
        run.status = "completed"
        save_run(run)

    with ThreadPoolExecutor(max_workers=5) as pool:
        jobs = [pool.submit(poll) for _ in range(4)] + [pool.submit(update)]
        for job in jobs:
            job.result()
    assert load_run(run.id).status == "completed"


def test_cleanup_timeout_preserves_report_instead_of_hanging():
    run = Run(id="d"*32, bundle_id="c"*32, digest="test", scenario="healthy", browser_requested=False)
    save_run(run)

    async def stalled():
        await asyncio.sleep(100)

    assert asyncio.run(cleanup(stalled(), run, "test close", timeout=.01)) is False
    assert load_run(run.id).events[-1]["phase"] == "cleanup"
