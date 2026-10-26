"""Persistent pre-request cost reservations; failures never silently refund uncertainty."""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal, ROUND_UP
import json
import os
import time
import uuid

from .. import store
from ..models import now


class BudgetExceeded(ValueError):
    pass


@contextmanager
def ledger_lock(destination):
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.with_suffix('.lock').open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        deadline=time.monotonic()+3
        while True:
            try:
                handle.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline:raise BudgetExceeded('Cost ledger is busy; no request was sent')
                time.sleep(.03)
        try:yield
        finally:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle,fcntl.LOCK_UN)


def destination():
    return store.ARTIFACTS/'verifyagent'/'model-budget.json'


def reserve(provider: str, model: str, messages: list, max_output: int):
    limit=Decimal(os.getenv('YZ_VERIFY_BUDGET_CNY','0'))
    if limit<=0:return None
    if provider=='jiuwenswarm':
        raise BudgetExceeded('Capped paid validation cannot use an unmetered external Swarm runtime')
    if os.getenv('YZ_VERIFY_PRICED_MODEL')!=model:
        raise BudgetExceeded('Price configuration is not bound to the selected model')
    rates=[os.getenv('YZ_VERIFY_INPUT_CNY_PER_MILLION'),os.getenv('YZ_VERIFY_OUTPUT_CNY_PER_MILLION')]
    if not all(rates):raise BudgetExceeded('Configure verified CNY input/output prices before paid validation')
    incoming,outgoing=map(Decimal,rates)
    if incoming<0 or outgoing<0:raise BudgetExceeded('Invalid model prices')
    size=len(json.dumps(messages,ensure_ascii=False).encode('utf-8'))
    if size>120000 or max_output>4000:
        raise BudgetExceeded('Request exceeds the conservatively bounded text-only validation envelope')
    tokens=size+4096  # UTF-8 bytes plus protocol overhead: deliberately much larger than normal token estimates.
    upper=((tokens*incoming+max_output*outgoing)/1_000_000).quantize(Decimal('.000001'),rounding=ROUND_UP)
    file=destination()
    with ledger_lock(file):
        ledger=json.loads(file.read_text(encoding='utf-8')) if file.exists() else {'limit_cny':str(limit),'reserved_upper_cny':'0','records':[]}
        approved=min(limit,Decimal(ledger['limit_cny']))
        total=Decimal(ledger['reserved_upper_cny'])
        if total+upper>approved or len(ledger['records'])>=int(os.getenv('YZ_VERIFY_MAX_PAID_CALLS','16')):
            raise BudgetExceeded('Paid-validation budget exhausted; no request was sent')
        entry={'id':uuid.uuid4().hex,'timestamp':now(),'provider':provider,'model':model,'input_token_upper':tokens,'max_output_tokens':max_output,
               'input_cny_per_million':str(incoming),'output_cny_per_million':str(outgoing),'reserved_upper_cny':str(upper),'status':'reserved'}
        ledger['reserved_upper_cny']=str(total+upper);ledger['records'].append(entry)
        store.write_json(file,ledger)
        return entry


def finish(entry: dict | None, status: str, usage: dict | None=None):
    if entry is None:return
    file=destination()
    with ledger_lock(file):
        ledger=json.loads(file.read_text(encoding='utf-8'))
        item=next(r for r in ledger['records'] if r['id']==entry['id'])
        item.update(status=status,usage=usage or {})
        if usage and 'prompt_tokens' in usage and 'completion_tokens' in usage:
            peak=(Decimal(usage['prompt_tokens'])*Decimal(item['input_cny_per_million'])+Decimal(usage['completion_tokens'])*Decimal(item['output_cny_per_million']))/1_000_000
            item['usage_cost_upper_cny']=str(peak)
            if peak>Decimal(item['reserved_upper_cny']):
                # Fail closed for all subsequent calls if provider accounting exceeds the stated envelope.
                ledger['reserved_upper_cny']=ledger['limit_cny']
                item['status']='usage_exceeded_reservation'
        store.write_json(file,ledger)
