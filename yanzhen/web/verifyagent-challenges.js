import {esc, pretty, describeAction} from './verifyagent-view.js?v=atelier-10';
const $ = s => document.querySelector(s);
const ended = report => ['completed','error','cancelled'].includes(report?.state);
const roles = {requirements:'需求分析',challenger:'反例挑战',executor:'执行规划',evidence_auditor:'证据审查',return:'完成交接'};
const states = {started:'正在执行',completed:'已完成',handoff:'要求补证',revision:'已修正规划',error:'执行受阻'};
const arms = {trace:'固定真实轨迹',single:'openJiuwen 单规划角色',team:'openJiuwen 多角色'};

export function renderRoles(element, run) {
  const events = run?.collaboration || [];
  element.hidden = !events.length;
  if (!events.length) return;
  const latest = new Map();
  for (const event of events) latest.set(event.role,event);
  element.innerHTML = `<h3>openJiuwen 协作交接</h3><div class="va-role-cards">${[...latest].filter(([role])=>role!=='return').map(([role,event])=>
    `<article><strong>${esc(roles[role] || role)}</strong><span>${esc(states[event.state] || event.state)}${event.cached?' · 复用已校验的分析':''}</span><p>${esc(event.summary || '官方 Workflow 正在调度此角色。')}</p></article>`).join('')}</div>
    <p class="va-field-help">需求、挑战与执行角色调用模型；证据审查按规则核对操作义务，最终结论由原冻结断言计算。</p>
    <details><summary>查看真实角色事件与工作流 ID</summary><pre>${esc(pretty(events))}</pre></details>`;
}

export class ChallengePanel {
  constructor(context) {
    this.context=context;this.plan=null;this.report=null;this.trial=null;this.working=false;this.polling=false;
    for (const [id,fn] of [
      ['#va-discover-challenges',()=>this.discover()],['#va-prepare-challenge',()=>this.prepare()],
      ['#va-start-challenge',()=>this.start()],['#va-cancel-challenge',()=>this.cancel()],
      ['#va-challenge-approve',()=>this.approve(true)],['#va-challenge-deny',()=>this.approve(false)]]) {
      $(id).addEventListener('click',async event=>{
        event.preventDefault();if(this.working)return;
        this.working=true;this.context.controls();
        try {await fn();} catch(error) {this.context.error(error);}
        finally {this.working=false;this.context.controls();}
      });
    }
    $('#va-challenge-consent').addEventListener('change',()=>this.syncControls());
    $('#va-challenge-candidates').addEventListener('change',()=>{
      this.plan=null;$('#va-challenge-plan').hidden=true;$('#va-challenge-consent').checked=false;this.syncControls();
    });
  }

  get running() {return !!this.report && !ended(this.report) && this.report.state!=='prepared';}
  get busy() {return this.working || this.running;}

  reset() {
    this.plan=null;this.report=null;this.trial=null;
    for (const id of ['#va-challenge-candidates','#va-challenge-results','#va-challenge-status','#va-challenge-plan']) $(id).innerHTML='';
    $('#va-challenge-plan').hidden=true;$('#va-prepare-challenge').hidden=true;
    $('#va-challenge-consent').checked=false;$('#va-challenge-approval').hidden=true;
    $('#va-challenge-mode').value='trace';
    $('#va-challenge-role-log').hidden=true;
  }

  syncControls() {
    const {state}=this.context;
    const eligible=state.run?.status==='completed' && state.run.results.length===1 && state.run.results.every(r=>r.verdict==='pass') && !!state.target?.project_id;
    $('#va-challenge-tools').hidden=!eligible && !this.report;
    const selected=document.querySelectorAll('[data-mutation]:checked').length;
    $('#va-discover-challenges').disabled=!eligible || this.busy;
    $('#va-prepare-challenge').disabled=this.busy || selected<1 || selected>6;
    $('#va-start-challenge').disabled=this.busy || !this.plan || !$('#va-challenge-consent').checked || !!this.report;
    $('#va-cancel-challenge').disabled=!this.running || this.working;
    $('#va-challenge-mode').disabled=this.busy || !!this.report;
    for(const value of ['team','compare']) $(`#va-challenge-mode option[value=${value}]`).disabled=!state.config?.openjiuwen?.ready;
    for(const input of document.querySelectorAll('[data-mutation]')) input.disabled=this.busy;
    const awaiting=!!this.trial?.pending_approval && this.running;
    $('#va-challenge-approval').hidden=!awaiting;
    $('#va-challenge-approve').disabled=this.working || !awaiting;
    $('#va-challenge-deny').disabled=this.working || !awaiting;
  }

  async discover() {
    const result=await this.context.api('/challenges/candidates/'+this.context.state.run.id);
    this.plan=null;this.report=null;
    $('#va-challenge-candidates').innerHTML=result.candidates.length?result.candidates.map((candidate,index)=>
      `<label class="va-mutation-choice"><input type="checkbox" data-mutation="${esc(candidate.id)}" ${index<2?'checked':''}/><span><strong>${esc(candidate.label)}</strong><span>${esc(candidate.file)} · 第 ${candidate.line} 行</span><code>${esc(candidate.before.slice(0,300))} → ${esc(candidate.after)}</code></span></label>`).join(''):
      '<p>当前源码没有受支持的变异位置。首版支持 ECMAScript 2017 的存储写入、比较边界和相等条件。</p>';
    if(result.skipped.length) $('#va-challenge-candidates').innerHTML+=`<details><summary>未处理的源码</summary><pre>${esc(pretty(result.skipped))}</pre></details>`;
    $('#va-prepare-challenge').hidden=!result.candidates.length;
    $('#va-challenge-results').innerHTML='';$('#va-challenge-status').textContent='候选是语法变异，是否形成有效业务缺陷还需单独确认。';
  }

  async prepare() {
    const ids=[...document.querySelectorAll('[data-mutation]:checked')].map(e=>e.dataset.mutation);
    this.plan=await this.context.api('/challenges/prepare',{source_run_id:this.context.state.run.id,candidate_ids:ids});
    this.report=null;this.trial=null;$('#va-challenge-results').innerHTML='';
    $('#va-challenge-plan').hidden=false;
    $('#va-challenge-plan').innerHTML=`<div class="va-notice"><strong>已准备 ${this.plan.candidates.length} 个单独变异与 1 个正常对照</strong><p>开始前已固定分配承诺：<code>${esc(this.plan.assignment_commitment)}</code></p><p>计划：<code>${esc(this.plan.digest)}</code>。正常和变异目标随机排序，执行者看不到标签。</p></div>
      <details><summary>审阅准确补丁与源码版本</summary><pre>${esc(pretty(this.plan))}</pre></details>`;
    $('#va-challenge-consent').checked=false;
  }

  async start() {
    this.report=await this.context.api(`/challenges/${this.plan.id}/start`,{plan_digest:this.plan.digest,confirmed:true,approve_repeated_writes:$('#va-challenge-consent').checked,mode:$('#va-challenge-mode').value,max_model_calls:12,max_seconds:90});
    history.replaceState(null,'',location.pathname+`?run=${this.context.state.run.id}&challenge=${this.report.id}`);
    this.follow().catch(error=>this.context.error(error));
  }

  async restore(report) {
    this.report=report;this.plan=null;$('#va-challenge-tools').open=true;
    if(report.mode) $('#va-challenge-mode').value=report.mode;
    await this.follow();
  }

  async follow() {
    if(this.polling)return;
    this.polling=true;
    try {
      do {
        this.report=await this.context.api('/challenges/'+this.report.id);
        const latestTeam=[...this.report.completed_trials].reverse().find(row=>row.arm==='team');
        const shownRun=this.report.current_run_id || (ended(this.report)?latestTeam?.run_id:null);
        this.trial=shownRun?await this.context.api('/runs/'+shownRun):null;
        this.render();this.context.controls();
        if(ended(this.report))break;
        await new Promise(resolve=>setTimeout(resolve,700));
      } while(true);
    } finally {this.polling=false;this.context.controls();}
  }

  render() {
    const report=this.report;
    const label={queued:'等待隔离环境',running:'正在匿名目标中实际验收',completed:'挑战已完成',cancelled:'挑战已取消',error:'挑战执行受阻'}[report.state] || report.state;
    $('#va-challenge-status').textContent=`${label} · 已记录 ${report.completed_trials.length} 次运行。${report.error || ''}`;
    if(this.trial?.pending_approval) $('#va-challenge-action').textContent=describeAction(this.trial.pending_approval.action);
    renderRoles($('#va-challenge-role-log'),this.trial);
    if(!report.revealed) {
      $('#va-challenge-results').innerHTML=`<p class="va-field-help">分配标签尚未揭晓。事前承诺：<code>${esc(report.assignment_commitment)}</code></p>`;
      return;
    }
    const mapping=new Map(report.assignment_reveal.slots.map(s=>[s.slot,s]));
    const verdict={pass:'通过',fail:'发现不满足原标准',blocked:'受阻',unclear:'待澄清'};
    $('#va-challenge-results').innerHTML=`<h3>揭晓结果 · ${report.integrity_verified?'已核对分配承诺、原源码和冻结标准':'完整性核对失败'}</h3>
      <div class="va-challenge-metrics">${Object.entries(report.metrics || {}).map(([arm,m])=>`<article><strong>${esc(arms[arm] || arm)}</strong><p>正常对照：${m.control_passed?'通过':'未通过，检出比例不成立'}</p><p>观察检出 ${m.detected ?? '—'} / ${m.comparable_mutations} · 存活 ${m.survived ?? '—'} · 受阻 / 待澄清 ${m.blocked_or_unclear} · 未执行 ${m.not_executed_mutations || 0}</p><p>模型请求 ${m.actual_model_calls} 次 · ${(m.wall_time_ms/1000).toFixed(1)} 秒</p></article>`).join('')}</div>
      ${report.comparison?`<p class="va-field-help">同预算对照：共同完成 ${report.comparison.paired_comparable_mutations} 个相同变异，未配对 ${report.comparison.unpaired_or_unexecuted_mutations} 个。这里只对共同完成的目标比较，尚无证据证明多角色更优。</p>`:''}
      <div class="va-challenge-table"><table><thead><tr><th>揭晓目标</th><th>执行方式</th><th>原标准结果</th><th>证据</th></tr></thead><tbody>${report.completed_trials.map(row=>{
        const item=mapping.get(row.slot),name=item?.kind==='control'?'正常对照':`${item?.candidate?.label || '变异'} · ${item?.candidate?.file || ''}`;
        return `<tr><td>${esc(name)}</td><td>${esc(arms[row.arm] || row.arm)}</td><td>${esc(verdict[row.verdict] || row.verdict)}</td><td><a href="/static/verifyagent.html?run=${row.run_id}" target="_blank" rel="noopener">查看实际记录</a></td></tr>`;
      }).join('')}</tbody></table></div><p class="va-field-help">存活可能意味着当前操作没覆盖、变异等价或与业务要求无关。这里展示语法变异观察结果，不当作业务缺陷召回率；正常对照不通过时不计算检出比例。</p>
      <a class="button secondary" href="/api/verify/challenges/${report.id}/export">下载挑战报告与逐次证据 ZIP</a><details><summary>查看补丁、匿名分配揭晓及完整指标</summary><pre>${esc(pretty(report))}</pre></details>`;
  }

  async approve(approved) {
    const trial=this.trial;
    if(!trial?.pending_approval)return;
    await this.context.api(`/runs/${trial.id}/approve`,{digest:trial.pending_approval.digest,approved,reviewer:'local-user'});
    this.trial=null;$('#va-challenge-approval').hidden=true;
  }

  async cancel() {await this.context.api(`/challenges/${this.report.id}/cancel`,{});}
}
