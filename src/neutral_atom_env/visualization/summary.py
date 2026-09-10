"""Bounded visual summaries. Device wall time and atom-time are different units."""
import json
import html
from pathlib import Path

CATEGORIES=(('load','装载','Load'),('transport','载原子运输','Loaded transport'),
            ('return','载原子回程','Loaded return'),('offload','卸载','Offload'),
            ('pulse','门脉冲','Gate pulse'),('empty','空载移动','Empty motion'),('idle','等待 / 空闲','Idle'))
COLORS=('#5364bc','#e89438','#d5aa64','#8190a3','#d95360','#bfc9d9','#e3e7ee')


def operation_category(record,pulse_seen):
    kind=record['operation_type']
    if kind in ('aod_load','aod_recapture'):return 'load'
    if kind in ('aod_offload','aod_park'):return 'offload'
    if kind=='entangling_pulse':return 'pulse'
    if kind=='aod_move':
        if not record.get('moving_atom_ids'):return 'empty'
        return 'return' if pulse_seen else 'transport'
    raise ValueError('Unsupported visual operation category: '+kind)


def movement_mode(record):
    if record['operation_type']!='aod_move':return None
    source=record.get('source_configuration');target=record.get('target_configuration')
    if source and target:
        for axis in ('x_um','y_um'):
            shifts=[b-a for a,b in zip(source[axis],target[axis])]
            if any(abs(v-shifts[0])>1e-8 for v in shifts):return 'axis_deformation'
    return 'translation'


def summarize_trace(trace,metrics=None):
    records=[json.loads(r) if isinstance(r,str) else r for r in trace]
    metrics=metrics or {}
    starts=[r['event']['time_us'] for r in records if r['event']['event_type']=='plan_started']
    start=metrics.get('episode_start_us')
    if start is None:start=min(starts,default=0.0)
    end=metrics.get('simulation_time_us',max((r['event']['time_us'] for r in records),default=start))
    operations=[];seen=set()
    for record in records:
        event=record['event'];plan=event.get('plan_id')
        if event['event_type']!='operation_started':continue
        category=operation_category(record,plan in seen)
        if category=='pulse':seen.add(plan)
        operations.append({'start':event['time_us'],'end':event['time_us']+record['duration_us'],
            'category':category,'moving_count':len(record.get('moving_atom_ids',())),
            'mode':movement_mode(record)})
    return summarize_intervals(operations,start,end,metrics)


def summarize_intervals(operations,start,end,metrics=None):
    """Intervals clipped to observed time; serial device occupancy, never summed per atom."""
    wall=max(0,end-start);totals={key:0.0 for key,_,_ in CATEGORIES}
    modes={};counts={key:0 for key in totals};atom_time=0.0;intervals=[];schedule=[]
    for op in operations:
        left=max(start,op['start']);right=min(end,op['end'])
        if right<=left:continue
        duration=right-left;key=op['category'];totals[key]+=duration;counts[key]+=1
        intervals.append((left,right))
        schedule.append({'start':left,'end':right,'category':key})
        if op.get('mode'):
            mode=modes.setdefault(op['mode'],{'duration_us':0.0,'segments':0,'atom_time_us':0.0})
            mode['duration_us']+=duration;mode['segments']+=1
            mode['atom_time_us']+=duration*op['moving_count']
            atom_time+=duration*op['moving_count']
    previous=start
    for left,right in sorted(intervals):
        if left<previous-1e-8:raise ValueError('Summary supports serial device intervals; overlapping operations require resource lanes')
        if left>previous:schedule.append({'start':previous,'end':left,'category':'idle'})
        previous=right
    if previous<end:schedule.append({'start':previous,'end':end,'category':'idle'})
    totals['idle']=max(0,wall-sum(totals.values()))
    return {'window_start_us':start,'window_end_us':end,'wall_time_us':wall,
        'categories':[{'key':key,'label':cn,'label_en':en,'duration_us':totals[key],
                       'fraction':totals[key]/wall if wall else 0,'segments':counts[key],'color':color}
                      for (key,cn,en),color in zip(CATEGORIES,COLORS)],
        'schedule':sorted(schedule,key=lambda op:op['start']),
        'movement_modes':modes,'transport_atom_time_us':atom_time,'metrics':metrics or {}}


def summary_html(summary):
    m=summary['metrics']
    fields=[('总耗时',summary['wall_time_us'],'μs'),('逻辑完成',m.get('logical_completion_elapsed_us'),'μs'),
            ('完成门数',m.get('completed_gate_count',0),''),('AOD 路程',m.get('total_aod_distance_um',0),'μm'),
            ('原子总路程',m.get('total_atom_distance_um',0),'μm'),('装载 / 卸载',f"{m.get('aod_load_count',0)} / {m.get('aod_offload_count',0)}",'次')]
    def fmt(v):return '未完成' if v is None else f'{v:.6g}' if isinstance(v,(int,float)) else str(v)
    cards=''.join(f'<div style="padding:14px;background:#f7f9fc;border-radius:10px"><small>{label}</small><div style="font-size:23px">{fmt(value)} <small>{unit}</small></div></div>' for label,value,unit in fields)
    rows=''.join(f'<tr><td>{r["label"]}</td><td>{r["duration_us"]:.6g} μs</td><td>{r["fraction"]:.2%}</td></tr>' for r in summary['categories'])
    modes='；'.join(f'{"整体平移" if mode=="translation" else "行列变形"}：{value["duration_us"]:.6g} μs，{value["segments"]} 段' for mode,value in summary['movement_modes'].items())
    return f'<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">{cards}</div><table style="width:100%;margin-top:18px;text-align:left"><thead><tr><th>时间占用</th><th>累计时间</th><th>总耗时占比</th></tr></thead><tbody>{rows}</tbody></table><p>{html.escape(modes)}</p><p class="muted">按设备时间统计；所有原子共享同一移动段，不按原子数重复计算。移动段承载原子时间（含静止交点）：{summary["transport_atom_time_us"]:.6g} atom·μs，单列且不参与耗时占比。</p>'


def render_summary(summary,path,theme):
    from matplotlib import pyplot as plt
    fig,ax=plt.subplots(figsize=(12,4.5));fig.patch.set_facecolor(theme.background);ax.set_facecolor(theme.background)
    rows=summary['categories'];wall=summary['wall_time_us']
    lanes={row['key']:i for i,row in enumerate(rows)}
    colors={row['key']:row['color'] for row in rows}
    for op in summary['schedule']:
        ax.barh(lanes[op['category']],op['end']-op['start'],left=op['start'],height=.55,color=colors[op['category']],edgecolor=theme.background,linewidth=.4)
        if op['category']=='pulse':
            ax.vlines(op['start'],lanes['pulse']-.35,lanes['pulse']+.35,color=colors['pulse'],linewidth=1.5)
    for i,row in enumerate(rows):
        ax.text(1.02,i,f"{row['duration_us']:.6g} us  |  {row['fraction']:.2%}",transform=ax.get_yaxis_transform(),va='center',fontsize=10,color=theme.text_color)
    ax.set_yticks(range(len(rows)),[r['label_en'] for r in rows]);ax.invert_yaxis()
    ax.set(xlabel='Simulation time / us',xlim=(summary['window_start_us'],summary['window_end_us'] if wall else summary['window_start_us']+1))
    ax.set_title(f"Operation schedule  |  total {wall:.6g} us",loc='left',pad=18,color=theme.text_color)
    ax.grid(axis='x',alpha=.15);ax.spines[['right','top']].set_visible(False)
    fig.subplots_adjust(left=.18,right=.80,bottom=.15,top=.85);fig.savefig(Path(path),dpi=140);plt.close(fig)
