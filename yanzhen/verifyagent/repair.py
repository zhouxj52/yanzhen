"""Oracle-preserving review based on archived executor evidence, never caller witnesses."""
from __future__ import annotations

from .schema import Action, Bundle, digest
from .repository import path, load_run
from .replay import trusted_actions


def review(identifier: str, contract_id: str, candidates: list[Action], claimed_digest: str):
    run=load_run(identifier)
    bundle=Bundle.model_validate_json((path('runs',identifier)/'contract.json').read_text(encoding='utf-8'))
    bundle.assert_frozen()
    violations=[]
    if claimed_digest != run.contract_digest or bundle.digest != run.contract_digest:
        violations.append('Frozen oracle digest changed')
    original=trusted_actions(run,contract_id)
    failed_ids={r['action']['id'] for r in run.trace if r['contract_id']==contract_id and not r['ok']}
    if not original or not failed_ids:violations.append('No executor-witnessed tool failure supports an executor repair')
    if len(original)!=len(candidates):violations.append('Action deletion/addition is outside executor repair scope')
    for before,after in zip(original,candidates):
        if before.model_dump(exclude={'locator','timeout_ms'}) != after.model_dump(exclude={'locator','timeout_ms'}):
            violations.append('Identity, input, action, dependencies or expected tool value changed')
        if before != after and before.id not in failed_ids:
            violations.append('Changed action has no corresponding executor-witnessed failure')
    return {'accepted':not violations,'kind':'executor_repair','violations':sorted(set(violations)),'source_run':identifier,'contract_id':contract_id,
            'contract_digest':run.contract_digest,'original_trace_hash':digest(run.trace),
            'scope':'Only locator and timeout changes on witnessed failed actions; frozen predicates are never accepted as repair inputs',
            'candidate_actions':[a.model_dump(mode='json') for a in candidates]}
