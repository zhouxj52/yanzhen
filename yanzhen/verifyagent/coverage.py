"""Explain literal requirement links using only frozen checks and sealed observations.

This is a traceability view, not an LLM estimate of semantic requirement coverage.
Unquoted text, ambiguous repeated quotations and incomplete checks stay visible.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

from .schema import Bundle, Run, digest
from .oracle import evaluate, operation_gaps


METHOD = "literal-requirement-traceability-v1"
NOTE = "按需求原文的精确引用关联冻结检查；引用关联和检查通过不等于已证明整段需求的全部语义。未引用的文字、前置条件和含歧义的重复引用不会计为已验证。"
STATES = {
    "verified": "关联检查已验证", "failed": "发现问题", "blocked": "检查受阻",
    "unclear": "需要澄清", "uncovered": "未覆盖", "partial": "部分原文未关联",
    "not_run": "尚未执行",
}


def requirement_spans(text: str) -> list[dict]:
    """Deterministic sentence/line boundaries, preserving original string offsets."""
    rows = []
    boundary = re.compile(r"[。！？；](?:[”’\"']?)(?=\s|\S)|[.!?;](?=\s|$)|\r?\n+")
    start = 0
    for stop in [match.end() for match in boundary.finditer(text)] + [len(text)]:
        left, right = start, stop
        while left < right and text[left].isspace(): left += 1
        while right > left and text[right-1].isspace(): right -= 1
        if any(ch.isalnum() for ch in text[left:right]):
            rows.append({"id": "req-" + str(len(rows)+1), "start": left, "end": right, "text": text[left:right]})
        start = stop
    return rows


def occurrences(text: str, quote: str) -> list[tuple[int, int]]:
    result, offset = [], 0
    while (index := text.find(quote, offset)) >= 0:
        result.append((index, index + len(quote)))
        offset = index + 1
    return result


def _sealed(e, run, contract_id):
    return bool(e and e.run_id == run.id and e.contract_id == contract_id
                and e.provenance.get("executor") == "yanzhen.verifyagent.ToolExecutor/v1"
                and e.content_hash == digest(e.model_dump(exclude={"content_hash"})))


def build_coverage(bundle: Bundle, run: Run | None = None, target=None) -> dict:
    rows = requirement_spans(bundle.requirements)
    by_evidence = {e.evidence_id: e for e in run.evidence} if run else {}
    integrity_ok = True
    if run:
        try:
            bundle.assert_frozen()
            integrity_ok = run.bundle_id == bundle.id and run.contract_digest == bundle.digest
        except ValueError:
            integrity_ok = False
    checks, edges, graph_nodes = [], [], []
    for contract in bundle.contracts:
        result = next((r for r in run.results if r["contract_id"] == contract.id), None) if run else None
        trace = [t for t in run.trace if t["contract_id"] == contract.id] if run else []
        steps = []
        for item in trace:
            witness = by_evidence.get(item.get("evidence_id"))
            trusted = bool(_sealed(witness, run, contract.id) and witness.action_id == item["action"]["id"]
                           and witness.source_type == "tool_result"
                           and witness.provenance.get("action_digest") == item.get("action_digest")
                           and witness.provenance.get("ok") == item.get("ok"))
            steps.append({"action": item["action"], "ok": bool(item.get("ok") and trusted),
                          "evidence_id": item.get("evidence_id"), "trusted": trusted,
                          "artifact": witness.artifact_reference if trusted else None,
                          "duration_ms": item.get("duration_ms"), "error": item.get("error")})
        trusted_trace = [t for t, step in zip(trace, steps) if step["trusted"]]
        # Reading an archived report must not resolve DNS or require a still-live
        # origin allowlist. Canonicalize only the already-recorded URL strings.
        normalized = contract.model_copy(deep=True)
        comparable = [{**t, 'action': dict(t['action'])} for t in trusted_trace]
        if target:
            for required in normalized.constraints.required_operations:
                if required.url: required.url = urljoin(target.base_url.rstrip('/')+'/', required.url)
            for item in comparable:
                if item['action'].get('url'): item['action']['url'] = urljoin(target.base_url.rstrip('/')+'/', item['action']['url'])
        gaps = operation_gaps(normalized, comparable) if run else []
        for group in ("preconditions", "postconditions", "invariants"):
            for predicate in getattr(contract, group):
                key = contract.id + ":" + predicate.id
                records = [a for a in result.get("assertions", []) if a.get("assertion_id") == predicate.id] if result else []
                proofs, verdicts = [], []
                for record in records:
                    observations, valid = {}, True
                    for ref in record.get("evidence_ids", []):
                        evidence = by_evidence.get(ref)
                        valid = valid and _sealed(evidence, run, contract.id)
                        if evidence:
                            probe_id = evidence.provenance.get("probe_id")
                            probe = next((p for p in contract.probes if p.id == probe_id), None)
                            valid = valid and bool(probe and evidence.source_type == probe.source_type
                                                   and evidence.provenance.get("phase") == probe.phase)
                            observations[probe_id] = evidence
                            proofs.append({"id": ref, "probe_id": probe_id, "source_type": evidence.source_type,
                                           "value": evidence.observed_value, "ok": bool(valid and evidence.provenance.get("ok")),
                                           "artifact": evidence.artifact_reference, "action_id": evidence.action_id})
                    computed = evaluate(predicate, observations, prerequisite=group == "preconditions")
                    verdicts.append(computed["verdict"] if valid and computed["verdict"] == record.get("verdict") else "blocked")
                verdict = next((v for v in ("fail", "blocked", "unclear") if v in verdicts), "pass") if verdicts else "not_run"
                if run and (not integrity_ok or gaps or (result and result.get("verdict") == "blocked")):
                    verdict = "blocked"
                if run and run.status in {"error", "cancelled"} and verdict == "not_run": verdict = "blocked"
                positions = occurrences(bundle.requirements, predicate.source.quote)
                linked_rows = {r["id"] for r in rows if any(a < r["end"] and b > r["start"] for a, b in positions)}
                check = {"id": key, "contract_id": contract.id, "predicate_id": predicate.id,
                         "title": contract.title, "group": group, "quote": predicate.source.quote,
                         "basis": predicate.source.basis, "operator": predicate.op,
                         "expected": predicate.expected, "right_probe": predicate.right_probe,
                         "probes": [p.model_dump(mode="json") for p in contract.probes if p.id in {predicate.left, predicate.right_probe}],
                         "verdict": verdict, "evidence": list({p["id"]: p for p in proofs}.values()),
                         "steps": steps, "operation_gaps": gaps, "quote_spans": positions,
                         "ambiguous": len(positions) > 1 and len(linked_rows) > 1}
                checks.append(check)
    for row in rows:
        linked = [c for c in checks if any(a < row["end"] and b > row["start"] for a, b in c["quote_spans"])]
        outcome = [c for c in linked if c["group"] != "preconditions"]
        direct = [c for c in outcome if c["basis"] == "direct"]
        covered = {i for c in direct for a, b in c["quote_spans"]
                   for i in range(max(a, row["start"]), min(b, row["end"]))}
        missing = [i for i in range(row["start"], row["end"]) if bundle.requirements[i].isalnum() and i not in covered]
        if not outcome: state, reason = "uncovered", "没有关联的结果检查；前置条件不能证明需求已满足。"
        elif any(c["verdict"] == "fail" for c in outcome): state, reason = "failed", "至少一项关联检查发现与冻结标准不一致的实际观测。"
        elif any(c["verdict"] == "blocked" for c in outcome): state, reason = "blocked", "所需操作、观测或证据完整性尚未满足。"
        elif any(c["ambiguous"] for c in outcome): state, reason = "unclear", "相同引用出现在多处，无法确定该检查针对哪一条需求。"
        elif missing: state, reason = "partial", "这段需求仍有未被结果检查直接引用的文字，请审阅并补充清单。"
        elif any(c["verdict"] == "unclear" for c in outcome): state, reason = "unclear", "关联检查需要澄清。"
        elif not run or any(c["verdict"] == "not_run" for c in outcome) or run.status != "completed": state, reason = "not_run", "尚未完成全部关联检查。"
        else: state, reason = "verified", "关联结果检查已完成，引用证据的哈希和来源已核对。"
        row.update(state=state, label=STATES[state], reason=reason, checks=linked,
                   unlinked_text="".join(bundle.requirements[i] for i in missing))
        graph_nodes.append({"id": row["id"], "type": "requirement", "label": row["text"], "state": state})
        for check in linked: edges.append({"source": row["id"], "target": check["id"], "relation": "quoted_by"})
    for check in checks:
        graph_nodes.append({"id": check["id"], "type": "check", "verdict": check["verdict"]})
        for proof in check["evidence"]: edges.append({"source": check["id"], "target": proof["id"], "relation": "measured_by"})
        for step in check["steps"]:
            step_id = check["contract_id"] + ":action:" + step["action"]["id"]
            graph_nodes.append({"id": step_id, "type": "action", "ok": step["ok"]})
            edges.append({"source": check["id"], "target": step_id, "relation": "executed_in_contract"})
            if step["evidence_id"]: edges.append({"source": step_id, "target": step["evidence_id"], "relation": "witnessed_by"})
    for evidence in by_evidence.values(): graph_nodes.append({"id": evidence.evidence_id, "type": "evidence", "source_type": evidence.source_type})
    return {"format_version": 1, "method": METHOD, "note": NOTE, "bundle_id": bundle.id,
            "contract_digest": bundle.digest, "run_id": run.id if run else None,
            "integrity_ok": integrity_ok, "requirements_sha256": digest(bundle.requirements),
            "summary": {"total": len(rows), **{key: sum(r["state"] == key for r in rows) for key in STATES}},
            "requirements": rows,
            "graph": {"nodes": list({n["id"]: n for n in graph_nodes}.values()),
                      "edges": list({(e["source"], e["target"], e["relation"]): e for e in edges}.values())}}
