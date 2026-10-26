"""Deterministic predicates over executor-authored evidence, independent of planning."""
from __future__ import annotations

import operator
from typing import Callable

from .schema import Evidence, GenericContract, Predicate, digest

RULES: dict[str, Callable] = {}


def register(name: str, rule: Callable):
    if name in RULES:
        raise ValueError("Duplicate predicate rule")
    RULES[name] = rule


def same(a, b):
    # Python considers True == 1. The business oracle must not.
    return type(a) is type(b) and a == b


register("eq", same)
register("ne", lambda a, b: not same(a, b))
register("contains", lambda a, b: b in a)
register("not_contains", lambda a, b: b not in a)
register("in", lambda a, b: a in b)
register("not_in", lambda a, b: a not in b)
register("gte", operator.ge)
register("lte", operator.le)


def evaluate(assertion: Predicate, observations: dict[str, Evidence], *, prerequisite=False) -> dict:
    left = observations.get(assertion.left)
    right = observations.get(assertion.right_probe) if assertion.right_probe else None
    refs = [e for e in (left, right) if e is not None]
    base = {"assertion_id": assertion.id, "source": assertion.source.model_dump(), "evidence_ids": [e.evidence_id for e in refs]}
    if left is None or (assertion.right_probe and right is None):
        return {**base, "verdict": "blocked", "reason": "Required observation is missing"}
    if any(e.content_hash != digest(e.model_dump(exclude={"content_hash"})) for e in refs):
        return {**base, "verdict": "blocked", "reason": "Evidence content hash mismatch"}
    if any(not e.provenance.get("ok", False) for e in refs):
        return {**base, "verdict": "blocked", "reason": "The observation tool failed"}
    actual = left.observed_value
    expected = right.observed_value if right else assertion.expected
    try:
        passed = bool(RULES[assertion.op](actual, expected))
    except (TypeError, ValueError, KeyError):
        return {**base, "verdict": "unclear", "reason": "Predicate types are incompatible"}
    verdict = "pass" if passed else "blocked" if prerequisite else "fail"
    return {**base, "verdict": verdict, "actual": actual, "expected": expected, "operator": assertion.op}


def operation_gaps(contract: GenericContract, trace: list[dict], target=None) -> list[dict]:
    """Only executor-witnessed operations satisfy the immutable action constraints."""
    assertions=[]
    completed_kinds = {x["action"]["kind"] for x in trace if x.get("ok")}
    missing = set(contract.constraints.required_actions) - completed_kinds
    if missing:
        assertions.append({"assertion_id": "required_actions", "verdict": "blocked", "reason": "Required actions were not executed", "missing": sorted(missing), "evidence_ids": []})
    for index,required in enumerate(contract.constraints.required_operations):
        fields={k:v for k,v in required.model_dump().items() if v is not None}
        def matches(action):
            for key,value in fields.items():
                actual=action.get(key)
                if key=='url' and target is not None:
                    from .security import TargetPolicy, PolicyError
                    try:
                        policy=TargetPolicy(target)
                        actual,value=policy.validate(actual),policy.validate(value)
                    except (ValueError,TypeError,AttributeError):
                        return False
                if not same(actual,value):return False
            return True
        if not any(row.get('ok') and matches(row['action']) for row in trace):
            assertions.append({'assertion_id':'required_operation_'+str(index),'verdict':'blocked','reason':'Required business operation was not witnessed','required_operation':fields,'evidence_ids':[]})
    return assertions


def decide(contract: GenericContract, observations: dict[str, Evidence], trace: list[dict], invariant_results: list[dict] | None = None, *, target=None) -> dict:
    assertions = [evaluate(p, observations) for p in contract.postconditions]
    assertions += invariant_results or []
    assertions += operation_gaps(contract,trace,target)
    verdicts = {a["verdict"] for a in assertions}
    # Missing required operations makes a failed postcondition uninterpretable.
    operation_blocked=any(a['verdict']=='blocked' and a['assertion_id'].startswith('required_') for a in assertions)
    verdict = 'blocked' if operation_blocked else next((v for v in ("fail", "blocked", "unclear") if v in verdicts), "pass")
    failed = sorted(a["assertion_id"] for a in assertions if a["verdict"] == "fail")
    # Concrete markers and timestamps are excluded; the same frozen predicates must fail.
    fingerprint = digest({"contract": contract.id, "failed_predicates": failed}) if failed and verdict=='fail' else ""
    return {"contract_id": contract.id, "title": contract.title, "verdict": verdict, "assertions": assertions, "fingerprint": fingerprint}


def evidence_graph(evidence: list[Evidence], results: list[dict], trace: list[dict]) -> dict:
    nodes = [dict(e.model_dump(mode="json"), node_type="evidence") for e in evidence]
    edges = []
    for result in results:
        nodes.append({"id":result["contract_id"],"node_type":"contract","verdict":result["verdict"]})
        for index,assertion in enumerate(result.get("assertions", [])):
            node_id = result["contract_id"] + ":" + assertion["assertion_id"] + ":" + str(index)
            nodes.append({"id": node_id, "node_type": "assertion", **assertion})
            relation = "contradicts" if assertion["verdict"] == "fail" else "supports" if assertion["verdict"] == "pass" else "depends_on"
            edges.append({"source":node_id,"target":result["contract_id"],"relation":relation})
            for ref in assertion.get("evidence_ids", []):
                edges.append({"source": ref, "target": node_id, "relation": relation})
    by_action = {(e.contract_id, e.action_id): e.evidence_id for e in evidence}
    for item in trace:
        for dep in item["action"].get("depends_on", []):
            source = by_action.get((item["contract_id"], dep))
            target = by_action.get((item["contract_id"], item["action"]["id"]))
            if source and target:
                edges.append({"source": target, "target": source, "relation": "depends_on"})
    return {"nodes": nodes, "edges": edges}
