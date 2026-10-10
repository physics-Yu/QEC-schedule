"""Audit the completed guarded execution and project its existing actions."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT)]
from basic_shor_audit import audit_run,read
from basic_shor_viewer import export
from na_pipeline.runtime.compilation_guard import CompilationGuard,UnexpectedCompilation
from na_pipeline.runtime.pipeline import save_artifact


def file_hash(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--producer',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--verify-duration-repair',action='store_true')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    root=Path('/home/yyq/na-platform-simulation/R7/T704')
    if not a.producer.resolve().is_relative_to(root) or not a.run.resolve().is_relative_to(root):
        raise ValueError('GUARDED_DELIVERY_SCOPE')
    producer=read(a.producer/'scripts/outputs/T704/job/status.json')
    worker=read(a.producer/'scripts/outputs/T704/worker-receipt.json')
    if producer['status']!='completed' or worker.get('source_snapshot_stable') is not True:
        raise ValueError('FROZEN_PRODUCER_NOT_COMPLETE')
    if read(a.run/'status.json')['status']!='execution_complete_validation_pending':
        raise ValueError('COMPLETE_EXECUTION_REQUIRED')
    inputs=[a.run/'world.json.gz',a.run/'execution-stats.json',a.run/'active-attempt.json',a.run/'order-repair.json']
    inputs+=list((a.run/'execute').rglob('*'))+list((a.run/'stops').rglob('*'))
    inputs=sorted({p for p in inputs if p.is_file() and not p.name.endswith(('.tmp','.writing'))})
    manifest={p.relative_to(a.run).as_posix():{'sha256':file_hash(p),'bytes':p.stat().st_size} for p in inputs}
    save_artifact(a.out/'input-manifest.json',{'run_root':str(a.run),'producer':str(a.producer),'files':manifest,
        'producer_status':producer,'worker_receipt':worker,'physical_execution_repeated':False})
    # Account for every real attempt, including the interrupted prefix.
    before=read(a.run/'stops/order-miss-v5/execute/compiler-stats.json')
    repaired=read(a.run/'order-repair.json')['stats'];after=read(a.run/'execution-stats.json')
    counters=('leaf_compile_count','placement_search_count','routing_search_count','frontier_search_count')
    totals={k:sum(v['module_stats'][k] for v in (before,repaired,after)) for k in counters}
    if any(totals.values()):raise ValueError('GUARDED_ATTEMPT_COMPILED')
    guard=CompilationGuard(on_violation=lambda v:save_artifact(a.out/'validation-compilation-violation.json.gz',v))
    try:
        with guard:
            if a.verify_duration_repair:
                from check_window_duration_repair import check
                check(a.run,a.out)
            report=audit_run(a.run)
            for name,item in manifest.items():
                if file_hash(a.run/name)!=item['sha256']:raise ValueError('EXECUTION_INPUT_CHANGED: '+name)
            save_artifact(a.out/'acceptance.json',report)
            save_artifact(a.out/'delivery-status.json',{'status':'full_audit_passed_exporting','full_program_passed':report['passed']})
            export(a.run)
        for source in (a.run/'viewer').rglob('*'):
            if not source.is_file():continue
            target=a.out/'viewer'/source.relative_to(a.run/'viewer');target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if file_hash(target)!=file_hash(source):raise ValueError('VIEWER_DELIVERY_REDEFINED')
            else:
                try:os.link(source,target)
                except OSError:shutil.copyfile(source,target)
        summary={'schema_version':'GuardedShorDelivery/0.1','status':'passed','metrics':report['metrics'],
            'all_attempt_native_counters':totals,'execution_stats':after,'single_factory_compatibility_path':True,
            'fleet_full_production_accepted':False,'sampled':False,'quantum_state_simulated':False,'hardware_executed':False,
            'user_visual_acceptance':'pending','run_root':str(a.run),'producer_root':str(a.producer),
            'wall_seconds':time.perf_counter()-started}
        save_artifact(a.out/'delivery-summary.json',summary)
        save_artifact(a.out/'delivery-status.json',{'status':'passed','full_program_passed':True,
            'viewer':'viewer/animation-library.html','user_visual_acceptance':'pending','browser_verified':False})
        m=report['metrics']
        (a.out/'README.md').write_text(
            '# Shor-15 组件调用与原子运动\n\n'
            '打开 [动画窗口](viewer/animation-library.html)，查看同一连续会话的组件调用和设备占用。\n\n'
            f"原始 {m['logical_nodes']} 节点；{m['verified_windows']} 个窗口；{m['atoms']} 个原子；{m['factory_attempts']} 次工厂消费。\n\n"
            f"模型总时间 {m['time_us']:g} μs。完整运行、停止前缀和修复绑定中的原生编译/布局/路由/选批次调用均为 0。\n\n"
            '这是单工厂兼容路径的编译、调度与明确 fake 场景的事件验收；不代表量子态仿真、硬件执行或多工厂全流程已验收。用户视觉待确认。\n\n'
            '验收与输入哈希见 acceptance.json、input-manifest.json；详细统计见 delivery-summary.json。\n',encoding='utf-8')
        print(json.dumps({'status':'passed','metrics':m}),flush=True)
    except (Exception,UnexpectedCompilation) as exc:
        save_artifact(a.out/'delivery-status.json',{'status':'failed_incomplete','error':str(exc),
            'full_program_passed':False,'physical_recompilation_requested':False})
        raise
    finally:save_artifact(a.out/'validation-compilation-guard.json',guard.receipt())


if __name__=='__main__':main()
