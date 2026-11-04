"""Explicit cost assumptions for a surface factory; no atom implementation.

The surrogate S is a logical operation with declared transversal physical cost.
It does not claim that applying physical S to every surface data atom realizes
logical S. Additional SE produces unobserved syndrome receipts; decoding and
waiting maintenance are outside this cost experiment.
"""

from dataclasses import dataclass, replace
from math import isfinite
from typing import Any, Literal

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.factory_recipe import ComponentCall, FactoryRecipe

from .definition import definition
from .fast_factory import factory_recipe


@dataclass(frozen=True)
class TransversalSAssumption:
    """Cost one simultaneous S pulse on each data atom under an explicit channel.

    Args:
        pauli_error: Independent X, Y, Z probabilities per data atom per pulse.
        duration_us: Positive common pulse duration, defaulting to 1 us.
    Raises:
        ValueError: Nonfinite/nonpositive timing or invalid Pauli probabilities.
    """

    pauli_error: tuple[float, float, float]
    duration_us: float = 1.0

    def __post_init__(self) -> None:
        if (
            type(self.duration_us) not in (float, int)
            or not isfinite(self.duration_us)
            or self.duration_us <= 0
            or not isinstance(self.pauli_error, tuple)
            or len(self.pauli_error) != 3
            or any(
                type(value) not in (float, int)
                or not isfinite(value)
                or value < 0
                or value > 1
                for value in self.pauli_error
            )
            or sum(self.pauli_error) > 1
        ):
            raise ValueError("INVALID_TRANSVERSAL_S_ASSUMPTION")
        object.__setattr__(self, "duration_us", float(self.duration_us))
        object.__setattr__(self, "pauli_error", tuple(map(float, self.pauli_error)))

    def to_dict(self) -> dict[str, Any]:
        """Return the complete model identity, including its physical boundary."""
        return {
            "schema": "nadit.assumed_transversal_s/1",
            "component_id": "assumed_transversal_s",
            "duration_us": self.duration_us,
            "physical_coverage": "all_data_atoms",
            "uses_aod": False,
            "noise": {
                "channel": "pauli",
                "scope": "independent_per_data_atom",
                "probabilities_xyz": list(self.pauli_error),
            },
            "physical_logical_implementation_verified": False,
            "output_logical_error_estimated": False,
        }

    @property
    def identity(self) -> str:
        """Hash timing, noise and scope together for lookup and provenance."""
        return canonical_hash(self.to_dict())


@dataclass(frozen=True)
class ECPolicy:
    """Declare preparation-only EC or independent rounds after every rotation.

    Args:
        mode: Preserve only embedded preparation/growth EC, or add rotation EC.
        rounds: Zero for preparation_only; positive count or distance otherwise.
    Raises:
        ValueError: Unknown cadence, invalid count, or contradictory options.
    """

    mode: Literal["preparation_only", "after_rotation"] = "preparation_only"
    rounds: int | Literal["distance"] = 0

    def __post_init__(self) -> None:
        valid_rounds = self.rounds == "distance" or (
            type(self.rounds) is int and self.rounds > 0
        )
        if (
            self.mode not in ("preparation_only", "after_rotation")
            or (
                self.mode == "preparation_only"
                and (type(self.rounds) is not int or self.rounds != 0)
            )
            or (self.mode == "after_rotation" and not valid_rounds)
        ):
            raise ValueError("INVALID_FACTORY_EC_POLICY")

    def resolved_rounds(self, distance: int) -> int:
        """Resolve the count using a checked odd-distance surface definition."""
        definition(distance)
        return distance if self.rounds == "distance" else self.rounds

    def to_dict(self, distance: int) -> dict[str, Any]:
        """Record additional cadence and preserved or omitted EC behavior."""
        return {
            "schema": "nadit.factory_ec_policy/1",
            "mode": self.mode,
            "rounds": self.rounds,
            "resolved_rounds": self.resolved_rounds(distance),
            "roles": "all_work_roles",
            "placement": "after_uncompute_before_next_raw_preparation",
            "preparation_and_growth_ec": "preserved",
            "waiting_maintenance": "omitted",
            "syndrome_interpretation": "unobserved_cost_only",
            "decoder_and_logical_correction": "omitted",
            "fault_tolerance_qualified": False,
        }


def assumed_factory_recipe(
    distance: int, *, s: TransversalSAssumption, ec: ECPolicy
) -> FactoryRecipe:
    """Replace S cost identity and append code-declared independent SE rounds.

    The 4+11 resource protocol, conditional S-before-uncompute ordering and
    final joint acceptance event remain unchanged. Every nonempty EC round
    exposes all work patches to the existing mandatory batching scheduler.
    """
    if not isinstance(s, TransversalSAssumption) or not isinstance(ec, ECPolicy):
        raise TypeError("EXPLICIT_FACTORY_ASSUMPTIONS_REQUIRED")
    base = factory_recipe(distance)
    rounds = ec.resolved_rounds(distance)
    identity = canonical_hash({"s": s.to_dict(), "ec": ec.to_dict(distance)})
    rotations = []
    for rotation in base.rotations:
        consumption = replace(
            rotation.consumption,
            branches=tuple(
                replace(
                    branch,
                    calls=tuple(
                        replace(
                            call,
                            component_id="assumed_transversal_s",
                            parameters=(("assumption_id", s.identity),),
                        )
                        if call.component_id == "logical_s"
                        else call
                        for call in branch.calls
                    ),
                )
                for branch in rotation.consumption.branches
            ),
        )
        rotations.append(
            replace(
                rotation,
                consumption=consumption,
                post_rotation_rounds=tuple(
                    tuple(
                        ComponentCall(
                            f"{rotation.key}/ec[{index}]/{role}",
                            "se_round",
                            (role,),
                        )
                        for role in base.work_roles
                    )
                    for index in range(rounds)
                ),
            )
        )
    return replace(
        base,
        protocol_id=f"{base.protocol_id}.assumed_s_ec.{identity}",
        version="1",
        rotations=tuple(rotations),
    )
