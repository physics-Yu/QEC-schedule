"""Explicit, opt-in Pauli approximation of timed exposure; units are microseconds.

No values here are hardware calibrations. Loss and amplitude damping are not
silently converted to Pauli errors. This module never mutates environment state.
"""
from dataclasses import dataclass, asdict
from math import exp, isfinite


def probability(value):
    if not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1:
        raise ValueError('Probability must be finite and between zero and one')
    return float(value)


@dataclass(frozen=True)
class Exposure:
    """One atom's disjoint interval, inserted after an identified native gate.

    The caller partitions the timeline; overlapping intervals for an atom fail.
    Gate calibration covers gate intervals; idle/move dephasing covers only their
    own intervals, preventing gate-duration coherence from being counted twice.
    """
    atom_id: str
    start_us: float
    end_us: float
    kind: str
    after_gate_id: str

    def __post_init__(self):
        if (not self.atom_id or not self.after_gate_id or self.kind not in {'idle', 'move'}
                or not all(isfinite(x) for x in (self.start_us, self.end_us))
                or self.start_us < 0 or self.end_us < self.start_us):
            raise ValueError('Invalid timed idle/move exposure')

    @property
    def duration_us(self):
        return self.end_us - self.start_us


@dataclass(frozen=True)
class PauliNoise:
    """Depolarizing probabilities are event probabilities, not gate infidelity.

    tphi_us describes pure Markovian dephasing ONLY. Do not substitute T2 without
    separating relaxation. All probabilities/rates require an explicit source.
    """
    source: str
    one_qubit: float = 0
    two_qubit: float = 0
    readout: float = 0
    reset: float = 0
    tphi_us: float | None = None
    move_depolarizing_rate_per_us: float = 0

    def __post_init__(self):
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError('Noise parameter source is required')
        for value in (self.one_qubit, self.two_qubit, self.readout, self.reset):
            probability(value)
        if self.tphi_us is not None and (not isfinite(self.tphi_us) or self.tphi_us <= 0):
            raise ValueError('Pure dephasing time must be positive microseconds')
        if not isfinite(self.move_depolarizing_rate_per_us) or self.move_depolarizing_rate_per_us < 0:
            raise ValueError('Move rate must be nonnegative inverse microseconds')

    def timed_channel(self, exposure):
        z = 0 if self.tphi_us is None else (1 - exp(-exposure.duration_us / self.tphi_us)) / 2
        dep = (1 - exp(-exposure.duration_us * self.move_depolarizing_rate_per_us)
               if exposure.kind == 'move' else 0)
        return {'z_error': z, 'depolarize1': dep}

    def to_dict(self):
        return dict(asdict(self), units={'time': 'us', 'move_rate': '1/us'},
                    model='independent Pauli approximation; no loss or amplitude damping')


def exposure_report(exposures, noise):
    intervals = {}
    for item in exposures:
        intervals.setdefault(item.atom_id, []).append(item)
    for items in intervals.values():
        ordered = sorted(items, key=lambda x: x.start_us)
        if any(a.end_us > b.start_us for a, b in zip(ordered, ordered[1:])):
            raise ValueError('Overlapping exposure intervals double-count an atom')
    return {'schema': 'qec-pauli-exposure/1', 'parameters': noise.to_dict(),
            'exposures': [dict(asdict(e), **noise.timed_channel(e)) for e in exposures]}


def require_loss_decoder(*args, **kwargs):
    raise NotImplementedError('Loss requires lifecycle-aware circuit rewriting and a decoder '
                              'conditioned only on observable loss information; not implemented')
