"""Canonical rotated Surface-17 coordinates as an explicit device profile.

Code coordinates are converted to device coordinates by a declared pitch and
translation; this is a structured placement baseline, not a search result.
"""
from .rigid_readout import rigid_readout_device
from .spec import validate_device


def canonical_surface17_device(*, measurement_x_range_um=(None, None), readout_capacity=None, transfer_us=100.):
    from na_pipeline.qec.surface17 import surface17_definition
    device = rigid_readout_device(x_range_um=measurement_x_range_um, readout_capacity=readout_capacity)
    from math import isfinite
    if type(transfer_us) not in (int, float) or not isfinite(transfer_us) or transfer_us <= 0:
        raise ValueError('transfer_us must be positive finite microseconds')
    device['artifact_id'] = 'device:surface17-canonical-rigid-v5:cz-aod-held:mz-x-'+('unbounded' if tuple(measurement_x_range_um)==(None,None) else 'bounded')+':readout-'+('unlimited' if readout_capacity is None else str(readout_capacity))+':transfer-'+str(float(transfer_us))
    for kind in ('pickup', 'drop'):
        device['timings_us'][kind] = float(transfer_us)
        device['parameter_provenance']['/timings_us/'+kind].update(
            source_refs=['T044-user-20261008:transfer-100us'] if transfer_us == 100 else ['T044:explicit-transfer-duration-override'],
            scope='Default 100 us from user instruction; explicit caller override otherwise. Per parallel batch, not per atom; not hardware calibration.')
    device['parameter_provenance']['/reset']['source_refs'].append('T044-user-20261008:reset-in-AOD')
    device['parameter_provenance']['/reset']['scope'] = 'In-place reset is allowed on stationary atoms in SLM or AOD in the declared zones; no carrier transfer required.'
    device['device_id'] = 'neutral-atom-canonical-surface17-engineering-reference'
    device['parameter_provenance']['/zones']['source_refs'].append('T044-user-20261007:measurement-all-x')
    device['parameter_provenance']['/zones']['scope'] += ' Measurement extends over all x by explicit user instruction; not a calibrated optical field of view.'
    definition = surface17_definition()
    coords = {f'd{i}': [i % 3, i // 3] for i in range(9)}
    coords.update({s['ancilla']: s['code_coordinate'] for s in definition['stabilizers']})
    slots = device['grouped_profile']['layouts']['patch_home']['slots']
    # 20 um data pitch gives every half-grid ancilla a site on the 10 um MZ grid.
    for name, xy in coords.items():
        p = [20. + 20. * v for v in xy]
        slots[name].update(position_um=p, row_id=f'r{round(p[1]/10)}', column_id=f'c{round(p[0]/10)}')
    device['grouped_profile']['provenance']['scope'] = 'Canonical code coordinates, 20 um data pitch; rigid readout uses actual captured shape. Uncalibrated engineering assumption.'
    geometry = device['patch_geometry']
    geometry.update(occupied_bounds_um=[10.,10.,70.,70.], cell_extent_um=[80.,80.], suggested_anchor_step_um=[80.,80.])
    geometry.update(schema_version='patch-geometry/0.2',
                    allowed_orientations=['x_vertical_z_horizontal', 'canonical_rot90'])
    geometry['provenance']['source_refs'].append('T044:initial-canonical-quarter-turn/1')
    geometry['provenance']['scope'] = 'Canonical rotated Surface-17 patch; fixed internal structure, caller-selected patch anchors. No optimization claim.'
    device["operations"]["action_kinds"].append("rebind")
    errors = validate_device(device)
    if errors:
        raise ValueError(errors)
    return device
