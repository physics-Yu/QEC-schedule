"""Code-owned execution claims for admission before any atom expansion.

Claims describe an entire component call. They do not sample, compile, schedule,
or replace physical validation. An exclusive call never joins a parallel batch.
"""

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Literal

from nadit_physical_compiler.device import Region


@dataclass(frozen=True, slots=True)
class ComponentPhase:
    """One nonpreemptible object stage, with explicit resource lease boundaries.

    ``batch_key`` is a code-owned compatibility certificate, not a timing guess.
    Equal certificates permit one shared command only for equal stage records.
    Acquire/release retain a resource between stages, including readout holds.
    Times are microseconds. Results become available at exit plus latency.
    """

    name: str
    duration_us: float
    category: str
    resources: tuple[str, ...]
    batch_key: str | None = None
    acquire: tuple[str, ...] = ()
    release: tuple[str, ...] = ()
    results: int = 0
    latency_us: float = 0

    def __post_init__(self) -> None:
        _names((self.name,), "Phase")
        for name in ("resources", "acquire", "release"):
            _names(getattr(self, name), name)
        if self.batch_key is not None:
            _names((self.batch_key,), "Batch certificate")
        if (
            any(
                type(t) not in (int, float) or not isfinite(t) or t < 0
                for t in (self.duration_us, self.latency_us)
            )
            or type(self.results) is not int
            or self.results < 0
            or self.category
            not in {"gate", "transfer", "movement", "measurement", "reset", "other"}
            or not set((*self.acquire, *self.release)) <= set(self.resources)
        ):
            raise ValueError("INVALID_COMPONENT_PHASE")


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
    """One synchronized row trajectory and an exclusive column band.

    Peak counts describe one member. A group shares the row demand and sums
    columns/readout demands. Limits are actual Device capabilities; None means
    no explicit count bound, not unlimited geometry or independently moving rows.
    """

    aod_id: str
    row_trajectory_key: str
    column_min: float
    column_max: float
    peak_rows: int
    peak_columns: int
    max_rows: int | None
    max_columns: int | None
    readout_channel: str
    peak_readout_atoms: int
    max_readout_atoms: int | None
    min_spacing: float = 0

    def __post_init__(self) -> None:
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
                "Shared AOD bands require finite ordered coordinates "
                "and nonnegative spacing."
            )
        for peak, limit, minimum in (
            (self.peak_rows, self.max_rows, 1),
            (self.peak_columns, self.max_columns, 1),
            (self.peak_readout_atoms, self.max_readout_atoms, 0),
        ):
            if (
                type(peak) is not int
                or peak < minimum
                or (
                    limit is not None
                    and (type(limit) is not int or limit < max(1, peak))
                )
            ):
                raise ValueError(
                    "Shared AOD demand must fit positive limits; "
                    "only readout demand may be zero."
                )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-ready resource/capacity evidence."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ComponentExecutionSpec:
    """Immutable requirements for one bound component without atom actions.

    Matching nonempty waveform keys declare synchronous composition for ordered
    participant tuples, including multi-patch calls. Local parallel families may
    combine different addressed Pauli corrections with their original pulse times.
    Patches and closed space claims remain exclusive; one AOD may be shared only
    through an explicit row trajectory, column band and capacity claim. Result
    count reserves global identities and differs from peak readout demand.
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
        "object_wave",
        "exclusive",
    ]
    result_count: int
    shared_aod: SharedAODClaim | None = None

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
            "object_wave",
            "exclusive",
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
        if self.parallel_mode == "local_parallel" and (
            len(self.participant_blocks) != 1
            or self.result_count != 0
            or self.exclusive_resources
            or self.shared_aod is not None
        ):
            raise ValueError(
                "Local parallel calls require one patch, no results "
                "and no transport claims."
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
        }
