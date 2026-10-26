"""Code-owned execution claims for admission before any atom expansion.

Claims describe an entire component call. They do not sample, compile, schedule,
or replace physical validation. An exclusive call never joins a parallel batch.
"""

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Literal

from nadit_physical_compiler.device import Region


def _names(values: tuple[str, ...], label: str, *, nonempty: bool = False) -> None:
    if (
        not isinstance(values, tuple)
        or (nonempty and not values)
        or any(not isinstance(value, str) or not value.strip() for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{label} must contain distinct nonempty identities.")


@dataclass(frozen=True, slots=True)
class SpaceClaim:
    """An exclusive closed absolute-coordinate envelope and its declared use."""

    region: Region
    purpose: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.region, Region)
            or not isinstance(self.purpose, str)
            or not self.purpose.strip()
        ):
            raise ValueError("Space claims require a Region and a nonempty purpose.")

    def to_dict(self) -> dict[str, Any]:
        """Return independent JSON-ready evidence."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SharedAODClaim:
    """Shared AOD proposal using a band proof or an exact joint-trace family.

    Peak counts describe one member. A group shares the row demand and sums
    columns/readout demands. Limits are actual Device capabilities; None means
    no explicit count bound, not unlimited geometry or independently moving rows.
    A joint_family/member pair instead requires complete-group trace admission
    by the execution owner. Its peak demands may be None until that trace is
    loaded; this is deferred demand, not zero usage. Legacy band claims retain
    their original requirements and serialization.
    A nonempty joint_code_ids explicitly permits those concrete codes within
    this exact family. Every group member must declare the same set; admission
    still requires a complete joint trace. Empty retains same-code admission.
    """

    aod_id: str
    row_trajectory_key: str
    column_min: float
    column_max: float
    peak_rows: int | None
    peak_columns: int | None
    max_rows: int | None
    max_columns: int | None
    readout_channel: str
    peak_readout_atoms: int | None
    max_readout_atoms: int | None
    min_spacing: float = 0
    joint_family: str | None = None
    joint_member: str | None = None
    joint_code_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _names(self.joint_code_ids, "Joint codes")
        if self.joint_code_ids and self.joint_family is None:
            raise ValueError("Joint code sets require an exact joint family.")
        if (self.joint_family is None) != (self.joint_member is None):
            raise ValueError(
                "Joint AOD claims require both family and member identities."
            )
        if self.joint_family is not None:
            assert self.joint_member is not None
            _names((self.joint_family,), "Joint AOD family")
            _names((self.joint_member,), "Joint AOD member")
        for name in ("aod_id", "row_trajectory_key", "readout_channel"):
            _names((getattr(self, name),), name)
        if (
            any(
                type(value) not in (int, float) or not isfinite(value)
                for value in (self.column_min, self.column_max, self.min_spacing)
            )
            or self.column_min > self.column_max
            or self.min_spacing < 0
        ):
            raise ValueError(
                "Shared AOD bands require finite ordered coordinates and nonnegative spacing."
            )
        for peak, limit, minimum in (
            (self.peak_rows, self.max_rows, 1),
            (self.peak_columns, self.max_columns, 1),
            (self.peak_readout_atoms, self.max_readout_atoms, 0),
        ):
            if peak is None and self.joint_family is not None:
                if limit is not None and (type(limit) is not int or limit < 1):
                    raise ValueError(
                        "Joint resource limits must be positive or unbounded."
                    )
                continue
            if (
                type(peak) is not int
                or peak < minimum
                or (
                    limit is not None
                    and (type(limit) is not int or limit < max(1, peak))
                )
            ):
                raise ValueError(
                    "Shared AOD demand must fit positive limits; only readout demand may be zero."
                )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready resource/capacity evidence."""
        result = asdict(self)
        if self.joint_family is None:
            result.pop("joint_family")
            result.pop("joint_member")
        if self.joint_code_ids:
            result["joint_code_ids"] = sorted(self.joint_code_ids)
        else:
            result.pop("joint_code_ids")
        return result

    def band_peaks(self) -> tuple[int, int, int]:
        """Require concrete legacy band demands; joint claims need group execution."""
        if self.joint_family is not None or any(
            value is None
            for value in (self.peak_rows, self.peak_columns, self.peak_readout_atoms)
        ):
            raise ValueError("JOINT_AOD_CLAIM_REQUIRES_GROUP_EXECUTION")
        assert self.peak_rows is not None and self.peak_columns is not None
        assert self.peak_readout_atoms is not None
        return self.peak_rows, self.peak_columns, self.peak_readout_atoms


@dataclass(frozen=True, slots=True)
class ComponentExecutionSpec:
    """Immutable requirements for one bound component without atom actions.

    Matching nonempty waveform keys declare synchronous composition for ordered
    participant tuples, including multi-patch calls. Local parallel families may
    combine different addressed Pauli corrections with their original pulse times.
    Patches and closed space claims remain exclusive; one AOD may be shared only
    through an explicit row trajectory, column band and capacity claim. Result
    count reserves global identities and differs from peak readout demand.

    profile_parallel is estimation-only: disjoint resource reservations may
    overlap with different durations. Physical execution rejects that mode; it
    is not evidence of jointly executable atom trajectories.
    An estimate_batch_key further restricts this mode to one declared model
    family and requires complete-group cost lookup with synchronized phases.
    """

    code_id: str
    component_id: str
    waveform_key: str | None
    participant_blocks: tuple[str, ...]
    spaces: tuple[SpaceClaim, ...]
    exclusive_resources: tuple[str, ...]
    parallel_mode: Literal[
        "independent_aods_lockstep",
        "shared_aod_lockstep",
        "local_parallel",
        "exclusive",
        "profile_parallel",
    ]
    result_count: int
    shared_aod: SharedAODClaim | None = None
    estimate_batch_key: str | None = None

    def __post_init__(self) -> None:
        _names((self.code_id,), "Code")
        _names((self.component_id,), "Component")
        _names(self.participant_blocks, "Participants", nonempty=True)
        _names(self.exclusive_resources, "Resources")
        if not isinstance(self.spaces, tuple) or any(
            not isinstance(space, SpaceClaim) for space in self.spaces
        ):
            raise ValueError("Spaces must be an immutable tuple of SpaceClaim records.")
        if self.parallel_mode not in (
            "independent_aods_lockstep",
            "shared_aod_lockstep",
            "local_parallel",
            "exclusive",
            "profile_parallel",
        ):
            raise ValueError("Unsupported component parallel mode.")
        if self.waveform_key is not None and (
            not isinstance(self.waveform_key, str) or not self.waveform_key.strip()
        ):
            raise ValueError("Waveform identity must be nonempty or None.")
        if self.parallel_mode != "exclusive" and self.waveform_key is None:
            raise ValueError("Lockstep calls require an explicit waveform identity.")
        if type(self.result_count) is not int or self.result_count < 0:
            raise ValueError("Result count must be a nonnegative integer.")
        if self.estimate_batch_key is not None:
            if (
                not isinstance(self.estimate_batch_key, str)
                or not self.estimate_batch_key.strip()
            ):
                raise ValueError("Estimate batch identity must be nonempty text.")
            if self.parallel_mode != "profile_parallel":
                raise ValueError("Estimate batch identity requires profile_parallel.")
        if self.parallel_mode == "local_parallel" and (
            len(self.participant_blocks) != 1
            or self.result_count != 0
            or self.exclusive_resources
            or self.shared_aod is not None
        ):
            raise ValueError(
                "Local parallel calls require one patch, no results and no transport claims."
            )
        if self.parallel_mode == "shared_aod_lockstep":
            if not isinstance(self.shared_aod, SharedAODClaim):
                raise ValueError(
                    "Shared AOD execution requires a typed shared resource claim."
                )
            if f"aod:{self.shared_aod.aod_id}" in self.exclusive_resources:
                raise ValueError(
                    "One AOD cannot be both shared and exclusive in a call."
                )
        elif self.shared_aod is not None:
            raise ValueError("Only shared AOD mode may carry a shared resource claim.")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready public declarations without action internals."""
        return {
            "code_id": self.code_id,
            "component_id": self.component_id,
            "waveform_key": self.waveform_key,
            "participant_blocks": list(self.participant_blocks),
            "spaces": [space.to_dict() for space in self.spaces],
            "exclusive_resources": list(self.exclusive_resources),
            "parallel_mode": self.parallel_mode,
            "result_count": self.result_count,
            "shared_aod": self.shared_aod.to_dict()
            if self.shared_aod is not None
            else None,
            **(
                {"estimate_batch_key": self.estimate_batch_key}
                if self.estimate_batch_key is not None
                else {}
            ),
        }
