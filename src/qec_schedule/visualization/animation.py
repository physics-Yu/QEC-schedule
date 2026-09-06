"""Standalone offline trace player; does not import or rerun the scheduler."""
import json
from pathlib import Path


def save_animation(trace, path):
    from ..trace import validate_trace
    validate_trace(trace)
    # Escape HTML delimiters even when a user-defined code supplies the identifiers.
    payload = json.dumps(trace, ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = Path(__file__).with_name('trace_player.html').read_text(encoding='utf-8')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html.replace('__TRACE_DATA__', payload), encoding='utf-8')
    return path


def create_matplotlib_animation(trace, *, frames=240, interval=40):
    """Matplotlib FuncAnimation adapter for notebooks or optional GIF export.

    The offline HTML player is the default because its seek/speed controls retain
    exact event times without pre-rendering thousands of raster frames.
    """
    from matplotlib.animation import FuncAnimation
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.patches import Rectangle
    from ..trace import frame_at, validate_trace
    validate_trace(trace)
    if type(frames) is not int or frames < 2:
        raise ValueError('At least two animation frames are required')
    fig = Figure(figsize=(8, 8), layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    bounds = [z['bounds'] for z in trace['initial_state']['zones']]
    for z in trace['initial_state']['zones']:
        x0, y0, x1, y1 = z['bounds']
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, facecolor='#edf3f8', edgecolor='#a3b6c8'))
        ax.text(x0 + 1, y0 + 3, {'STORAGE': 'Memory', 'ENTANGLING': 'Entanglement',
                                'MEASUREMENT': 'Measurement', 'RESERVOIR': 'Reservoir'}[z['kind']], fontsize=9)
    markers, labels = {}, {}
    for atom in trace['initial_state']['atoms']:
        kind, basis = atom['atom_type'], atom['syndrome_basis']
        marker, color = ('o', '#3478cc') if kind == 'DATA' else ('D', '#8693a2') if kind == 'RESERVOIR' else ('^', '#df8a20') if basis == 'X' else ('s', '#875abd')
        markers[atom['atom_id']], = ax.plot([], [], marker=marker, color=color, markersize=7, linestyle='none')
        labels[atom['atom_id']] = ax.text(0, 0, '', fontsize=8)
    lines = [ax.plot([], [], color='#dc4354', linewidth=2)[0] for _ in range(len(markers) // 2)]
    ax.set_xlim(min(b[0] for b in bounds) - 3, max(b[2] for b in bounds) + 3)
    ax.set_ylim(max(b[3] for b in bounds) + 3, min(b[1] for b in bounds) - 3)
    ax.set_aspect('equal')
    ax.set_xlabel('x (μm)')
    ax.set_ylabel('y (μm)')

    def update(time):
        frame = frame_at(trace, time)
        active = {atom: a for a in frame['active_actions'] for atom in a['atoms']}
        positions = {a['atom_id']: a['position'] for a in frame['atoms']}
        for atom in frame['atoms']:
            key, (x, y) = atom['atom_id'], atom['position']
            markers[key].set_data([x], [y])
            a = active.get(key)
            markers[key].set_markeredgecolor('#d85067' if a else 'white')
            markers[key].set_markeredgewidth(2 if a else .5)
            label = a['metadata'].get('gate', '') if a and a['type'] == 'SINGLE_QUBIT' else 'M' if a and a['type'] == 'MEASURE' else ''
            labels[key].set_position((x + 1, y - 1))
            labels[key].set_text(label or (atom['assigned_qubit'] or key).split(':')[-1])
        for line in lines:
            line.set_data([], [])
        for line, action in zip(lines, (a for a in frame['active_actions'] if a['type'] == 'ENTANGLE')):
            pair = [positions[k] for k in action['atoms']]
            line.set_data([p[0] for p in pair], [p[1] for p in pair])
        ax.set_title(f'QEC atom execution · {time:.2f} / {trace["duration"]:.2f} μs')
        return tuple(markers.values()) + tuple(labels.values()) + tuple(lines)

    times = [trace['duration'] * i / (frames - 1) for i in range(frames)]
    return FuncAnimation(fig, update, frames=times, init_func=lambda: update(0), interval=interval, blit=False)
