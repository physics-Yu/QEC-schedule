"""Write R6's scoped handoff from existing immutable receipts; no jobs are run."""
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path

root=Path(__file__).resolve().parents[2]
kb=root/'knowledge/roles/R6'
evidence=kb/'evidence/T605'
job=evidence/'server-session-20261006T153530Z'
load=lambda p:json.loads(p.read_bytes())
save=lambda p,v:p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
dispatch=load(job/'dispatch.json'); status=load(job/'result/job-server/status.json')
receipt=load(evidence/'fixed-session-receipt.json'); probe=load(evidence/'D05-probe.json')
assert status['status']=='completed' and receipt['passed'] and probe['passed']
files=[job/'dispatch.json',job/'preflight.json',job/'frozen-verifier-inputs.tar.gz',job/'validation-results.tar.gz',job/'result/job-server/status.json',evidence/'fixed-session-receipt.json',evidence/'fixed-session-report.json']
save(kb/'server-job-history-handoff.json',{
 'schema_version':'R6-R7-historical-job-handoff/0.1','task_id':'T605','sender_role':'R6','receiver_role':'R7',
 'objective':'Register the already completed validation job without moving, restarting or recompiling it',
 'kb_revision':'kb-0006','required_interface_versions':{'GOV-001':'0.4.1','IF-SERVER-JOB-001':'0.1.0'},
 'read_paths':[p.relative_to(root).as_posix() for p in files],'write_scope':'R7 job index only, owned by R7',
 'deliverables':['historical job index entry'],'acceptance_checks':['Preserve budget 12 GiB and actual completed status','Do not repeat the job'],
 'dependencies':[],'unresolved_questions':[], 'host':dispatch['host'],'remote_directory':dispatch['project'],
 'budget':dispatch['budget'],'status':status,'input_sha256':dispatch['input_sha256'],
 'evidence_byte_sha256':{p.relative_to(root).as_posix():sha256(p.read_bytes()).hexdigest() for p in files},
 'validation_passed':receipt['passed'],'scope':receipt['scope'],'full_shor_passed':False,
 'future_dispatch_owner':'R7','historical_r6_launch_now_disabled':True})
note={
 'schema_version':'R6-report-version-supplement/0.1','owner':'R6','task_id':'T605','status':'metadata_correction_only',
 'reports_unchanged':['full-world-entry-report.json','full-world-placement-report.json'],
 'original_report_byte_sha256':{n:sha256((evidence/n).read_bytes()).hexdigest() for n in ('full-world-entry-report.json','full-world-placement-report.json')},
 'correction':'Full 205-carrier reports consumed R1-PREINITIALIZED-IF-001 0.2.0 optional inventory/probe fields; the embedded R1 0.1.0 label was stale. Original frozen report bytes are retained.',
 'rerun':False,'runtime_dynamic_leases_qualified':False,'full_program_passed':False}
save(evidence/'full-world-version-supplement.json',note)
p=kb/'status.md'; old=p.read_text(encoding='utf-8'); history=old[old.index('## 历史交付 T604'):]
current='''# R6 独立验证与基准状态

## 当前主线 T605（2026-10-06）

R6-T605-STATUS-001；owner R6；version 0.2.0；status in_progress；updated_at 2026-10-06 Asia/Shanghai；applies_to T040完整Shor双层DAG；dependencies kb-0006 / plan-0008；evidence evidence/T605/；supersedes本节0.1.0，不覆盖历史原始证据。

已读INDEX/registry、charter1.3.0、governance0.4.1、roles1.1.0、ADR-0008 1.0.0、IF-HIERARCHICAL-DAG-001 0.1.0、IF-SERVER-JOB-001 0.1.0及T605。共享目录仍有既有未跟踪全项目修改，只写src/na_pipeline/validation、tests/validation、knowledge/roles/R6。后续所有重型服务器任务由R7统一派发，R6提交spec/固定输入/预算。历史服务器作业交接见server-job-history-handoff.json；旧自派发入口已关闭。

完整逻辑源检查仍为2069源操作、2102节点、817 T/TDG需求、5个首用reset迁入入口。D01同一冻结输入83条直接机械边标relaxed；其中35对不再传递可达，不能混用计数。四SE真实分量224源操作/827动作/32结果/71382μs通过；490个不同实际动作重叠见证、28共享动作只计一次。真实SE/H/X/Z/CX/CZ静态检查、两份实际SA布局及输出→初态检查均有独立报告。

固定R5五窗口已独立通过：12逻辑节点、538物理操作、2111动作、64结果、68载体、175847μs；fixed-session-report.json和fixed-session-receipt.json的failures/unverified为空。读取已有窗口，没有重编或重跑placer。此前本地2GiB任务在3.219秒达到预算，保留budget_exhausted_incomplete；扩大为服务器1800秒/12GiB/1线程/0搜索，监督器31.351秒完成、验证主体26.036秒，峰值root RSS 2813767680字节。只证明固定runtime0.1.1四patch连续源/几何/因果，不外推到新runtime或完整工厂。

D05最新0.1.2复验14项全部通过（0.875秒，源前后稳定）：guard结果值/producer/ready/refs伪造拒绝、延期ready与反馈保留、旧revision/重复绑定/共享动作复制拒绝；deferred草案仅改complete=true仍拒绝。历史guard及deferred漏洞保留D05-*-before-fix和D05-*-before-deferred-fix。当前读取D05-probe.json；不能把历史失败写成仍未修复。

完整205世界入口及原始SA输出映射检查通过：5算法patch+7工厂patch+1probe、85 data/120 magic载体、空启动/结果/ready token。输入examples/atom/t405/resource-world-server-v1/world.json.gz；独立报告full-world-entry-report.json/full-world-placement-report.json。R1消费版本实际0.2.0，旧标签0.1.0的补充在full-world-version-supplement.json；冻结报告不改。该结果尚不证明动态租约/工厂执行。

已消费R5 session0.1.2、resource-pool0.1.0-draft及R8 factory-phase-review0.2.0/O01～O09；不重做R8算符计算。下一步独立核同载体、Y/probe/mutex排他、全部DAG终端/结果ready、实际cleanup与epoch；O04～O07完整候选/转换/ready/单次消费仍需生产控制器实际工件。R4首工厂stage和R5代表完整协议已在服务器运行，不重复编译。完整八轮Shor、factory接受/拒绝/T消费及后处理尚未通过，用户视觉pending；继续同一授权主线。

'''
p.write_text(current+history,encoding='utf-8')
p=kb/'hierarchical-review.md'; text=p.read_text(encoding='utf-8')
start=text.index('**D05最新复核：'); end=text.index('\n\n四SE真实联合工件',start)
text=text[:start]+'''**D05最新0.1.2复核已通过14项，源前后稳定。** 当前D05-probe.json同时覆盖合法非零第二窗口与guard/ready/revision/重复绑定/共享动作/deferred拒绝。仅修改deferred的complete=true已被SESSION_RUNTIME_INPUTS_UNRESOLVED拒绝。第二窗口本次frontier为17692μs，与早期18555μs探针不是同一版本性能比较。此前deferred反例和真实context签发见D05-probe-before-deferred-fix.json/D05-inputs-before-deferred-fix.json.gz，保留历史；不再列为当前阻塞。

固定runtime0.1.1五窗口真实连续链独立通过，读取fixed-session-report.json/receipt.json：12逻辑节点、538物理操作、2111动作、64结果、68载体、175847μs。服务器1800秒/12GiB/1线程/0搜索，31.351秒完成；主体26.036秒。源/输入前后稳定，未重编。仅固定四patch分量；完整工厂/205动态世界仍待独立验证。历史作业位置与哈希已在server-job-history-handoff.json交给R7登记，遵循新GOV0.4.1，后续重型任务不再由R6自行dispatch。

205世界入口与真实SA输出映射已通过；R1版本标签补充full-world-version-supplement.json，不改旧冻结报告。动态池和完整代表工厂继续消费R8 0.2.0 O01～O09，检查终端/结果ready与实际清理，避免把最后target Z当整个Y仪器完成。'''+text[end:]
p.write_text(text,encoding='utf-8')
print(json.dumps({'history_handoff':str(kb/'server-job-history-handoff.json'),'D05_cases':len(probe['cases']),'fixed_session_passed':receipt['passed']},ensure_ascii=False))
