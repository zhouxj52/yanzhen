from __future__ import annotations

import io
import json
import hashlib
import zipfile

from .models import Run
from .store import run_dir


def sanitize_trace(path, tokens: set[str]) -> None:
    """Trace resources include login responses and request headers; redact both."""
    original = path.read_bytes()
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            content = source.read(name)
            for token in tokens:
                content = content.replace(token.encode(), b"[REDACTED]")
            target.writestr(name, content)
    path.write_bytes(output.getvalue())


def make_export(run: Run, origin: str) -> None:
    directory = run_dir(run.id)
    replay = '''"""Replay the frozen contracts against a newly seeded, isolated fixture. Requires httpx."""
import json, sys, time
import httpx
ORIGIN = __ORIGIN__
SOURCE_RUN = __RUN_ID__
def main():
    with httpx.Client(base_url=ORIGIN, timeout=30, trust_env=False) as client:
        response = client.post('/api/runs/' + SOURCE_RUN + '/replay')
        response.raise_for_status()
        identifier = response.json()['id']
        for _ in range(180):
            response = client.get('/api/runs/' + identifier)
            response.raise_for_status()
            run = response.json()
            if run['status'] in ('completed', 'error', 'cancelled'):
                print(json.dumps(run, ensure_ascii=False, indent=2))
                return 0 if run.get('replay_comparison', {}).get('matches') else 1
            time.sleep(1)
        raise TimeoutError('Replay did not complete within 180 seconds')
if __name__ == '__main__':
    sys.exit(main())
'''.replace("__ORIGIN__", repr(origin)).replace("__RUN_ID__", repr(run.id))
    (directory / "replay.py").write_text(replay, encoding="utf-8")
    if run.reproductions:
        (directory / "reproduction.json").write_text(json.dumps(run.reproductions,ensure_ascii=False,indent=2),encoding="utf-8")
        script = """# Execute a verified reduced recipe through the local Yanzhen service.
import json, sys
import httpx
ORIGIN = __ORIGIN__
RUN_ID = __RUN_ID__
CONTRACTS = __CONTRACTS__
if __name__ == '__main__':
    contract_id = sys.argv[1] if len(sys.argv) > 1 else CONTRACTS[0] if CONTRACTS else ''
    if contract_id not in CONTRACTS:
        raise SystemExit('Choose a verified contract: ' + ', '.join(CONTRACTS))
    response = httpx.post(ORIGIN + '/api/runs/' + RUN_ID + '/reproduce/' + contract_id, timeout=60, trust_env=False)
    response.raise_for_status()
    result = response.json()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result['matches'] else 1)
""".replace("__ORIGIN__",repr(origin)).replace("__RUN_ID__",repr(run.id)).replace("__CONTRACTS__",repr([r["contract_id"] for r in run.reproductions if r["status"]=="verified"]))
        (directory / "reproduce.py").write_text(script,encoding="utf-8")
    instructions = "# 验真证据包\n\n包含冻结契约、真实执行报告、截图和浏览器 trace（如本次已生成）。不包含数据库或登录 token。\n\n运行 replay.py 会通过本地验真服务创建新的隔离环境重跑整组契约。reproduce.py <契约编号> 仅执行经过验证的精简步骤。二者均需原记录仍保留、本地服务运行并安装 httpx，不是完整环境镜像。reproduction.json 包含每次删减和独立确认的实际观察。脚本不会调用模型。\n\n支持内置报销与固定版本 TodoMVC；受控缺陷与上游版本观察分开报告，不代表真实项目检出率。\n"
    (directory / "README.md").write_text(instructions, encoding="utf-8")
    payloads = {}
    for path in directory.iterdir():
        safe_trace = path.name.startswith("trace-") and path.suffix == ".zip" and path.with_suffix(".safe").exists()
        if path.name in {"contract.json", "replay.py", "reproduce.py", "reproduction.json", "README.md"} or path.suffix == ".png" or safe_trace:
            payloads[path.name] = path.read_bytes()
    final_report = run.model_dump(mode="json")
    final_report["summary"] = run.summary()
    payloads["report.json"] = json.dumps(final_report, ensure_ascii=False, indent=2).encode()
    manifest = {"format_version": 1, "run_id": run.id, "contract_digest": run.digest,
                "target": run.target, "scenario": run.scenario,
                "files": {name: {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                          for name, content in sorted(payloads.items())}}
    payloads["manifest.json"] = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
    with zipfile.ZipFile(directory / "evidence.zip.tmp", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in payloads.items():
            archive.writestr(name, content)
    (directory / "evidence.zip.tmp").replace(directory / "evidence.zip")
    (directory / "manifest.json").write_bytes(payloads["manifest.json"])


def verify_evidence(path) -> dict:
    """Check completeness and content hashes. This is integrity, not a digital signature."""
    errors = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                errors.append("证据包包含重复文件名")
            if any("/" in name or "\\" in name or name in {".", ".."} for name in names):
                errors.append("证据包包含不允许的文件路径")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format_version") != 1 or not isinstance(manifest.get("files"), dict):
                raise ValueError("不支持的证据清单格式")
            expected = set(manifest["files"]) | {"manifest.json"}
            if set(names) != expected:
                errors.append("文件集合与清单不一致")
            for name, entry in manifest["files"].items():
                if name not in names:
                    errors.append("缺少文件：" + name)
                    continue
                content = archive.read(name)
                if len(content) != entry.get("size") or hashlib.sha256(content).hexdigest() != entry.get("sha256"):
                    errors.append("内容校验失败：" + name)
            return {"valid": not errors, "run_id": manifest.get("run_id"), "files_checked": len(manifest["files"]), "errors": errors}
    except (ValueError, KeyError, TypeError, AttributeError, zipfile.BadZipFile) as exc:
        return {"valid": False, "files_checked": 0, "errors": ["证据包格式不完整或已损坏：" + type(exc).__name__]}
