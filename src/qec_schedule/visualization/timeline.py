"""Resource custody and atom action timelines derived exclusively from a trace."""
from pathlib import Path
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Patch
from ..trace import validate_trace

COLORS = {'PICKUP': '#70a6b2', 'MOVE': '#3478cc', 'DROPOFF': '#70a6b2',
          'SINGLE_QUBIT': '#209987', 'ENTANGLE': '#d85067', 'MEASURE': '#e5a521',
          'PREPARE': '#9670b4', 'RESET': '#657d91'}

EPOCH_COLORS = {'AOD_MOVEMENT': '#3478cc', 'RYDBERG': '#d85067',
                'IMAGING': '#e5a521', 'LOCAL_1Q': '#209987',
                'PREPARE': '#9670b4', 'RESET': '#657d91'}


def _create_epoch_timeline(trace):
    fig = Figure(figsize=(15, 11), facecolor='#f7f9fc', layout='constrained')
    FigureCanvasAgg(fig)
    top, bottom = fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [1, 2.2]})
    resources = [resource for resource in trace['resource_capacities'] if resource.startswith('device/')]
    for index, resource in enumerate(resources):
        for span in trace['resource_spans']:
            if resource in span['resources']:
                top.broken_barh([(span['start_time'], span['end_time'] - span['start_time'])],
                                (index - .32, .64), facecolors='#3f7889', linewidth=0)
    top.set_yticks(range(len(resources)), [resource.removeprefix('device/').replace('_', ' ')
                                          for resource in resources])
    top.set_title('Epoch device custody · shared devices are acquired at epoch granularity',
                  loc='left', fontsize=11, pad=12)

    atoms = [atom['atom_id'] for atom in trace['initial_state']['atoms'] if atom.get('assigned_qubit')]
    for index, atom in enumerate(atoms):
        for epoch in trace['epochs']:
            if atom not in epoch['atoms']:
                continue
            bottom.broken_barh([(epoch['start_time'], epoch['end_time'] - epoch['start_time'])],
                               (index - .34, .68),
                               facecolors=EPOCH_COLORS.get(epoch['type'], '#8393a3'), linewidth=0)
            if epoch['end_time'] - epoch['start_time'] > trace['duration'] / 40:
                label = epoch['type'].replace('_', ' ')
                if epoch['type'] == 'AOD_MOVEMENT':
                    label += f" · {epoch['batch_size']} atoms"
                elif epoch['type'] == 'RYDBERG':
                    label += f" · {epoch.get('pair_count', 0)} pairs"
                bottom.text(epoch['start_time'] + .5, index, label, fontsize=6, color='white',
                            va='center', clip_on=True)
    bottom.set_yticks(range(len(atoms)), [atom.removeprefix('atom:') for atom in atoms])
    bottom.set_title('Atom participation · epoch bars are derived from the same execution trace',
                     loc='left', fontsize=11, pad=12)
    bottom.set_xlabel('Simulation time (μs)', labelpad=10)
    for ax in (top, bottom):
        ax.invert_yaxis()
        ax.set_xlim(0, trace['duration'] or 1)
        ax.set_facecolor('white')
        ax.grid(axis='x', color='#dce3eb', linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
        ax.tick_params(labelsize=9)
    fig.suptitle(f"QEC epoch timeline  |  {trace['duration']:,.2f} μs", fontsize=17, color='#243c54')
    fig.legend(handles=[Patch(color=color, label=kind.replace('_', ' ').title())
                        for kind, color in EPOCH_COLORS.items()],
               loc='upper center', bbox_to_anchor=(.5, -.01), ncol=3, frameon=False, fontsize=9)
    return fig


def create_timeline_figure(trace):
    validate_trace(trace)
    if trace.get('schema_version') == 2 and 'epochs' in trace:
        return _create_epoch_timeline(trace)
    fig = Figure(figsize=(15, 11), facecolor='#f7f9fc', layout='constrained')
    FigureCanvasAgg(fig)
    top, bottom = fig.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [1, 2.2]})
    resources = [r for r in trace['resource_capacities'] if r.startswith('device/')]
    for i, resource in enumerate(resources):
        for span in trace['resource_spans']:
            if resource in span['resources']:
                top.broken_barh([(span['start_time'], span['end_time'] - span['start_time'])],
                                (i - .32, .64), facecolors='#3f7889', linewidth=0)
    top.set_yticks(range(len(resources)), [r.removeprefix('device/').replace('_', ' ') for r in resources])
    top.set_title('Device custody · the AOD stays occupied through pickup, move and dropoff', loc='left', fontsize=11, pad=12)
    atoms = [a['atom_id'] for a in trace['initial_state']['atoms'] if a['assigned_qubit']]
    for i, atom in enumerate(atoms):
        for action in trace['actions']:
            if atom in action['atoms']:
                bottom.broken_barh([(action['start_time'], action['duration'])], (i - .34, .68),
                                   facecolors=COLORS[action['type']], linewidth=0)
    bottom.set_yticks(range(len(atoms)), [a.removeprefix('atom:') for a in atoms])
    bottom.set_title('Atom operations · blank intervals indicate idle or resource waiting', loc='left', fontsize=11, pad=12)
    bottom.set_xlabel('Simulation time (μs)', labelpad=10)
    for ax in (top, bottom):
        ax.invert_yaxis()
        ax.set_xlim(0, trace['duration'] or 1)
        ax.set_facecolor('white')
        ax.grid(axis='x', color='#dce3eb', linewidth=.6)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
        ax.tick_params(labelsize=9)
    fig.suptitle(f"QEC execution timeline  |  {trace['duration']:,.2f} μs", fontsize=17, color='#243c54')
    bottom.legend(handles=[Patch(color=c, label=k.replace('_', ' ').title()) for k, c in COLORS.items()],
                  loc='upper center', bbox_to_anchor=(.5, -.12), ncol=4, frameon=False, fontsize=9)
    return fig


def save_timeline(trace, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    create_timeline_figure(trace).savefig(path, dpi=160)
    return path
