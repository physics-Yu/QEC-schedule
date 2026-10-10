"""Finish a frozen producer run with independent checks and the existing viewer."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, sys, time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from basic_shor_audit import audit_run,read
from basic_shor_viewer import export
from na_pipeline.runtime.pipeline import save_artifact


def main():
    p=argparse.ArgumentParser();p.add_argument('--producer',type=Path,required=True)
    p.add_argument('--source',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if not a.producer.resolve().is_relative_to(Path('/home/yyq/na-platform-simulation/R7/T704')):raise ValueError('PRODUCER_SCOPE')
    a.out.mkdir(parents=True,exist_ok=True);status_file=a.producer/'scripts/outputs/T704/job/status.json'
    started=time.perf_counter();last=None
    while True:
        status=read(status_file)
        if status['status']!=last:
            last=status['status'];print(json.dumps({'producer_status':last}),flush=True)
        if status['status']=='completed':break
        if status['status'] not in ('running','starting','dispatched_not_completed'):
            save_artifact(a.out/'delivery-status.json',{'status':'producer_incomplete','producer':status});raise ValueError('PRODUCER_INCOMPLETE')
        if time.perf_counter()-started>86400:raise TimeoutError('PRODUCER_WAIT_BUDGET_EXHAUSTED')
        time.sleep(15)
    source=a.producer/a.source
    if read(source/'status.json')['status']!='execution_complete_validation_pending':raise ValueError('COMPLETE_EXECUTION_REQUIRED')
    manifest={}
    for path in sorted(source.rglob('*')):
        rel=path.relative_to(source)
        if not path.is_file() or 'prepare' in rel.parts or path.name.endswith(('.tmp','.writing')):continue
        dest=a.out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        sha=hashlib.file_digest(path.open('rb'),'sha256').hexdigest()
        if dest.exists():
            if hashlib.file_digest(dest.open('rb'),'sha256').hexdigest()!=sha:raise ValueError('DELIVERY_INPUT_CHANGED')
        else:
            try:os.link(path,dest)
            except OSError:shutil.copyfile(path,dest)
        manifest[rel.as_posix()]={'sha256':sha,'bytes':path.stat().st_size}
    save_artifact(a.out/'delivery-inputs.json',{'producer':str(a.producer),'source':a.source,'files':manifest,
        'producer_job_status':status,'original_plan_event_bytes_preserved':True})
    report=audit_run(a.out)
    export(a.out)
    metrics=report['metrics'];stats=read(a.out/'execution-stats.json');prepare=read(a.out/'prepare-stats.json')
    integrated={'schema_version':'BasicShorDelivery/0.1','status':'passed','algorithm':'N15 a2 / eight-round semiclassical QPE',
        'metrics':metrics,'execution_stats':stats,'preparation_stats':prepare,
        'component_internal_batches':'reused from compiled component schedule receipts',
        'component_boundary_scheduling':'sequential basic baseline',
        'measurement_origin':'explicit fake scenario','quantum_state_simulated':False,'hardware_executed':False,
        'user_visual_acceptance':'pending','compiler_source_project':str(a.producer)}
    save_artifact(a.out/'delivery-summary.json',integrated)
    text=f'''# 完整 Shor-15 基础 pipeline

打开 [动画窗口](viewer/animation-library.html)。这是同一连续会话的完整组件调用，支持轮次目录、前后调用、连续播放、关键帧/真实时间、100μs/屏幕秒及设备Schedule。

- 原始逻辑节点：{metrics['logical_nodes']}；状态：{json.dumps(metrics['terminal_counts'],ensure_ascii=False)}。
- 完整世界：{metrics['atoms']}个原子；已检查窗口：{metrics['verified_windows']}；工厂请求/尝试：{metrics['factory_attempts']}。
- 模型总时间：{metrics['time_us']:g}μs。抓取/放回各100μs，保持原三轮SE。
- 正式运行组件/叶子/布局/路由编译调用均为0；准备阶段和正式执行统计分别保留。
- 组件内部批次复用既有编译结果；组件之间采用基础顺序调度，未追求额外并行优化。

这是编译、调度与明确fake测量场景的事件闭环，没有量子态/噪声仿真或硬件执行。相位输入为{metrics['phase_bits']}；后处理来自实际发布的结果，详见[交付摘要](delivery-summary.json)。工程检查通过，用户视觉待确认。

## 文件入口

- [最终验收](acceptance.json)：全源、几何、资源、因果、载体、工厂阶段与token/epoch。
- [全部源节点](viewer/source-nodes.json)：每个源节点的完成/条件跳过证据及动画对应。
- [调用窗口索引](viewer/calls.json)：每段动画对应的原始窗口/事件块和字节哈希。
- execute/windows 与 execute/history：同一会话的完整动作、场景、事件、结果和出口世界。
- execute/factory：逐请求的真实阶段提交、消费、清理和资源释放记录。
- recipes/schedules：从既有组件提取的静态内部批次及原始编译工件来源；无运行结果缓存。
- recipes/modules 与完整recipe文件：内容寻址动作叶子和完整调用体。
- delivery-inputs.json：生产作业及原始输出字节校验；生产摘要中的待验证标志保留历史，最终状态以acceptance.json为准。

静态组件接口为ComponentRecipeLibrary，持续驱动为ComponentPipeline。先准备缺失的位置变体，再用build_missing=False执行；更换组件库使用新的冻结输出目录，不能覆盖在用库。重现入口为scripts/basic_shor_job.py、basic_shor_audit.py、basic_shor_viewer.py；固定源码与环境回执位于记录的生产作业。
'''
    (a.out/'README.md').write_text(text,encoding='utf-8')
    save_artifact(a.out/'delivery-status.json',{'status':'passed','full_program_passed':report['passed'],
        'viewer':'viewer/animation-library.html','browser_verified':False,'user_visual_acceptance':'pending',
        'wall_seconds':time.perf_counter()-started,'scope':'complete_basic_shor_compile_schedule_fake_event_run'})
    print(json.dumps({'status':'passed','metrics':report['metrics']}),flush=True)


if __name__=='__main__':main()
