"""Committed, blinded source-mutation campaigns with fresh browser contexts and frozen oracles."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import uuid
import zipfile
from urllib.parse import urlsplit

from pydantic import Field
from typing import Literal

from .. import store
from ..store import safe_id, write_json
from .schema import Strict, Bundle, Run, RunInput, Target, now, digest
from . import repository as repo
from .projects import load_project, save_project, folder
from .mutations import source_files, discover, apply
from .replay import trusted_actions
from .security import Redactor

TERMINAL = {'completed','error','cancelled'}


class Prepare(Strict):
    source_run_id: str
    candidate_ids: list[str] = Field(default_factory=list, max_length=6)


class Launch(Strict):
    plan_digest: str
    confirmed: bool
    approve_repeated_writes: bool
    mode: Literal['trace','team','compare'] = 'trace'
    max_model_calls: int = Field(default=12, ge=3, le=30)
    max_seconds: int = Field(default=90, ge=15, le=180)


def directory(identifier):
    return store.ARTIFACTS / 'verifyagent' / 'challenges' / safe_id(identifier)


def read(identifier, name='report'):
    if name not in {'report','plan','private'}: raise ValueError('Invalid challenge artifact')
    return json.loads((directory(identifier)/(name+'.json')).read_text(encoding='utf-8'))


def baseline(identifier):
    run = repo.load_run(identifier)
    if run.status != 'completed' or not run.results or any(r['verdict'] != 'pass' for r in run.results):
        raise ValueError('先完成正常项目验收并全项通过，再挑战这套验收')
    bundle = repo.load_bundle(run.bundle_id)
    bundle.assert_frozen()
    if bundle.digest != run.contract_digest or len(bundle.contracts) != 1:
        raise ValueError('首版反例挑战要求一份已冻结且只含一项业务契约的通过记录')
    archived = Bundle.model_validate_json((repo.path('runs',run.id)/'contract.json').read_text(encoding='utf-8'))
    archived.assert_frozen()
    if archived.digest != bundle.digest: raise ValueError('归档契约与冻结标准不一致')
    target = repo.load_target(run.target_id)
    if not target.project_id or target.interface != 'web':
        raise ValueError('请先导入 HTML/JavaScript 源码，启动静态预览并完成一次验收')
    project = load_project(target.project_id)
    if not project['static_entry']:
        raise ValueError('首版只在只读静态项目副本中构造反例，不执行任意项目启动脚本')
    actions = trusted_actions(run, bundle.contracts[0].id)
    refs = [p.url for p in bundle.contracts[0].probes if p.url]
    refs += [a.url for a in actions if a.url]
    refs += [o.url for o in bundle.contracts[0].constraints.required_operations if o.url]
    if any(urlsplit(url).scheme or url.startswith('//') for url in refs):
        raise ValueError('反例副本需要相对 URL 的原冻结检查；不能悄悄改写含绝对地址的验收标准')
    if '[REDACTED]' in json.dumps([a.model_dump() for a in actions]):
        raise ValueError('归档动作含已脱敏的输入值，不能把脱敏占位符作为真实重放数据')
    return run, bundle, target, source_files(project['id']), actions


def candidates(identifier):
    run,bundle,target,files,actions = baseline(identifier)
    values, skipped = discover(files)
    return Redactor(target)({'source_run_id':run.id, 'contract_digest':bundle.digest, 'source_sha256':load_project(target.project_id)['source_sha256'],
                            'candidates':values, 'skipped':skipped, 'scope':'语法变异候选，不保证每个候选都是有效业务缺陷；未执行源码'})


def prepare(request: Prepare):
    run,bundle,target,files,actions = baseline(request.source_run_id)
    values,skipped = discover(files)
    selection = request.candidate_ids or [v['id'] for v in values[:2]]
    lookup = {v['id']:v for v in values}
    if not selection or len(selection) != len(set(selection)) or not set(selection) <= lookup.keys():
        raise ValueError('请选择 1～6 个当前源码中真实存在的变异候选')
    selected = [lookup[key] for key in selection]
    redactor = Redactor(target)
    if any(redactor(value['before']) != value['before'] or redactor(value['after']) != value['after'] for value in selected):
        raise ValueError('变异片段含已配置的凭据，请先从源码中移除凭据再创建可导出的挑战')
    for value in selected: apply(files,value)
    identifier = uuid.uuid4().hex
    slots = [{'slot':uuid.uuid4().hex, 'kind':'control','candidate':None}]
    slots += [{'slot':uuid.uuid4().hex,'kind':'mutant','candidate':value} for value in selected]
    secrets.SystemRandom().shuffle(slots)
    private = {'nonce':secrets.token_hex(32), 'slots':slots}
    commitment = digest(private)
    project = load_project(target.project_id)
    plan = {'id':identifier,'source_run_id':run.id, 'bundle_id':bundle.id,'contract_digest':bundle.digest,
            'project_id':project['id'], 'source_sha256':project['source_sha256'], 'candidate_ids':selection,
            'candidates':selected, 'slot_ids':[row['slot'] for row in slots], 'assignment_commitment':commitment,
            'trace_digest':digest(run.trace), 'created_at':now(),
            'scope':'每个副本只应用一个预览过的语法补丁；冻结标准保持不变；执行端不接收变异标签和补丁'}
    plan['digest'] = digest(plan)
    report = {'id':identifier,'state':'prepared','plan_digest':plan['digest'], 'source_run_id':run.id,
              'contract_digest':bundle.digest, 'source_sha256':project['source_sha256'],'assignment_commitment':commitment,
              'candidate_count':len(selected),'completed_trials':[],'current_run_id':None,'events':[], 'revealed':False,
              'scope':'匿名执行由接口与工具边界实现；不是对拥有服务器文件权限者的密码学保密。变异存活不等于验收无效。'}
    write_json(directory(identifier)/'plan.json',plan)
    write_json(directory(identifier)/'private.json',private)
    write_json(directory(identifier)/'report.json',report)
    return {**Redactor(target)(plan), 'state':'prepared'}


def summarize(report, private):
    mapping = {row['slot']:row for row in private['slots']}
    metrics = {}
    expected_arms = ['single','team'] if report.get('mode')=='compare' else [report['mode']] if report.get('mode') else list(dict.fromkeys(row['arm'] for row in report['completed_trials']))
    planned_mutations = sum(row['kind']=='mutant' for row in private['slots'])
    for arm in expected_arms:
        rows = [row for row in report['completed_trials'] if row['arm']==arm]
        controls = [row for row in rows if mapping[row['slot']]['kind']=='control']
        calibrated = len(controls)==1 and controls[0]['verdict']=='pass' and controls[0]['status']=='completed'
        mutants = [row for row in rows if mapping[row['slot']]['kind']=='mutant']
        comparable = [row for row in mutants if row['status']=='completed' and row['verdict'] in {'pass','fail'}]
        detected = sum(row['verdict']=='fail' for row in comparable) if calibrated else None
        metrics[arm] = {'control_passed':calibrated,'control_false_alarms':sum(row['verdict']=='fail' for row in controls),
                        'mutant_trials':len(mutants),'planned_mutations':planned_mutations,'not_executed_mutations':planned_mutations-len(mutants),
                        'comparable_mutations':len(comparable),'detected':detected,
                        'survived':sum(row['verdict']=='pass' for row in comparable) if calibrated else None,
                        'blocked_or_unclear':sum(row not in comparable for row in mutants),
                        'observed_mutation_detection_rate':detected/len(comparable) if calibrated and comparable else None,
                        'actual_model_calls':sum(row['model_calls'] for row in rows),
                        'prompt_tokens':sum(row.get('prompt_tokens',0) for row in rows),
                        'completion_tokens':sum(row.get('completion_tokens',0) for row in rows),
                        'wall_time_ms':sum(row['wall_time_ms'] for row in rows),
                        'interpretation':'可比较语法变异中的观察检出比例，不是已标注业务缺陷召回率；无效和等价变异尚未独立标注'}
    return metrics


def compare_pairs(report, private):
    if report.get('mode')!='compare': return None
    mutant_slots={row['slot'] for row in private['slots'] if row['kind']=='mutant'}
    completed={arm:{row['slot']:row for row in report['completed_trials'] if row['arm']==arm and row['status']=='completed' and row['verdict'] in {'pass','fail'}} for arm in ('single','team')}
    shared=mutant_slots & completed['single'].keys() & completed['team'].keys()
    controls_valid=all(report['metrics'][arm]['control_passed'] for arm in ('single','team'))
    return {'same_request_and_time_caps':True, 'controls_valid':controls_valid,
            'paired_comparable_mutations':len(shared), 'unpaired_or_unexecuted_mutations':len(mutant_slots)-len(shared),
            'detections_on_shared_mutations':{arm:sum(completed[arm][slot]['verdict']=='fail' for slot in shared) for arm in ('single','team')} if controls_valid else None,
            'scope':'只在共同完成的相同变异上比较；相同请求次数和时间上限不等于相同实际费用。不能据一次样例宣称角色协作优于单角色。'}


def export(identifier):
    report = read(identifier)
    if report['state'] not in TERMINAL or not report.get('revealed'):
        raise ValueError('结束并揭晓后才能导出反例证据包')
    plan = read(identifier,'plan')
    private = read(identifier,'private')
    content = {'report.json':json.dumps(report,ensure_ascii=False,indent=2).encode(),
               'plan.json':json.dumps(plan,ensure_ascii=False,indent=2).encode(),
               'assignment-reveal.json':json.dumps(private,ensure_ascii=False,indent=2).encode(),
               'contract.json':(repo.path('runs',plan['source_run_id'])/'contract.json').read_bytes(),
               'source-manifest.json':(folder(plan['project_id'])/'manifest.json').read_bytes()}
    for row in report['completed_trials']:
        archive = repo.path('runs',row['run_id'])/'evidence.zip'
        if archive.is_file(): content['runs/'+row['run_id']+'.zip'] = archive.read_bytes()
    manifest = {'files':{name:{'size':len(value),'sha256':hashlib.sha256(value).hexdigest()} for name,value in content.items()}}
    content['manifest.json'] = json.dumps(manifest,indent=2).encode()
    temporary = directory(identifier)/'challenge.zip.tmp'
    with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,value in content.items(): archive.writestr(name,value)
    temporary.replace(directory(identifier)/'challenge.zip')


class ChallengeService:
    def __init__(self, service):
        self.service, self.tasks = service, {}

    def recover(self):
        root = store.ARTIFACTS/'verifyagent/challenges'
        for file in root.glob('*/report.json'):
            report = json.loads(file.read_text(encoding='utf-8'))
            if report['state'] in {'running','queued'}:
                report.update(state='error', error='服务重启中断反例挑战；未执行项不产生结论', current_run_id=None)
                write_json(file,report)

    def start(self, identifier, request: Launch):
        if len(self.tasks)>=2: raise ValueError('反例挑战队列已满')
        plan,report = read(identifier,'plan'),read(identifier)
        if report['state']!='prepared': raise ValueError('此反例计划已启动；重新准备计划才能再次执行')
        if not request.confirmed or not request.approve_repeated_writes or request.plan_digest != plan['digest']:
            raise ValueError('请审阅并确认这份准确的变异计划，以及在隔离副本中重复原操作的授权')
        check = {k:v for k,v in plan.items() if k!='digest'}
        if digest(check)!=plan['digest']: raise ValueError('反例计划已被修改')
        if request.mode != 'trace':
            from .jiuwen import availability
            if not availability()['ready']: raise ValueError('协作和对照模式需要可用的真实 openJiuwen 模型配置')
        run,bundle,target,files,actions = baseline(plan['source_run_id'])
        if bundle.digest!=plan['contract_digest'] or digest(run.trace)!=plan['trace_digest'] or load_project(target.project_id)['source_sha256']!=plan['source_sha256']:
            raise ValueError('源码、真实轨迹或冻结契约已变化，请重新准备计划')
        private = read(identifier,'private')
        if digest(private)!=plan['assignment_commitment']: raise ValueError('匿名分配承诺已变化')
        report.update(state='queued',mode=request.mode,limits={'per_trial_model_calls':request.max_model_calls,'per_trial_seconds':request.max_seconds})
        write_json(directory(identifier)/'report.json',report)
        task = asyncio.create_task(self.work(identifier,request))
        self.tasks[identifier] = task
        task.add_done_callback(lambda job: self.finish(identifier,job))
        return report

    def finish(self, identifier, task):
        self.tasks.pop(identifier,None)
        report = read(identifier)
        error = None if task.cancelled() else task.exception()
        if report['state'] not in TERMINAL and (task.cancelled() or error):
            report.update(state='cancelled' if task.cancelled() else 'error', current_run_id=None,
                          error='任务未完成；未执行项没有验收结论')
            write_json(directory(identifier)/'report.json',report)

    async def work(self, identifier, request):
        report,plan,private = read(identifier),read(identifier,'plan'),read(identifier,'private')
        try:
            baseline_run,bundle,target,files,actions = baseline(plan['source_run_id'])
        except Exception as exc:
            report.update(state='error',error=str(exc),current_run_id=None)
            write_json(directory(identifier)/'report.json',report)
            return
        arms = ['single','team'] if request.mode=='compare' else [request.mode]
        mapping = {row['slot']:row for row in private['slots']}
        created = []
        active_run = None
        try:
            async with self.service.semaphore:
                report['state']='running'
                write_json(directory(identifier)/'report.json',report)
                for slot in plan['slot_ids']:
                    for arm in arms:
                        # Only the source builder sees assignment metadata. The
                        # executor receives opaque target IDs and actual observations.
                        assignment = mapping[slot]
                        copy_files = files if assignment['kind']=='control' else apply(files,assignment['candidate'])
                        copy = save_project(copy_files,'challenge_copy',{'source':'anonymous_isolated_copy'})
                        created.append(copy['id'])
                        preview = await asyncio.to_thread(self.service.previews.start,copy['id'])
                        candidate = Target(name='匿名验收目标',base_url=preview['base_url'],environment='test',authorized=True,
                                           identities=target.identities,namespace_header=target.namespace_header,
                                           isolation_note='独立只读静态副本；每次运行使用全新的浏览器上下文。执行侧没有源码快照引用。')
                        repo.save_target(candidate)
                        planner = 'manual' if arm=='trace' else 'openjiuwen_team' if arm=='team' else 'openjiuwen'
                        trial = Run(bundle_id=bundle.id,target_id=candidate.id,contract_digest=bundle.digest,planner=planner,
                                    challenge_id=identifier,challenge_slot=slot)
                        active_run = trial
                        trial_request = RunInput(bundle_id=bundle.id,planner=planner,manual_actions=actions if arm=='trace' else [],
                                                 max_model_calls=request.max_model_calls,max_seconds=request.max_seconds)
                        write_json(repo.path('runs',trial.id)/'contract.json',bundle.model_dump(mode='json'))
                        write_json(repo.path('runs',trial.id)/'request.json',trial_request.model_dump(mode='json'))
                        repo.save_run(trial)
                        self.service.active[trial.id]=trial
                        report['current_run_id']=trial.id
                        write_json(directory(identifier)/'report.json',report)
                        allowed = {digest(a) for a in actions}
                        async def approve(run,action):
                            if arm=='trace':
                                if digest(action) not in allowed: raise ValueError('固定轨迹不能引入未经确认的新动作')
                                return True
                            return await self.service.require_approval(run,action)
                        from .engine import execute
                        try:
                            result = await execute(trial,trial_request,approve)
                        finally:
                            self.service.active.pop(trial.id,None)
                            self.service.waiters.pop(trial.id,None)
                            await asyncio.to_thread(self.service.previews.stop,copy['id'])
                        verdict = result.results[0]['verdict'] if len(result.results)==1 else 'blocked'
                        calls = result.usage.get('calls',[])
                        actual_calls = result.usage.get('actual_model_requests',sum(len(c['underlying_calls']) if 'underlying_calls' in c else 1 for c in calls))
                        report['completed_trials'].append({'slot':slot,'arm':arm,'run_id':trial.id,'status':result.status,'verdict':verdict,
                                                           'model_calls':actual_calls,'wall_time_ms':result.usage.get('wall_time_ms',0),
                                                           'prompt_tokens':result.usage.get('prompt_tokens',0),'completion_tokens':result.usage.get('completion_tokens',0),
                                                           'contract_digest':result.contract_digest})
                        report['current_run_id']=None
                        write_json(directory(identifier)/'report.json',report)
                        active_run = None
                        if result.status=='cancelled' or any(a.get('approved') is False for a in result.approvals):
                            raise asyncio.CancelledError()
                report['state']='completed'
        except asyncio.CancelledError:
            report.update(state='cancelled',error='已取消；未完成项不产生验收结论')
        except Exception as exc:
            report.update(state='error',error=Redactor(target)(f'{type(exc).__name__}: {exc}')[:800])
        finally:
            if active_run:
                self.service.active.pop(active_run.id,None)
                self.service.waiters.pop(active_run.id,None)
            for copy_id in created:
                await asyncio.to_thread(self.service.previews.stop,copy_id)
            report['current_run_id']=None
            report['finished_at']=now()
            try:
                if digest(read(identifier,'private'))!=plan['assignment_commitment'] or digest(private)!=plan['assignment_commitment']:
                    raise ValueError('匿名分配揭晓与事前承诺不一致')
                source_files(plan['project_id'])
                current_bundle=repo.load_bundle(bundle.id)
                current_bundle.assert_frozen()
                if current_bundle.digest!=plan['contract_digest']: raise ValueError('冻结标准已变化')
                report['integrity_verified']=True
                report['revealed']=True
                report['assignment_reveal']=private
                report['metrics']=summarize(report,private)
                report['comparison']=compare_pairs(report,private)
                write_json(directory(identifier)/'report.json',report)
                export(identifier)
            except Exception as exc:
                report.update(state='error',integrity_verified=False,error=str(exc),revealed=False)
                report.pop('assignment_reveal',None)
                report.pop('metrics',None)
                write_json(directory(identifier)/'report.json',report)

    def cancel(self, identifier):
        if identifier not in self.tasks: raise ValueError('反例挑战未在运行')
        if not self.tasks[identifier].cancelling(): self.tasks[identifier].cancel()

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.cancelling(): task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
