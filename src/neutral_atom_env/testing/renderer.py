"""Shared PNG/SVG primitives for reports, debug snapshots and failure overlays."""
import json
import textwrap
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch
from neutral_atom_env.domain.models import HolderType
from neutral_atom_env.replay.serializer import canonical_json
from .scene import build_scene, activity_color, gate_label
from .theme import VisualTheme


def _save(fig, path):
    fig.savefig(path, dpi=140, bbox_inches='tight', pad_inches=.3,
                metadata={'Date': None} if Path(path).suffix == '.svg' else {})
    plt.close(fig)


def render_layout(snapshot, path, theme=None, violation=None, show_aod=False, trails=(), show_labels=True):
    theme = theme or VisualTheme.load()
    scene = build_scene(snapshot)
    width = max(10, len(scene.grid_x)*.40)
    with plt.rc_context({'font.size':theme.font_size,'text.color':theme.text_color,
                         'svg.hashsalt':'neutral-atom-m0','font.family':'DejaVu Sans'}):
        fig,ax=plt.subplots(figsize=(width,max(8,1.25*width*(scene.bounds.upper.y_um-scene.bounds.lower.y_um)/
            (scene.bounds.upper.x_um-scene.bounds.lower.x_um))))
        fig.patch.set_facecolor(theme.background);ax.set_facecolor(theme.background)
        for i,z in enumerate(scene.zones):
            lo,hi=z.bounds.lower,z.bounds.upper
            color=theme.zone_colors[i%len(theme.zone_colors)]
            ax.add_patch(Rectangle((lo.x_um,lo.y_um),hi.x_um-lo.x_um,hi.y_um-lo.y_um,facecolor=color,zorder=0))
            # Outside zone: labels cannot obscure atoms on a boundary grid row.
            label_y=min(hi.y_um+scene.spacing_um*.35,scene.bounds.upper.y_um-scene.spacing_um*.35)
            ax.text(lo.x_um,label_y,z.id.upper(),fontsize=8,color=theme.muted_color)
        for x in scene.grid_x: ax.axvline(x,color=theme.grid_color,lw=theme.grid_line_width,zorder=1)
        for y in scene.grid_y: ax.axhline(y,color=theme.grid_color,lw=theme.grid_line_width,zorder=1)
        ax.scatter([p.x_um for p in scene.candidates],[p.y_um for p in scene.candidates],s=3,color=theme.muted_color,zorder=2)
        for trap in scene.traps:
            ax.scatter(trap.position.x_um,trap.position.y_um,s=theme.trap_size,
                facecolors='none',edgecolors=theme.muted_color,marker='o' if trap.enabled else 's',lw=1,zorder=3)
            if not trap.enabled:
                ax.scatter(trap.position.x_um,trap.position.y_um,marker='x',s=theme.atom_size,color=theme.failure_color,zorder=4)
        for atom in scene.atoms:
            if atom.position is None: continue
            p=atom.position
            color=activity_color(atom.activity,theme.colors())
            if atom.holder.holder_type==HolderType.MOBILE and not show_aod:
                ax.scatter(p.x_um,p.y_um,s=theme.trap_size,facecolors='none',edgecolors=theme.moving_color,marker='o',lw=1,zorder=3)
            ax.scatter(p.x_um,p.y_um,s=theme.atom_size,color=color,
                marker='D' if atom.holder.holder_type==HolderType.MOBILE else 'o',zorder=5)
            if show_labels:
                # Separate a close mobile/static gate pair without moving its geometry.
                offset=10 if atom.activity=='gating' and atom.holder.holder_type==HolderType.STATIC else -12
                ax.annotate(atom.id,(p.x_um,p.y_um),xytext=(0,offset),textcoords='offset points',ha='center',fontsize=theme.atom_label_size,zorder=6)
        if show_aod:
            from neutral_atom_env.replay.trajectory import axes_from_dict
            data=json.loads(snapshot);aod=data['aod'];axes=axes_from_dict(aod)
            # Each discrete AOD site is a ring, including currently empty sites.
            for row in range(aod['rows']):
                for column in range(aod['columns']):
                    ax.scatter(axes.x_um[column],axes.y_um[row],
                        s=theme.trap_size,facecolors='none',edgecolors=theme.moving_color,lw=1,zorder=4)
            runtime=data['active_plan']
            if runtime:
                incidental=runtime['plan']['incidental_atom_ids']
                for atom in scene.atoms:
                    if atom.id in incidental and atom.position:
                        ax.annotate('incidental',(atom.position.x_um,atom.position.y_um),xytext=(0,10),
                            textcoords='offset points',ha='center',fontsize=6,color=theme.muted_color)
            running=[n for n in data['dag'].values() if n['status']=='running']
            positions={a.id:a.position for a in scene.atoms}
            for node in running:
                if len(node['gate']['qubit_ids'])==2:
                    a,b=[positions[q] for q in node['gate']['qubit_ids']]
                    ax.plot([a.x_um,b.x_um],[a.y_um,b.y_um],color=theme.active_color,lw=1.5,zorder=5)
        for start,end in trails:
            ax.plot([start.x_um,end.x_um],[start.y_um,end.y_um],color=theme.moving_color,lw=1,alpha=.65,zorder=2)
        if violation:
            # The red mark and caption come exclusively from structured validator output.
            p=violation.position
            if p:
                x=min(max(p.x_um,scene.bounds.lower.x_um),scene.bounds.upper.x_um)
                y=min(max(p.y_um,scene.bounds.lower.y_um),scene.bounds.upper.y_um)
                ax.scatter(x,y,marker='x',s=100,color=theme.failure_color,zorder=8)
            for atom in scene.atoms:
                if atom.id in violation.atom_ids and atom.position:
                    ax.scatter(atom.position.x_um,atom.position.y_um,s=130,facecolors='none',edgecolors=theme.failure_color,zorder=7)
            caption=f'{violation.code} | atoms={", ".join(violation.atom_ids)} | holder={violation.holder_id} | position={p}'
            fig.text(.08,.01,'\n'.join(textwrap.wrap(caption,110)),color=theme.failure_color,fontsize=8)
        ax.set(xlim=(scene.bounds.lower.x_um,scene.bounds.upper.x_um),ylim=(scene.bounds.lower.y_um,scene.bounds.upper.y_um),
               xlabel='x / μm',ylabel='y / μm',aspect='equal')
        ax.tick_params(length=0,colors=theme.muted_color,labelsize=8)
        for spine in ax.spines.values():spine.set_visible(False)
        ax.set_title('PROCESSOR LAYOUT',loc='left',fontsize=12,pad=22)
        ax.text(0,-.14,f'{scene.spacing_um:g} μm grid · dots: allowed SLM sites · ring: enabled trap · crossed square: disabled\n'
            'Gray-blue ring: SLM trap · orange ring: AOD trap (same size)\n'
            'Circle: SLM atom · diamond: AOD atom\n'
            'Atom fill: indigo idle · orange moving · red gate / measure',transform=ax.transAxes,fontsize=8,color=theme.muted_color)
        fig.subplots_adjust(bottom=.22)
        _save(fig,path)


def render_dag(snapshot,path,theme=None):
    theme=theme or VisualTheme.load()
    data=json.loads(snapshot);nodes=data['dag'];levels={}
    pending=set(nodes)
    while pending:
        available=sorted(key for key in pending if all(p in levels for p,n in nodes.items() if key in n['successors']))
        if not available:raise ValueError('DAG contains a cycle')
        for key in available:
            parents=[p for p,n in nodes.items() if key in n['successors']]
            levels[key]=max((levels[p]+1 for p in parents),default=0)
            pending.remove(key)
    counts={};positions={}
    for key in sorted(nodes,key=lambda k:(levels[k],k)):
        level=levels[key];row=counts.get(level,0);counts[level]=row+1
        positions[key]=(level*3.6,-row*1.1)
    fig,ax=plt.subplots(figsize=(max(9,(max(levels.values(),default=0)+1)*3.6),max(3,max(counts.values(),default=1)*1.1)))
    fig.patch.set_facecolor(theme.background);ax.set_facecolor(theme.background)
    for key,node in nodes.items():
        x,y=positions[key]
        for child in node['successors']:
            xx,yy=positions[child];ax.annotate('',xy=(xx,yy+.3),xytext=(x+3.1,y+.3),arrowprops={'arrowstyle':'->','color':theme.muted_color,'lw':.8})
    for key,node in nodes.items():
        x,y=positions[key]
        color=theme.ready_color if node['status']=='ready' else theme.completed_color if node['status']=='completed' else theme.blocked_color
        ax.add_patch(FancyBboxPatch((x,y),3.1,.7,boxstyle='round,pad=.06',facecolor=color,edgecolor='none'))
        ax.text(x+.1,y+.43,f'{key} {gate_label(node)}',fontsize=9,color=theme.text_color)
        ax.text(x+.1,y+.12,f"{node['status'].upper()} · pending {node['remaining_predecessors']}",fontsize=8,color=theme.muted_color)
    ax.set(xlim=(-.2,max((x for x,y in positions.values()),default=0)+3.5),ylim=(-max(counts.values(),default=1)*1.1,1))
    ax.axis('off');_save(fig,path)


def write_scene(snapshot,path):
    Path(path).write_text(canonical_json(build_scene(snapshot)),encoding='utf-8')
