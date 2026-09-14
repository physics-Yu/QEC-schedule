"""Static acceptance figure from recorded inputs/intervals; no browser claims."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt


def main():
    root=Path('artifacts/m4-parallel')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    data=read(root/'recording.json');value=read(root/'input.json')
    rows=[]
    for name in ['m4-parallel','m4-parallel-resident','m4-parallel-returning','m4-greedy-fixed',
                 'm4-mixed-resident','m4-mixed-returning','m4-scale-32-fixed','m4-budget-failure']:
        directory=Path('artifacts')/name
        if not (directory/'result.json').exists():continue
        result=read(directory/'result.json');decisions=read(directory/'decisions.json')
        rows.append({'directory':name,'status':result['status'],'gates':result['metrics']['completed_gate_count'],
                     'wall_us':result['metrics']['episode_wall_time_us'],'load':result['metrics']['aod_load_count'],
                     'offload':result['metrics']['aod_offload_count'],'compile_and_execute_seconds':result['compile_seconds'],
                     'decisions':result['decisions'], 'legal_candidates':sum(len(d['candidates']) for d in decisions) if decisions else None,
                     'verified':(directory/'verification.json').exists()})
    Path('artifacts/m4-comparison.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    fig=plt.figure(figsize=(13,7),facecolor='#f3f6f3')
    gs=fig.add_gridspec(2,2,height_ratios=[1.25,1],hspace=.57,wspace=.32)
    circuit=fig.add_subplot(gs[0,0]);compare=fig.add_subplot(gs[0,1]);timeline=fig.add_subplot(gs[1,:])
    for ax in (circuit,compare,timeline):
        ax.set_facecolor('#ffffff');ax.spines[['top','right']].set_visible(False)
    fig.suptitle('M4 greedy acceptance | editable circuit to verified physical execution',x=.06,ha='left',fontsize=17,y=.98)
    for i in range(value['atom_count']):circuit.hlines(i,-.45,3.5,color='#b7c9be',linewidth=1)
    for gate in value['gates']:
        col=gate['column'];qs=[int(q[1:]) for q in gate['qubit_ids']]
        if len(qs)==2:circuit.plot([col,col],qs,color='#18785e',linewidth=2)
        for q in qs:circuit.text(col,q,gate['gate_type'],ha='center',va='center',fontsize=9,
            bbox={'boxstyle':'round,pad=.3','fc':'#e7f3ed' if len(qs)==2 else '#f0eaf7','ec':'#a7caba'})
    circuit.set(yticks=range(4),yticklabels=[f'Q{i:03d}' for i in range(4)],xticks=range(4),
                xticklabels=range(1,5),xlabel='Logical column (not physical time)',ylim=(3.55,-.55),xlim=(-.5,3.5))
    circuit.set_title('Input: 4 atoms / 8 gates / row layout',loc='left',fontsize=12,pad=12)
    labels=['M4 greedy','M3 resident','M3 returning'];dirs=['m4-parallel','m4-parallel-resident','m4-parallel-returning']
    metrics=[read(Path('artifacts')/d/'result.json')['metrics'] for d in dirs]
    values=[m['episode_wall_time_us'] for m in metrics]
    compare.barh(labels,values,color=['#18785e','#77978c','#b8c9c0'],height=.55)
    for i,(v,m) in enumerate(zip(values,metrics)):
        compare.text(v+45,i,f'{v:.2f} us | {m["aod_load_count"]} loads',va='center',fontsize=10)
    compare.invert_yaxis();compare.set_xlim(0,max(values)*1.42);compare.set_xlabel('Total time including the same exact terminal / us')
    compare.set_title('Same circuit, initial state and final holders',loc='left',fontsize=12,pad=12)
    slots=[o for o in data['operations'] if o['kind']=='raman_rotation' and o['gate_id'] in ['G001','G002','G003','G004']]
    left=min(o['start'] for o in slots)-.5;right=max(o['end'] for o in slots)+1
    for op in data['operations']:
        for lane,res in enumerate(['AOD_0','RAMAN_0']):
            if res in op['resources'] and op['end']>left and op['start']<right:
                start=max(left,op['start']);end=min(right,op['end'])
                label=op['kind'].removeprefix('aod_').upper() if lane==0 else op['gate_id']
                color=('#eab066' if op['kind']=='aod_move' else '#b8c9c0') if lane==0 else '#a287bc'
                timeline.barh(lane,end-start,left=start,height=.52,color=color,edgecolor='white')
                timeline.text((start+end)/2,lane,label,ha='center',va='center',fontsize=11)
    timeline.set(xlim=(left,right),yticks=[0,1],yticklabels=['AOD','Raman'],xlabel='Actual simulation time / us')
    timeline.invert_yaxis();timeline.set_title('Zoom: four consecutive 1 us pulses inside the unchanged transport window',loc='left',fontsize=12,pad=12)
    timeline.grid(axis='x',alpha=.18)
    fig.text(.06,.02,'Source: Executor recording. Static figure; browser rendering was not verified. Single-qubit pulse = 1 us; playback supports up to 32x.',fontsize=10,color='#667d76')
    fig.subplots_adjust(left=.10,right=.96,top=.88,bottom=.12)
    fig.savefig(root/'acceptance.png',dpi=145);plt.close(fig)


if __name__=='__main__':main()
