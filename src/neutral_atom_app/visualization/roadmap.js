/* Read-only status view. No POST, execution, approval, or retry action. */
(()=>{'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={pending:'未开始',running:'正式验收中',passed:'已通过',failed:'失败 · 已停止',awaiting_approval:'失败 · 等待用户审批'};
const approvalLabels={pending:'等待用户明确审批',approved:'已记录用户审批；本页面不会发起重试',rejected:'用户未批准重试；保持停止'};
let ledger=null,openedFailure=null,lastFocus=null;
const list=items=>items?.length?'<ul>'+items.map(v=>'<li>'+esc(v)+'</li>').join('')+'</ul>':'<p class="muted">尚未记录</p>';
function evidenceMarkup(items){return items?.length?'<h3>证据路径</h3><ul>'+items.map(e=>'<li>'+esc(e.label)+'<br><code>'+esc(e.path)+'</code></li>').join('')+'</ul>':'<p class="muted">尚无证据路径</p>';}
function failureMarkup(attempt){const f=attempt.failure;return '<section class="facts"><h3>已观察到的事实</h3>'+list(f.facts)+'</section><section class="hypotheses"><h3>原因假设 · 尚待核实</h3>'+list(f.hypotheses)+'</section><h3>拟议重试范围 · 尚未执行</h3>'+list(f.proposed_retry_scope)+'<p class="approval">'+esc(approvalLabels[f.approval.status])+'</p>'+(f.approval.user_message?'<p>用户审批原文：'+esc(f.approval.user_message)+'</p>':'')+evidenceMarkup(attempt.evidence);}
function openFailure(stage,attempt){lastFocus=document.activeElement;$('failure-title').textContent=stage.title;$('failure-attempt').textContent='Attempt '+attempt.number+' · '+(attempt.finished_at||'结束时间未记录');$('failure-body').innerHTML=failureMarkup(attempt);$('failure-dialog').hidden=false;$('failure-close').focus();}
function closeFailure(){$('failure-dialog').hidden=true;lastFocus?.focus?.();}
$('failure-close').onclick=closeFailure;
$('failure-dialog').onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();closeFailure();}if(e.key==='Tab'){e.preventDefault();$('failure-close').focus();}};
function render(value){
 ledger=value;$('error').hidden=true;$('updated').textContent='持久记录更新时间：'+(value.updated_at||'未记录')+' · 每 10 秒只读刷新';
 $('stages').innerHTML=value.stages.map((stage,index)=>{
  const attempts=stage.attempts||[],formal=attempts.filter(a=>a.formal),latest=formal.at(-1);
  return '<article class="stage" data-stage="'+esc(stage.id)+'"><div class="stage-head"><div><div class="eyebrow">STEP '+(index+1)+'</div><h2>'+esc(stage.title)+'</h2></div><span class="tag '+esc(stage.status)+'">'+esc(labels[stage.status])+'</span></div><p class="muted">'+(latest?'正式 Attempt '+latest.number+' · '+esc(latest.status):'尚无正式验收记录')+'</p>'+(['failed','awaiting_approval'].includes(stage.status)?'<button data-failure="'+index+'">查看失败报告</button>':'')+'<details><summary>尝试历史 · '+attempts.length+' 条</summary>'+attempts.map(a=>'<div class="attempt"><strong>Attempt '+a.number+' · '+(a.formal?'正式验收':'非正式局部检查')+' · '+esc(labels[a.status]||a.status)+'</strong><p class="muted small">'+esc(a.started_at||'')+(a.finished_at?' → '+esc(a.finished_at):'')+'</p>'+(a.formal&&a.status==='failed'?failureMarkup(a):evidenceMarkup(a.evidence))+'</div>').join('')+'</details></article>';
 }).join('');
 for(const button of document.querySelectorAll('[data-failure]'))button.onclick=()=>{const s=ledger.stages[Number(button.dataset.failure)];openFailure(s,s.attempts.filter(a=>a.formal).at(-1));};
 const stage=value.stages.find(s=>['failed','awaiting_approval'].includes(s.status));
 if(stage){const attempt=stage.attempts.filter(a=>a.formal).at(-1),key=stage.id+':'+attempt.number+':'+JSON.stringify(attempt.failure);
  if(key!==openedFailure){openedFailure=key;openFailure(stage,attempt);}
 }else{openedFailure=null;if(!$('failure-dialog').hidden)closeFailure();}
}
async function refresh(){try{const response=await fetch('status.json',{cache:'no-store'});const value=await response.json();if(!response.ok)throw Error(value.error||'状态读取失败');if(value.schema_version!==1||!Array.isArray(value.stages)||value.stages.length!==4)throw Error('状态格式不正确');render(value);}catch(e){$('error').textContent='状态记录不可用：'+e.message+'。未确认的阶段不会显示通过。';$('error').hidden=false;$('stages').innerHTML='';$('updated').textContent='当前没有可确认的阶段状态';}}
$('refresh').onclick=refresh;refresh();setInterval(refresh,10000);
})();
