"""Static physical layout drawn ONLY from a validated hardware snapshot."""
from pathlib import Path

from ..hardware.atom import AtomState, AtomType
from ..hardware.hardware_state import HardwareState


def create_layout_figure(state: HardwareState):
    # Lazy optional dependency. No pyplot, GUI backend, or QEC compiler access.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Rectangle

    state.validate()
    if not state.zones:
        raise ValueError("Layout rendering requires at least one zone")
    figure = Figure(figsize=(12, 11), facecolor="#f8fafc")
    FigureCanvasAgg(figure)
    ax = figure.add_axes((0.07, 0.14, 0.9, 0.72))
    ax.set_facecolor("#f8fafc")
    colors = {"STORAGE": "#eaf2fe", "ENTANGLING": "#fff3df", "MEASUREMENT": "#e5f5ee", "RESERVOIR": "#edf0f4"}
    occupied = {atom.site_id for atom in state.atoms if atom.site_id is not None}
    for zone in state.zones:
        bounds = zone.bounds
        ax.add_patch(Rectangle((bounds.xmin, bounds.ymin), bounds.xmax - bounds.xmin, bounds.ymax - bounds.ymin,
                               facecolor=colors[zone.kind.value], edgecolor="#99a6b5", linewidth=1.2, zorder=0))
        count = len(state.atoms_in_zone(zone.id))
        name = {"STORAGE": "Memory", "ENTANGLING": "Entanglement"}.get(zone.kind.value, zone.kind.value.title())
        title = f"{name}  |  {count}/{zone.capacity} atoms"
        if zone.kind.value.lower() != zone.id.lower():
            title += f"  [{zone.id}]"
        if zone.entangling_geometry is not None or zone.measurement_geometry is not None:
            title += "  | dynamic working region"
        ax.text(bounds.xmin + 1.5, bounds.ymin + 2.5, title, fontsize=10, weight="bold", color="#253449")
        sites = {s.id: s for s in zone.sites}
        # Dynamic zones are intentionally rendered as capabilities, not as a
        # collection of predeclared destinations. Storage/reservoir sites are
        # still shown because those zones retain discrete trap semantics.
        if zone.entangling_geometry is None and zone.measurement_geometry is None:
            for site in zone.sites:
                if site.id not in occupied:
                    ax.scatter(site.position.x, site.position.y, s=60, facecolors="none", edgecolors="#94a3b8", linewidths=1, zorder=2)
                    ax.annotate(site.id, (site.position.x, site.position.y), xytext=(0, -14), textcoords="offset points",
                                ha="center", fontsize=7, color="#64748b")
        if zone.entangling_geometry is not None:
            geometry = zone.entangling_geometry
            lanes = geometry.interaction_lanes or ((geometry.bounds.ymin + geometry.bounds.ymax) / 2,)
            for lane in lanes:
                if geometry.preferred_axis == "x":
                    ax.plot((geometry.bounds.xmin, geometry.bounds.xmax), (lane, lane),
                            color="#d49a3a", linestyle=":", linewidth=1.0, zorder=1)
                else:
                    ax.plot((lane, lane), (geometry.bounds.ymin, geometry.bounds.ymax),
                            color="#d49a3a", linestyle=":", linewidth=1.0, zorder=1)
        if zone.measurement_geometry is not None:
            field = zone.measurement_geometry.field_of_view
            ax.plot((field.xmin, field.xmax, field.xmax, field.xmin, field.xmin),
                    (field.ymin, field.ymin, field.ymax, field.ymax, field.ymin),
                    color="#3d9a6c", linestyle=":", linewidth=1.0, zorder=1)

    styles = {"DATA": ("#2563eb", "o", "Data"), "X": ("#d97706", "^", "X ancilla"),
              "Z": ("#7c3aed", "s", "Z ancilla"), "OTHER": ("#0d9488", "p", "Other ancilla"),
              "RESERVOIR": ("#64748b", "D", "Reservoir")}
    used_styles = set()
    for atom in state.atoms:
        if atom.state == AtomState.LOST:
            continue
        key = atom.atom_type.value
        if atom.atom_type == AtomType.ANCILLA:
            key = atom.syndrome_basis if atom.syndrome_basis in ("X", "Z") else "OTHER"
        color, marker, _ = styles[key]
        used_styles.add(key)
        ax.scatter(atom.position.x, atom.position.y, s=110, c=color, marker=marker,
                   edgecolors="white", linewidths=0.9, zorder=4)
        # Include block ID so multiple blocks do not have ambiguous labels.
        label = atom.assigned_qubit if atom.assigned_qubit is not None else atom.atom_id
        ax.annotate(label, (atom.position.x, atom.position.y), xytext=(0, -14), textcoords="offset points",
                    ha="center", fontsize=7.5, color="#27364b", zorder=5)

    xmin, xmax = min(z.bounds.xmin for z in state.zones), max(z.bounds.xmax for z in state.zones)
    ymin, ymax = min(z.bounds.ymin for z in state.zones), max(z.bounds.ymax for z in state.zones)
    live = [a for a in state.atoms if a.state != AtomState.LOST]
    xmin, xmax = min([xmin] + [a.position.x for a in live]), max([xmax] + [a.position.x for a in live])
    ymin, ymax = min([ymin] + [a.position.y for a in live]), max([ymax] + [a.position.y for a in live])
    ax.set_xlim(xmin - 3, xmax + 3)
    ax.set_ylim(ymax + 3, ymin - 3)  # Diagram convention: y grows downward.
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("x (um)", color="#475569")
    ax.set_ylabel("y (um; increases downward)", color="#475569")
    ax.tick_params(colors="#64748b", labelsize=8)
    for spine in ax.spines.values():
        spine.set_visible(False)
    figure.text(0.075, 0.945, "Neutral-atom hardware layout", fontsize=22, weight="bold", color="#172b46")
    figure.text(0.075, 0.904, f"Static snapshot  /  t = {state.current_time:g} us  /  {len(live)} present atoms  /  {len(state.qubit_to_atom)} mapped qubits",
                fontsize=11, color="#526176")
    handles = [Line2D([], [], marker=marker, linestyle="none", color=color, markersize=8, label=label)
               for key, (color, marker, label) in styles.items() if key in used_styles]
    handles.append(Line2D([], [], marker="o", linestyle="none", color="#94a3b8", markerfacecolor="none", label="Empty trap"))
    figure.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 0.04), ncol=len(handles), frameon=False, fontsize=10)
    figure.text(0.5, 0.018, "Illustrative geometry. Working-region lanes and imaging FOV are capabilities; placement is runtime-managed.",
                ha="center", fontsize=9, color="#64748b")
    return figure


def save_layout(state: HardwareState, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure = create_layout_figure(state)
    figure.savefig(path, dpi=180, facecolor=figure.get_facecolor())
    return path
