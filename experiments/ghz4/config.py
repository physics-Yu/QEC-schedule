"""GHZ experiment configuration helpers.

The experiment deliberately uses the repository's normal hardware config and
initial-state APIs.  The only experiment-specific piece here is the mapping of
each logical block to one storage zone, which keeps the four blocks visually
separate without putting hardware coordinates into the compiler.
"""
from qec_schedule.hardware import HardwareConfig, ZoneKind


def build_block_placements(code, config: HardwareConfig):
    """Return a qubit -> storage-site mapping for the four code blocks."""
    storage_zones = [zone for zone in config.zones if zone.kind == ZoneKind.STORAGE]
    if len(storage_zones) < len(code.block_ids):
        raise ValueError("GHZ4 config needs one storage zone per logical block")
    placements = {}
    for block_id, zone in zip(code.block_ids, storage_zones):
        qubits = code.block_qubits(block_id)
        if len(qubits) > zone.capacity or len(qubits) > len(zone.sites):
            raise ValueError(f"Storage zone {zone.id} cannot hold logical block {block_id}")
        placements.update({qubit: site.id for qubit, site in zip(qubits, zone.sites)})
    return placements


def logical_block_visualization(code, config):
    """Describe block outlines for trace consumers, not compiler placement."""
    storage_zones = [zone for zone in config.zones if zone.kind == ZoneKind.STORAGE]
    return [
        {
            "id": block_id,
            "label": f"{block_id} · d=3",
            "zone": zone.id,
            "bounds": zone.bounds.to_list(),
            "data_qubits": list(code.block_data(block_id)),
            "ancilla_qubits": list(code.block_ancilla(block_id)),
        }
        for block_id, zone in zip(code.block_ids, storage_zones)
    ]


def hardware_summary(config: HardwareConfig):
    """Serialize the relevant hardware profile in a compact, JSON-safe form."""
    return {
        "min_atom_separation": config.min_atom_separation,
        "reservoir_atoms": config.reservoir_atoms,
        "devices": dict(config.device_capacities),
        "timing": config.timing.to_dict(),
        "aod": config.aod.to_dict(),
        "zones": [zone.to_dict() for zone in config.zones],
    }
