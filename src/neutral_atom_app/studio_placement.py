"""Initial-placement comparison for the existing editable Atom Studio input."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
from math import ceil, floor
from pathlib import Path
from threading import Event, RLock, Thread
from time import perf_counter
from uuid import uuid4

from neutral_atom_env.domain.models import ZoneType, Position2D, GridCoord, StaticTrap
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.placement import CompilerSearchConfig
from .control import configured_strategy
from .placement_execution import optimize_free_layout
from .placement_workbench import record_trial


def search_options(raw=None):
    defaults=dict(enabled=True,proposal_pool=256,evaluations=16,workers=4,terminal_mode='stable',expand_storage=True)
    if raw is None:return defaults
    if not isinstance(raw,dict) or set(raw)-set(defaults):raise ValueError('Unknown placement search settings')
    defaults.update(raw)
    for key,maximum in [('proposal_pool',1024),('evaluations',64),('workers',8)]:
        if type(defaults[key]) is not int or not 1<=defaults[key]<=maximum:raise ValueError(f'{key} must be 1..{maximum}')
    if defaults['terminal_mode'] not in {'stable','fixed'}:raise ValueError('Unknown placement terminal mode')
    if type(defaults['expand_storage']) is not bool:raise ValueError('expand_storage must be boolean')
    if type(defaults['enabled']) is not bool:raise ValueError('enabled must be boolean')
    return defaults


def prepare(raw):
    from .visualization.workbench import build_inputs
    from .visualization.studio_config import configuration_issue
    value,circuit,platform,mapping=build_inputs(raw)
    if value.get('studio',{}).get('mode')!='custom' or value.get('qec_enabled'):
        raise ValueError('初态优化仅开放自定义物理线路；专用 QEC 协议不能自动替换初态。')
    if value['compiler'] not in {'ordered_greedy','smt_ordered','zoned_ids'} or platform.hardware.backend!='row_column_orthogonal':
        raise ValueError('请选择当前有序轴贪心或 SMT，以及有序行列正交后端。')
    if issue:=configuration_issue(value):raise ValueError(issue)
    options=search_options(value.get('placement_search'))
    if options['expand_storage']:
        # Explicit user option: prepare extra empty SLM sites within the existing
        # storage zone. Bounds, AOD, EZ, physical spacing and input atoms stay fixed.
        traps=dict(platform.world.traps)
        occupied={(t.position.x_um,t.position.y_um) for t in traps.values()}
        pitch=platform.world.grid_spacing_um
        for zone in platform.world.zones:
            if zone.zone_type!=ZoneType.STORAGE:continue
            b=zone.bounds
            for iy in range(ceil(b.lower.y_um/pitch),floor(b.upper.y_um/pitch)+1):
                for ix in range(ceil(b.lower.x_um/pitch),floor(b.upper.x_um/pitch)+1):
                    p=Position2D(ix*pitch,iy*pitch)
                    if (p.x_um,p.y_um) in occupied:continue
                    key=f'PLACE_{ix}_{iy}'
                    traps[key]=StaticTrap(key,GridCoord(ix,iy),p,enabled=False)
                    occupied.add((p.x_um,p.y_um))
        platform=replace(platform,world=replace(platform.world,traps=traps))
    return value,circuit,platform,mapping,options


def compare_studio(raw,directory,progress=None,cancelled=None):
    value,circuit,platform,mapping,options=prepare(raw)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/'input.json').write_text(canonical_json(value),encoding='utf-8')
    started=perf_counter()
    def report_trial(trial):
        if cancelled and cancelled.is_set():raise InterruptedError('用户取消；当前批次已结束，未开始下一批。')
        if progress:progress(dict(trial=trial.index+1,budget=options['evaluations'],valid=trial.evaluation.valid,
                                 time_us=trial.evaluation.total_time_us,failure=trial.evaluation.failure))
    compiler_options=dict(configured_strategy(value).options)
    # The outer experiment owns a shared terminal contract for every worker.
    compiler_options.pop('restore_layout',None)
    result=optimize_free_layout(circuit,platform,mapping,
        config=CompilerSearchConfig(max_evaluations=options['evaluations'],proposal_pool=options['proposal_pool'],
                                   seed=value['seed'],allow_vacancies=True),
        compiler_options=compiler_options,seed=value['seed'],
        workers=options['workers'],terminal_mode=options['terminal_mode'],
        output=directory/'search',on_trial=report_trial)
    if cancelled and cancelled.is_set():raise InterruptedError('用户取消。')
    report=dict(status='completed' if result.selected and result.baseline.evaluation.valid else 'failed',
        input=value,options=options,baseline=asdict(result.baseline),selected=asdict(result.selected) if result.selected else None,
        improvement_percent=result.improvement_percent,diagnostics=result.diagnostics,
        trials=[dict(index=t.index,origin=t.origin,valid=t.evaluation.valid,time_us=t.evaluation.total_time_us,
                     failure=t.evaluation.failure) for t in result.trials],recordings={},
        candidate_sites=[dict(id=t.id,x_um=t.position.x_um,y_um=t.position.y_um) for t in platform.world.traps.values()
            if any(z.zone_type==ZoneType.STORAGE and z.bounds.contains(t.position) for z in platform.world.zones)],
        contract='same edited circuit, AOD, compiler options and candidate domain; prepared initial state; assembly excluded')
    if report['status']=='completed':
        for name,trial in [('baseline',result.baseline),('optimized',result.selected)]:
            if progress:progress(dict(phase='recording',message='独立重放并生成'+name+'动画'))
            report['recordings'][name]=record_trial(directory/'search'/f'trial-{trial.index:04d}',directory/f'{name}.json')
    report['wall_seconds']=perf_counter()-started
    (directory/'comparison.json').write_text(canonical_json(report),encoding='utf-8')
    return report


class StudioPlacementJobs:
    """One study at a time. Cancellation drains the current bounded worker wave."""
    def __init__(self,output):
        self.output=Path(output);self.jobs={};self.lock=RLock()

    def start(self,raw):
        value,*_=prepare(raw)
        cache_value=dict(value)
        cache_value['placement_search']={k:v for k,v in search_options(value.get('placement_search')).items() if k!='enabled'}
        cache_key=sha256(canonical_json(cache_value).encode()).hexdigest()
        with self.lock:
            if any(j['status'] in {'running','cancelling'} for j in self.jobs.values()):
                raise ValueError('已有初态搜索运行中；取消需等待当前批次退出。')
            # Only completed studies from this server lifetime are cached. Never
            # reuse old-code artifacts, a failed baseline, or another contract.
            for previous in self.jobs.values():
                if previous['status']=='completed' and previous.get('cache_key')==cache_key:
                    previous['cache_hits']+=1
                    return previous['id']
            key=uuid4().hex
            job=dict(id=key,status='running',progress=dict(message='编译当前布局基线'),cancel=Event(),
                     cache_key=cache_key,cache_hits=0)
            self.jobs[key]=job
        def progress(p):
            with self.lock:job['progress']=p
        def work():
            try:
                result=compare_studio(value,self.output/key,progress,job['cancel'])
                with self.lock:job.update(status=result['status'],result=result)
            except Exception as error:
                status='cancelled' if isinstance(error,InterruptedError) else 'failed'
                with self.lock:job.update(status=status,error=str(error))
                folder=self.output/key;folder.mkdir(parents=True,exist_ok=True)
                (folder/'failure.json').write_text(canonical_json(dict(status=status,error=str(error))),encoding='utf-8')
        Thread(target=work,daemon=True).start()
        return key

    def get(self,key,result=False):
        with self.lock:
            job=self.jobs.get(key)
            if job:
                return job.get('result') if result else {k:v for k,v in job.items() if k not in {'cancel','result','cache_key'}}
        if result and len(key)==32 and all(c in '0123456789abcdef' for c in key):
            file=self.output/key/'comparison.json'
            if file.exists():return json.loads(file.read_text(encoding='utf-8'))

    def cancel(self,key):
        with self.lock:
            job=self.jobs.get(key)
            if job and job['status']=='running':job['cancel'].set();job['status']='cancelling'

    def close(self):
        for key in list(self.jobs):self.cancel(key)
