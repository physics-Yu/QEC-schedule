"""Device-aware, bounded MZ targets for a fixed rigid Cartesian payload.

This policy chooses support positions; the injected realizer owns routing,
LOAD/MEASURE/RESET/return/OFFLOAD construction and complete physical validation.
Candidates preserve the existing device axes and never invent an MZ SLM site.
The nearest geometric projection is a proxy, not proof of an obstacle-free
route or a globally optimal readout service.
"""
from dataclasses import dataclass
from itertools import product
from math import hypot, isfinite
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, Position2D, ZoneType
from neutral_atom_env.hardware.multi_aod import backend_for, device, occupancy
from neutral_atom_strategies.scheduling.readout_placement import ReadoutTarget


@dataclass(frozen=True)
class RigidReadoutSelection:
    plan: object
    target: ReadoutTarget
    target_pose: Position2D


class RigidReadoutPlacementPolicy:
    """Propose nearby MZ poses, then rank complete legal services by actual cost.

    One request fixes static source carriers, the selected device, its full
    rigid offsets and an externally chosen capture origin. Foreign device
    occupants remain in the shared world; they are never hidden or relabelled.
    Only stationary AOD support is proposed. ``realizer(Position2D)`` must
    construct a fresh complete plan from the original state without committing
    or mutating that state, including on rejection.
    """

    def __init__(self, candidate_budget=16, top_k=3, *, deadline=None):
        if type(candidate_budget) is not int or not 1 <= candidate_budget <= 64:
            raise ValueError('Readout candidate budget must be 1..64')
        if type(top_k) is not int or not 1 <= top_k <= candidate_budget:
            raise ValueError('Readout top_k must be 1..candidate_budget')
        if deadline is not None and (not isinstance(deadline, (int, float)) or
                                     not isfinite(deadline)):
            raise ValueError('Deadline must be a finite perf_counter value or None')
        self.candidate_budget = candidate_budget
        self.top_k = top_k
        self.deadline = deadline
        self.log = []
        self.generation_rejections = {}

    @staticmethod
    def _source(state, atoms, aod_id, origin):
        atoms = tuple(atoms)
        if not atoms or len(set(atoms)) != len(atoms):
            raise ValueError('Distinct nonempty readout atom IDs are required')
        if state.hardware.backend != 'rigid':
            raise ValidationError('GRAPH_BACKEND_UNSUPPORTED',
                                  'Rigid MZ placement preserves all existing row and column offsets')
        aod = device(state, aod_id)
        if (aod.is_moving or aod_id in state.transfers or occupancy(state, aod_id) or
                any(q not in state.atoms or not state.atoms[q].alive or
                    state.placement.atom_to_holder[q].holder_type != HolderType.STATIC
                    for q in atoms)):
            raise ValidationError('READOUT_POLICY_START',
                                  'MZ target selection requires static source carriers and this device idle and empty')
        points = {q: state.placement.position(q, state.world, state.aods) for q in atoms}
        if any(not state.slm_enabled[state.placement.atom_to_holder[q].holder_id] for q in atoms):
            raise ValidationError('READOUT_POLICY_START', 'Every source carrier needs enabled SLM support')
        if origin is None:
            origin = Position2D(min(p.x_um for p in points.values()),
                                min(p.y_um for p in points.values()))
        if not isinstance(origin, Position2D):
            raise TypeError('origin must be a Position2D')
        axes = aod.configuration()
        xs = tuple(x - aod.pose.x_um for x in axes.x_um)
        ys = tuple(y - aod.pose.y_um for y in axes.y_um)
        tolerance = state.hardware.alignment_tolerance_um
        offsets = {}
        for q, point in points.items():
            dx, dy = point.x_um - origin.x_um, point.y_um - origin.y_um
            x = min(xs, key=lambda value: abs(dx - value))
            y = min(ys, key=lambda value: abs(dy - value))
            if abs(dx - x) > tolerance or abs(dy - y) > tolerance:
                raise ValidationError('RIGID_MZ_SOURCE_EMBEDDING',
                                      'Source carriers must embed in the configured rigid axes at the capture origin')
            # After LOAD the actual carrier coordinates are the selected AOD
            # cell coordinates, including any permitted alignment tolerance.
            offsets[q] = (x, y)
        return atoms, aod, origin, offsets, xs, ys

    def candidates(self, state, atoms, *, aod_id='AOD_0', origin=None):
        """Return ReadoutTargets ordered by source-to-target geometric distance.

        Only actual carrier offsets must fit the same MZ rectangle. Complete
        capacity axes, including disabled spares, must fit world and envelope.
        No physical route is compiled here and no support mask is switched.
        """
        self.generation_rejections = {}
        atoms, aod, origin, offsets, xs, ys = self._source(state, atoms, aod_id, origin)
        bounds = state.world.bounds
        left, bottom = bounds.lower.x_um - min(xs), bounds.lower.y_um - min(ys)
        right, top = bounds.upper.x_um - max(xs), bounds.upper.y_um - max(ys)
        if aod.envelope is not None:
            envelope = aod.envelope
            if not bounds.contains(envelope.lower) or not bounds.contains(envelope.upper):
                raise ValidationError('AOD_ENVELOPE_REQUIRED', 'A device envelope must be contained in world bounds')
            left = max(left, envelope.lower.x_um - min(xs))
            right = min(right, envelope.upper.x_um - max(xs))
            bottom = max(bottom, envelope.lower.y_um - min(ys))
            top = min(top, envelope.upper.y_um - max(ys))
        if not (left <= origin.x_um <= right and bottom <= origin.y_um <= top):
            code = 'AOD_ENVELOPE_EXCEEDED' if aod.envelope is not None else 'AOD_OUTSIDE_WORLD'
            raise ValidationError(code, 'The full source capture footprint must fit the world and device envelope')
        backend = backend_for(state, aod_id)
        backend.validate_pose(state, origin)
        source_aod = backend.target_aod(aod, origin)
        empty_us = backend.move_duration(aod, origin, state.hardware)
        min_x = min(dx for dx, _ in offsets.values())
        max_x = max(dx for dx, _ in offsets.values())
        min_y = min(dy for _, dy in offsets.values())
        max_y = max(dy for _, dy in offsets.values())
        targets = {}
        zones = tuple(z for z in state.world.zones if z.zone_type == ZoneType.MEASUREMENT)
        if not zones:
            self.generation_rejections['NO_MEASUREMENT_ZONE'] = 1
        for zone in zones:
            rect = zone.bounds
            lo_x = max(left, rect.lower.x_um - min_x)
            hi_x = min(right, rect.upper.x_um - max_x)
            lo_y = max(bottom, rect.lower.y_um - min_y)
            hi_y = min(top, rect.upper.y_um - max_y)
            if lo_x > hi_x or lo_y > hi_y:
                code = 'MZ_PAYLOAD_DOES_NOT_FIT'
                self.generation_rejections[code] = self.generation_rejections.get(code, 0) + 1
                continue
            def clamp(value, low, high):
                return max(low, min(high, value))
            nearest_x = clamp(origin.x_um, lo_x, hi_x)
            nearest_y = clamp(origin.y_um, lo_y, hi_y)
            for ox, oy in product((0., -2.5, 2.5, -5., 5.), repeat=2):
                x = clamp(nearest_x + ox, lo_x, hi_x)
                y = clamp(nearest_y + oy, lo_y, hi_y)
                pose = Position2D(x, y)
                key = (x, y)
                positions = tuple(sorted((q, (x + dx, y + dy))
                                         for q, (dx, dy) in offsets.items()))
                # The proxy uses this device's actual backend timing model;
                # readout/reset cost is omitted because it is common to targets.
                direct_us = backend.move_duration(source_aod, pose, state.hardware)
                proxy_us = (empty_us + 2 * direct_us + state.hardware.load_duration_us +
                            state.hardware.offload_duration_us)
                features = {
                    'aod_id': aod_id,
                    'zone_id': zone.id,
                    'target_pose_um': [x, y],
                    'source_origin_um': [origin.x_um, origin.y_um],
                    'proxy_distance_um': hypot(x - origin.x_um, y - origin.y_um),
                    'empty_position_estimate_us': empty_us,
                    'estimated_transfer_us': state.hardware.load_duration_us + state.hardware.offload_duration_us,
                    'estimated_motion_us': 2 * direct_us,
                    'effect_cost_in_proxy': False,
                    'feasibility_claim': False,
                    'feasible_origin_bounds_um': [lo_x, lo_y, hi_x, hi_y],
                    'geometric_nearest_pose_um': [nearest_x, nearest_y],
                    'complete_axis_span_um': [max(xs) - min(xs), max(ys) - min(ys)],
                    'loaded_offset_bounds_um': [min_x, min_y, max_x, max_y],
                }
                candidate = ReadoutTarget('aod', positions, (), proxy_us, features)
                previous = targets.get(key)
                if previous is None or zone.id < previous.features['zone_id']:
                    targets[key] = candidate
        return tuple(sorted(targets.values(), key=lambda target: (
            target.features['proxy_distance_um'], target.estimated_us,
            tuple(target.features['target_pose_um']), target.features['zone_id'])))

    def choose(self, state, atoms, realizer, *, aod_id='AOD_0', origin=None):
        """Choose among bounded, independently realized complete service plans.

        The caller's realizer validates all spectators, capture intersections,
        moves, supports, MZ effects and original-source restoration. A geometric
        candidate is never accepted merely because its endpoint fits a zone.
        """
        if not callable(realizer):
            raise TypeError('realizer must accept a target Position2D and return a complete legal plan')
        atoms = tuple(atoms)
        _, _, origin, _, _, _ = self._source(state, atoms, aod_id, origin)
        candidates = self.candidates(state, atoms, aod_id=aod_id, origin=origin)
        entry_log = {
            'schema': 'rigid-readout-placement-decision/1',
            'aod_id': aod_id,
            'atom_ids': list(atoms),
            'source_origin_um': [origin.x_um, origin.y_um],
            'support': 'aod',
            'generated': len(candidates),
            'generation_rejections': dict(self.generation_rejections),
            'candidate_budget': self.candidate_budget,
            'top_k': self.top_k,
            'candidates': [],
            'selected': None,
            'optimality_claim': False,
            'selection_scope': 'bounded legal complete services ranked by actual duration and distance',
        }
        self.log.append(entry_log)
        best = None
        accepted = 0
        for target in candidates[:self.candidate_budget]:
            pose = Position2D(*target.features['target_pose_um'])
            entry = {
                'support': target.support,
                'positions': target.positions,
                'zone_id': target.features['zone_id'],
                'aod_id': aod_id,
                'target_pose_um': list(target.features['target_pose_um']),
                'proxy_distance_um': target.features['proxy_distance_um'],
                'estimated_us': target.estimated_us,
                'features': dict(target.features),
            }
            entry_log['candidates'].append(entry)
            if self.deadline is not None and perf_counter() > self.deadline:
                entry.update(status='timeout')
                entry_log['budget_exhausted'] = True
                if best is None:
                    raise TimeoutError('Readout target selection deadline')
                break
            try:
                plan = realizer(pose)
                actual_us = plan.estimated_duration_us
                actual_distance = plan.estimated_distance_um
                if (not isfinite(actual_us) or actual_us <= 0 or
                        not isfinite(actual_distance) or actual_distance < 0):
                    raise ValidationError('READOUT_REALIZER_COST',
                                          'A complete legal readout service needs finite positive duration and nonnegative distance')
            except ValidationError as error:
                entry.update(status='rejected', code=error.violation.code, message=str(error))
                continue
            except TimeoutError:
                entry.update(status='timeout')
                entry_log['budget_exhausted'] = True
                if best is None:
                    raise
                break
            entry.update(status='accepted', actual_us=actual_us, actual_distance_um=actual_distance)
            key = (actual_us, actual_distance, target.features['proxy_distance_um'],
                   pose.x_um, pose.y_um, target.features['zone_id'])
            if best is None or key < best[0]:
                best = (key, RigidReadoutSelection(plan, target, pose), entry)
            accepted += 1
            if accepted >= self.top_k:
                break
        if best is None:
            raise ValidationError('READOUT_TARGETS_EXHAUSTED',
                                  f'No legal readout service among {len(entry_log["candidates"])} checked targets; '
                                  'not proof of continuous-space infeasibility')
        entry_log['selected'] = best[2]
        entry_log['accepted'] = accepted
        return best[1]
