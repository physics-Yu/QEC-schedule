"""Curated route evidence: shared axes, a dense carried array, alternative policy."""
from dataclasses import replace
from pathlib import Path
import json
from neutral_atom_env.domain.models import Atom,StaticTrap,GridCoord,Position2D,HolderRef,HolderType,Rectangle
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent
from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.simulation.row_column_factory import make_row_column_state
from neutral_atom_env.world import PlacementState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.motion.planners import HalfGridPlanner
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json
from .artifacts import page


def dense_transport_state():
    state=make_single_gate_state()
    sources=[Position2D(c*5,r*5) for r in range(4) for c in range(4)]
    positions=[sources[0],Position2D(5,-25),*sources[1:]]
    traps={f'S{i:03d}':StaticTrap(f'S{i:03d}',GridCoord(round(p.x_um/5),round(p.y_um/5)),p) for i,p in enumerate(positions)}
    # Empty but enabled traps are obstacles too. They lie beside the half-grid corridor.
    for i,p in enumerate((Position2D(0,-20),Position2D(10,-20))):
        traps[f'E{i}']=StaticTrap(f'E{i}',GridCoord(round(p.x_um/5),round(p.y_um/5)),p)
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(len(positions))}
    placement=PlacementState({q:HolderRef(HolderType.STATIC,f'S{i:03d}') for i,q in enumerate(atoms)})
    zones=(replace(state.world.zones[0],bounds=Rectangle(Position2D(-5,-5),Position2D(25,20))),*state.world.zones[1:])
    world=replace(state.world,traps=traps,zones=zones,bounds=Rectangle(Position2D(-5,-45),Position2D(30,20)))
    return replace(state,world=world,atoms=atoms,placement=placement,aod=replace(state.aod,rows=4,columns=4))


def plot_routes(payloads,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle,Rectangle as Box
    fig,axes=plt.subplots(1,len(payloads),figsize=(15,8),layout='constrained',facecolor='#f4f6fa')
    for ax,(title,data) in zip(axes,payloads):
        scene=data['scene'];plan=data['plans'][0];bounds=scene['bounds'];route=plan['paths']['Q000']
        ax.set_facecolor('#fafbfd')
        for z,col in zip(scene['zones'],('#edf4f5','#efedf8','#eaf4ef')):
            lo,hi=z['bounds']['lower'],z['bounds']['upper'];ax.add_patch(Box((lo['x_um'],lo['y_um']),hi['x_um']-lo['x_um'],hi['y_um']-lo['y_um'],color=col,zorder=0))
        for trap in scene['traps']:
            p=trap['position'];ax.add_patch(Circle((p['x_um'],p['y_um']),scene['slm_clearance_um'],facecolor='#8190a315',edgecolor='#8190a34a',lw=.8))
            ax.plot(p['x_um'],p['y_um'],'o',ms=4,mfc='none',mec='#8190a3')
        for atom,path_points in plan['paths'].items():
            if atom=='Q000':continue
            ax.plot([p['x_um'] for p in path_points],[p['y_um'] for p in path_points],color='#c28d4a',lw=.65,alpha=.3)
        xs=[p['x_um'] for p in route];ys=[p['y_um'] for p in route]
        ax.plot(xs,ys,'o--',color='#ba782f',lw=1.6,ms=4)
        for i,(x,y) in enumerate(zip(xs,ys)):ax.annotate(str(i),(x,y),xytext=((-14,-16) if i%2 else (7,6)),textcoords='offset points',color='#805623')
        for a in data['frames'][0]['atom_updates']:
            p=a['position'];ax.plot(p['x_um'],p['y_um'],'o',ms=3,color='#5364bc')
        ax.set(xlim=(bounds['lower']['x_um']-3,bounds['upper']['x_um']+3),ylim=(bounds['lower']['y_um']-3,bounds['upper']['y_um']+3),xlabel='x / μm',ylabel='y / μm',title=title)
        ax.set_xticks(scene['grid_x']);ax.set_yticks(scene['grid_y']);ax.grid(color='#dfe6ef',lw=.5);ax.set_axisbelow(True);ax.set_aspect('equal');ax.tick_params(labelsize=8)
        ax.spines[['right','top']].set_visible(False)
    fig.suptitle('Validated routes · Q000 highlighted / all carried atoms checked\nRings = enabled SLM exclusion (1 μm) · Numbers = outbound waypoints',fontsize=13,color='#25334b')
    fig.savefig(path,dpi=140);plt.close(fig)


def build_report(root='artifacts/motion-planner'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    cases=[('row_column',make_row_column_state('incidental'),HalfGridPlanner(),'相邻列伸缩 + 附带原子',64,174),
           ('dense_right',dense_transport_state(),HalfGridPlanner(),'16 原子 · 右侧通道',56,896),
           ('dense_left',dense_transport_state(),HalfGridPlanner(sides=(-1,),id='left-only'),'16 原子 · 替换 planner',66,1056)]
    cards=[];plots=[];results=[]
    for name,state,planner,title,aod_distance,atom_distance in cases:
        before=state.snapshot();recorder=VisualRecorder(state)
        plan=MotionCompiler(planner).compile(ExecuteGateBatchIntent({'G000'}),state)
        assert state.snapshot()==before
        executor=Executor(state);executor.submit(plan)
        while state.event_queue:recorder.observe(state,executor.step())
        m=state.metrics();assert m['total_aod_distance_um']==aod_distance and m['total_atom_distance_um']==atom_distance
        assert state.dag.completed and state.placement==type(state).restore(before).placement
        directory=root/name;recorder.write(directory/'animation.html');recorder.write_json(directory/'recording.json')
        (directory/'plan.json').write_text(canonical_json(plan),encoding='utf-8')
        (directory/'metrics.json').write_text(canonical_json(m),encoding='utf-8')
        state.trace.write(directory/'trace.jsonl')
        plots.append((name.replace('_',' ').title(),recorder.payload()))
        results.append({'scenario':name,'passed':True,'captured':len(plan.bindings),'aod_distance_um':aod_distance,'atom_distance_um':atom_distance})
        cards.append(f'<section class="card"><header><h2>{title}</h2><span class="badge">PASS</span></header><p style="padding:18px">{len(plan.bindings)} 颗携带原子；AOD 路程 {aod_distance} μm，原子总路程 {atom_distance} μm。<a href="{name}/animation.html">打开交互回放</a> · <a href="{name}/plan.json">查看实际计划</a></p></section>')
    plot_routes(plots,root/'routes.png')
    body='<h1>路径规划与物理验证</h1><p>上层选目标，planner 选途经点，backend 校验并计时，Executor 执行。右侧半格优先，边界受限时尝试左侧或水平连接通道；不保证全局最优或找到所有可行路线。</p><p>网格交点是候选位置；开启的实际 SLM trap 才参与此处避让。装卸仅允许接近各自源 trap。虚线为去程，原路返回；右上角可开关路线与避让区。</p><img style="width:100%;border-radius:16px" src="routes.png">'+''.join(cards)+'<p>证据来自实际 Executor 事件和全路径几何检查；不是光场仿真，也不代表真实浏览器视觉验收。</p>'
    (root/'index.html').write_text(page('Motion planner',body),encoding='utf-8')
    (root/'results.json').write_text(canonical_json(results),encoding='utf-8')
    return results
