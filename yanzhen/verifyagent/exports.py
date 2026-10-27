from __future__ import annotations

import hashlib
import json
import zipfile

from .schema import Run
from .repository import path, load_target


def export(run: Run):
    directory = path("runs", run.id)
    payloads = {"contract.json":(directory / "contract.json").read_bytes()}
    payloads['target.json']=json.dumps(load_target(run.target_id).model_dump(mode='json'),ensure_ascii=False,indent=2).encode()
    target = load_target(run.target_id)
    if target.project_id:
        from .projects import folder, load_project
        payloads['project.json'] = json.dumps(load_project(target.project_id), ensure_ascii=False, indent=2).encode()
        payloads['source-manifest.json'] = (folder(target.project_id) / 'manifest.json').read_bytes()
    for name, value in (("report.json",run.model_dump(mode="json")),("evidence-graph.json",run.graph),("trusted-trace.json",run.trace)):
        payloads[name] = json.dumps(value, ensure_ascii=False, indent=2).encode()
    for name in {e.artifact_reference for e in run.evidence if e.artifact_reference}:
        if name.startswith("screen-") and name.endswith(".png") and "/" not in name and "\\" not in name:
            payloads[name] = (directory / name).read_bytes()
    payloads["README.md"] = ("# VerifyAgent evidence\n\nContains a frozen contract, executor-authored trace, evidence graph and report.\n"
        "Model mode and actual token usage are recorded in report.json. Manual mode is not autonomous inference.\n"
        "Screenshots mask password inputs, declared sensitive elements and known identity secrets.\n"
        "Fresh browser/API sessions do not imply a fresh backend. Backend isolation depends on the target's declared namespace protocol.\n"
        "Hashes check content integrity; they are not signatures proving who created the files.\n").encode()
    manifest = {"format_version":1,"run_id":run.id,"contract_digest":run.contract_digest,
                "files":{name:{"size":len(data),"sha256":hashlib.sha256(data).hexdigest()} for name,data in sorted(payloads.items())}}
    payloads["manifest.json"] = json.dumps(manifest,ensure_ascii=False,indent=2).encode()
    temporary = directory / "evidence.zip.tmp"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads.items():
            archive.writestr(name,data)
    temporary.replace(directory / "evidence.zip")
    (directory / "manifest.json").write_bytes(payloads["manifest.json"])
