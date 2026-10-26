"""Bridge factory calls to real d3 components and code-owned probability ports.

This adapter owns no world, clock, result allocator, random generator, retry
policy, or quantum truth. Caches contain immutable templates and event models.
All execution context and selected coarse events are supplied by the caller.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from math import isclose, isfinite
from typing import Any, Protocol

import numpy as np
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.provenance import canonical_hash

from ..._support.atom_template import AtomComponentTemplate, BindingRejected
from ..._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from ...contracts.component import (
    ComponentBinding,
    ComponentExpansion,
    InvocationContext,
)
from ...contracts.event_probability import ProbabilityPort
from ...contracts.parallel import ComponentExecutionSpec
from ..components import get_component
from ..components.canonicalization import (
    CompiledPreparationCorrections,
    CorrectionApplication,
    CorrectionDecision,
    PreparationCanonicalization,
    PreparationExpansion,
)
from ..components.transversal import TransversalCNOTComponent, TransversalCNOTTemplate
from ..definition import REFERENCE_COORDINATES, REFERENCE_HOMES
from ..probabilities.factory import factory_mx_port
from ..probabilities.factory import output_quality as factory_output_quality
from ..probabilities.factory import preparation_quality as resource_preparation_quality
from ..probabilities.preparation import preparation_port
from ..probabilities.raw_t_preparation import raw_t_preparation_port
from ..probabilities.t_injection import t_injection_port
from .parallel import (
    describe_execution,
    local_reference_device,
    pair_reference_device,
    pair_reference_origins,
    reference_origin,
)
from .raw_t_postselection import (
    RawTPostselection,
    RawTPostselectionExpansion,
    RawTPostselectionTemplate,
)

_SITE_PITCH_UM = 10
_PREFIX = "rotated_surface_d3/"
type FactoryExpansion = (
    ComponentExpansion | RawTPostselectionExpansion | CorrectionApplication
)


def _normal_raw_source(source: RawTPostselectionExpansion) -> None:
    """Exclude historical controls and old protocol records from factory use."""
    if source.version != RAW_T_PROTOCOL_VERSION or source.round_policy != "distance":
        raise ValueError(
            "Factory raw-T use requires the current distance round policy."
        )
    resolve_postselection_rounds(3, len(source.parts) - 1)


def _normal_raw_port(port: ProbabilityPort) -> None:
    """Require the complete current d3 temporal identity before cached correction."""
    parameters = port.to_dict()["model"]["parameters"]
    if port.protocol_version != RAW_T_PROTOCOL_VERSION or any(
        parameters.get(key) != value
        for key, value in {
            "distance": 3,
            "extra_rounds": 2,
            "total_rounds": 3,
            "round_policy": "distance",
        }.items()
    ):
        raise ValueError(
            "Factory raw-T probability port has an old or different round policy."
        )


class _Expander(Protocol):
    def expand(self, context: InvocationContext) -> FactoryExpansion: ...


@dataclass(frozen=True)
class BoundFactoryCall:
    """A bound real expander with the exact caller-reserved result range length.

    Raw preparation retains its original multi-round expansion. Canonicalization
    returns CorrectionApplication, including its decision and original results.
    No result identities or physical bit values are allocated by this wrapper.
    """

    expander: _Expander
    result_count: int
    device: Device

    def expand(self, context: InvocationContext) -> FactoryExpansion:
        """Expand in the caller's current complete world on this backend's Device."""
        if context.device != self.device:
            raise ValueError("Bound factory call requires the backend's Device.")
        return self.expander.expand(context)


@dataclass(frozen=True)
class _BoundCorrection:
    compiled: CompiledPreparationCorrections
    source: PreparationExpansion
    decision: CorrectionDecision

    def expand(self, context: InvocationContext) -> CorrectionApplication:
        return self.compiled.expand_after(self.source, self.decision, context)


@dataclass(frozen=True)
class _BoundJointCall:
    """Use the control's transport resource without changing patch defaults."""

    expander: _Expander
    participants: tuple[ComponentBinding, ...]

    def expand(self, context: InvocationContext) -> ComponentExpansion:
        output = self.expander.expand(context)
        if not isinstance(output, ComponentExpansion):
            raise TypeError("Joint call requires a component expansion.")
        return replace(
            output,
            participant_bindings=self.participants,
            exit_participant_bindings=self.participants,
        )


def _name(component_id: str) -> str:
    if not isinstance(component_id, str) or not component_id:
        raise ValueError("Component identity must be a nonempty string.")
    component_id = component_id.removeprefix(_PREFIX)
    if not component_id or "/" in component_id:
        raise ValueError("Factory backend only supplies rotated_surface_d3 components.")
    return component_id


def _parameters(values: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    if not isinstance(values, tuple) or any(
        not isinstance(item, tuple) or len(item) != 2 or not isinstance(item[0], str)
        for item in values
    ):
        raise ValueError("Call parameters must be a tuple of named pairs.")
    result = dict(values)
    if len(result) != len(values):
        raise ValueError("Call parameters repeat a name.")
    return result


def _allowed(parameters: Mapping[str, Any], names: set[str]) -> None:
    extra = parameters.keys() - names
    if extra:
        raise ValueError(f"Unsupported parameters: {sorted(map(str, extra))}.")


def _preparation(source: PreparationExpansion) -> str:
    if isinstance(source, RawTPostselectionExpansion):
        return "raw_t_postselection"
    return source.description.component_id


@dataclass(frozen=True)
class SurfaceFactoryBackend:
    """Compile and cache immutable templates for one concrete physical Device.

    Bindings use the approved d3 reference spacing and orientation. Explicit
    site_ids retain the existing template-key semantics and are never discarded.
    Changing Device requires another backend, not a hidden reconfiguration.
    """

    device: Device
    _single: dict[tuple[Any, ...], AtomComponentTemplate] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _raw: dict[tuple[Any, ...], RawTPostselectionTemplate] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _cnot: dict[tuple[Any, ...], TransversalCNOTTemplate] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _corrections: dict[tuple[Any, ...], CompiledPreparationCorrections] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _preparation_events: dict[tuple[str, str], ProbabilityPort] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def _homes(self, binding: ComponentBinding) -> tuple[str, ...]:
        """Resolve the reference roles at actual coordinates before compiling."""
        if not isinstance(binding, ComponentBinding) or len(binding.atom_ids) != 17:
            raise BindingRejected("Factory participants require a 17-atom binding.")
        if len(dict(binding.site_ids)) != len(binding.site_ids):
            raise BindingRejected("Repeated explicit site-binding key.")
        explicit = dict(binding.site_ids)
        result = []
        for reference, (x, y) in zip(
            REFERENCE_HOMES, REFERENCE_COORDINATES, strict=True
        ):
            matches = [
                site.id
                for site in self.device.slm_sites
                if isclose(
                    site.position.x,
                    binding.origin.x + _SITE_PITCH_UM * x,
                    rel_tol=0,
                    abs_tol=1e-9,
                )
                and isclose(
                    site.position.y,
                    binding.origin.y + _SITE_PITCH_UM * y,
                    rel_tol=0,
                    abs_tol=1e-9,
                )
            ]
            if len(matches) > 1:
                preferred = explicit.get(reference)
                matches = (
                    [preferred]
                    if preferred in matches
                    else [site for site in matches if site in explicit.values()]
                )
            if len(matches) != 1:
                raise BindingRejected(
                    f"Role home {reference!r} requires one actual SLM site."
                )
            result.append(matches[0])
        return tuple(result)

    def describe_execution(
        self,
        component_id: str,
        participant_bindings: tuple[ComponentBinding, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> ComponentExecutionSpec:
        """Return pure code-owned claims before binding, compiling or expanding."""
        if isinstance(component_id, str) and component_id.endswith("/canonicalize"):
            preparation = _name(component_id.removesuffix("/canonicalize"))
            PreparationCanonicalization(preparation)
            name = preparation + "/canonicalize"
        else:
            name = _name(component_id)
        values = _parameters(parameters)
        count = 2 if name == "transversal_cnot" else 1
        if (
            not isinstance(participant_bindings, tuple)
            or len(participant_bindings) != count
        ):
            raise ValueError(f"{name} requires exactly {count} participant bindings.")
        _allowed(values, {"extra_rounds"} if name == "raw_t_postselection" else set())
        blocks: set[str] = set()
        atoms: set[int] = set()
        for binding in participant_bindings:
            self._homes(binding)
            self.device.aod(binding.aod_id)
            if (
                not binding.block_id
                or binding.block_id in blocks
                or len(set(binding.atom_ids)) != 17
                or atoms.intersection(binding.atom_ids)
                or any(type(atom) is not int or atom < 0 for atom in binding.atom_ids)
            ):
                raise BindingRejected(
                    "Participants require disjoint patch and atom identities."
                )
            blocks.add(binding.block_id)
            atoms.update(binding.atom_ids)
        return describe_execution(self.device, name, participant_bindings, values)

    def bind_call(
        self,
        component_id: str,
        participant_bindings: tuple[ComponentBinding, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> BoundFactoryCall:
        """Bind a single component, two-block CNOT, or full raw-T preparation.

        ``extra_rounds`` is the only component parameter and applies only to
        raw_t_postselection. Unknown parameters and participant counts raise
        ValueError. Expanding still validates the complete supplied world.
        """
        name, values = _name(component_id), _parameters(parameters)
        count = 2 if name == "transversal_cnot" else 1
        if (
            not isinstance(participant_bindings, tuple)
            or len(participant_bindings) != count
        ):
            raise ValueError(f"{name} requires exactly {count} participant bindings.")
        _allowed(values, {"extra_rounds"} if name == "raw_t_postselection" else set())
        homes = tuple(self._homes(binding) for binding in participant_bindings)
        first = participant_bindings[0]
        key: tuple[Any, ...] = (
            name,
            homes,
            tuple(p.origin for p in participant_bindings),
            first.aod_id,
        )
        spec = self.describe_execution(name, participant_bindings, parameters)
        if name == "transversal_cnot":
            second = participant_bindings[1]
            compilation_device = self.device
            control_origin, target_origin = first.origin, second.origin
            if spec.parallel_mode == "shared_aod_lockstep":
                control_origin, target_origin = pair_reference_origins(
                    self.device, first, second
                )
                homes = tuple(
                    self._homes(replace(binding, origin=origin, site_ids=()))
                    for binding, origin in zip(
                        participant_bindings,
                        (control_origin, target_origin),
                        strict=True,
                    )
                )
                compilation_device = pair_reference_device(
                    self.device, first.aod_id, control_origin, target_origin
                )
                key = (name, "canonical_pair_profile", spec.waveform_key)
            if key not in self._cnot:
                self._cnot[key] = TransversalCNOTComponent().compile(
                    compilation_device,
                    control_home_sites=homes[0],
                    target_home_sites=homes[1],
                    control_origin=control_origin,
                    target_origin=target_origin,
                    aod_id=first.aod_id,
                )
            joint = self._cnot[key].bind(first, replace(second, aod_id=first.aod_id))
            return BoundFactoryCall(
                _BoundJointCall(joint, participant_bindings), 0, self.device
            )
        compilation_device = self.device
        if spec.parallel_mode in (
            "independent_aods_lockstep",
            "shared_aod_lockstep",
            "local_parallel",
        ):
            origin = reference_origin(self.device)
            assert origin is not None
            reference = replace(first, origin=origin, site_ids=())
            homes = (self._homes(reference),)
            key = (name, "canonical_local_profile", spec.waveform_key)
            compilation_device = local_reference_device(self.device, first.aod_id)
        else:
            reference = first
        if name == "raw_t_postselection":
            protocol = RawTPostselection(values.get("extra_rounds"))
            key += (
                RAW_T_PROTOCOL_VERSION,
                protocol.round_policy,
                protocol.extra_rounds,
            )
            if key not in self._raw:
                self._raw[key] = protocol.compile(
                    compilation_device,
                    home_sites=homes[0],
                    origin=reference.origin,
                    aod_id=reference.aod_id,
                )
            return BoundFactoryCall(
                self._raw[key].bind(first), 8 * (1 + protocol.extra_rounds), self.device
            )
        if key not in self._single:
            self._single[key] = get_component(name).compile(
                compilation_device,
                home_sites=homes[0],
                origin=reference.origin,
                aod_id=reference.aod_id,
            )
        template = self._single[key]
        return BoundFactoryCall(
            template.bind(first), len(template.description.measurements), self.device
        )

    def bind_canonicalization(
        self,
        preparation: str,
        source: PreparationExpansion,
        decision: CorrectionDecision,
        probability_port: ProbabilityPort,
    ) -> BoundFactoryCall:
        """Bind selected local preparation corrections without allocating results.

        The supplied source and coarse decision are kept in this one bound call,
        never in the backend cache. Readiness and provenance are checked during
        expand; it returns CorrectionApplication with the original source bits.
        """
        name = _name(preparation)
        if name == "raw_t_postselection":
            if not isinstance(source, RawTPostselectionExpansion):
                raise ValueError(
                    "Raw correction requires the complete repeated-SE protocol."
                )
            _normal_raw_source(source)
            _normal_raw_port(probability_port)
        binding = source.exit_binding
        if binding is None:
            raise ValueError(
                "Canonicalization source requires an explicit exit binding."
            )
        homes = self._homes(binding)
        key: tuple[Any, ...] = (
            name,
            homes,
            binding.origin,
            binding.aod_id,
            probability_port.content_sha256,
        )
        if key not in self._corrections:
            self._corrections[key] = PreparationCanonicalization(name).compile(
                self.device,
                probability_port=probability_port,
                home_sites=homes,
                origin=binding.origin,
                aod_id=binding.aod_id,
            )
        return BoundFactoryCall(
            _BoundCorrection(self._corrections[key], source, decision), 0, self.device
        )

    def canonicalize(
        self,
        source: PreparationExpansion,
        decision: CorrectionDecision,
        context: InvocationContext,
        probability_port: ProbabilityPort,
    ) -> CorrectionApplication:
        """Bind and expand one local correction after the true source exit."""
        result = self.bind_canonicalization(
            _preparation(source), source, decision, probability_port
        ).expand(context)
        assert isinstance(result, CorrectionApplication)
        return result

    def correction_decision(
        self,
        source: PreparationExpansion,
        *,
        event_id: str,
        probability_port: ProbabilityPort,
        values: Mapping[str, object],
        available_at_us: float,
    ) -> CorrectionDecision:
        """Build the code-specific decision from an opaque preparation and event.

        The logical compiler need not know the raw multi-round structure or d3
        byproduct-class encoding. Unknown fields, invalid class/acceptance types,
        or a port for a different preparation raise ValueError. The subsequent
        canonicalization checks possibility, readiness and known physical bits.
        """
        if not isinstance(values, Mapping) or set(values) != {
            "accepted",
            "byproduct_class",
        }:
            raise ValueError(
                "Preparation decision requires only accepted and byproduct_class."
            )
        if probability_port.protocol_id != f"rotated_surface_d3.{_preparation(source)}":
            raise ValueError("Probability port describes a different preparation.")
        accepted, value = values["accepted"], values["byproduct_class"]
        if type(accepted) is not bool or (value is not None and type(value) is not int):
            raise ValueError(
                "Preparation decision requires Boolean acceptance "
                "and integer/null class."
            )
        first = (
            source.parts[0]
            if isinstance(source, RawTPostselectionExpansion)
            else source
        )
        return CorrectionDecision(
            first.invocation_id,
            event_id,
            probability_port.content_sha256,
            value,
            accepted,
            available_at_us,
        )

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Resolve declared probability semantics; never ignore history or quality.

        Preparation ports currently use ideal joint acceptance/byproduct events
        and exactly three raw SE rounds. T consumption permits an explicit density
        or phase-flip input_z_error. Factory MX permits iid input_z_error only.
        Unknown selectors or parameters raise ValueError instead of silently
        replacing a requested model with an ideal or fixture distribution.
        """
        if not isinstance(selector, str):
            raise ValueError("Event selector must be a string.")  # noqa: TRY004 - public validation contract
        if parameters is not None and (
            not isinstance(parameters, Mapping)
            or any(not isinstance(k, str) for k in parameters)
        ):
            raise ValueError("Event parameters must be a string-keyed mapping.")
        values = dict(parameters or {})
        if selector.startswith("preparation:"):
            name = selector[len("preparation:") :]
            _allowed(
                values, {"extra_rounds"} if name == "raw_t_postselection" else set()
            )
            if name == "raw_t_postselection":
                extra = resolve_postselection_rounds(3, values.get("extra_rounds"))
                return preparation_port(name, extra_rounds=extra)
            return preparation_port(name)
        if selector == "factory_mx":
            _allowed(values, {"input_z_error"})
            return factory_mx_port(**values)
        if selector == "t_consumption":
            _allowed(values, {"data_density", "magic_density", "input_z_error"})
            return _consumption_port(values)
        raise ValueError(f"Unsupported factory event selector {selector!r}.")

    def preparation_quality(
        self, preparation: str, parameters: Mapping[str, object] | None = None
    ) -> dict[str, Any]:
        """Return declared accepted-input quality and opaque consumption parameters."""
        return resource_preparation_quality(preparation, parameters)

    def preparation_event(
        self,
        preparation: str,
        source: PreparationExpansion,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Resolve a preparation event from its actual compiled source and world.

        With no noise_model, input_z_error is the existing explicit reference
        quality parameter; it does not change ideal preparation class statistics.
        noise/v1 requires explicit noise_params and a full raw-T sequence. The
        actual segment is validated and costed with every spectator retained.
        Unknown/mixed models and unsupported preparation sources raise ValueError.
        """
        name = _name(preparation)
        if _preparation(source) != name:
            raise ValueError(
                "Preparation source does not match the requested protocol."
            )
        if isinstance(source, RawTPostselectionExpansion):
            _normal_raw_source(source)
        values = _event_parameters(parameters)
        if "noise_model" not in values and "noise_params" not in values:
            _allowed(values, {"input_z_error"})
            resource_preparation_quality("raw_t_postselection", values)
            if isinstance(source, RawTPostselectionExpansion):
                return self.resolve_event(
                    f"preparation:{name}", {"extra_rounds": len(source.parts) - 1}
                )
            return self.resolve_event(f"preparation:{name}")
        _allowed(values, {"noise_model", "noise_params"})
        if (
            values.get("noise_model") != "noise/v1"
            or "noise_params" not in values
            or not isinstance(values["noise_params"], Mapping)
        ):
            raise ValueError("noise/v1 requires an explicit noise_params mapping.")
        if name != "raw_t_postselection" or not isinstance(
            source, RawTPostselectionExpansion
        ):
            raise ValueError(
                "Noisy preparation currently supports raw_t_postselection."
            )
        # Fingerprint the complete immutable source, including actual actions,
        # world and identities. It is only an in-process cache key; public model
        # provenance is independently derived by the physical cost estimator.
        key = (
            sha256(repr(source).encode("utf-8")).hexdigest(),
            canonical_hash(dict(values["noise_params"])),
        )
        if key not in self._preparation_events:
            self._preparation_events[key] = raw_t_preparation_port(
                source, self.device, noise_params=values["noise_params"]
            )
        return self._preparation_events[key]

    def preparation_quality_from_event(
        self,
        preparation: str,
        source: PreparationExpansion,
        port: ProbabilityPort,
        values: Mapping[str, object],
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Keep actual noisy acceptance separate from uncomputed output quality.

        Returns a reference quality only for the existing ideal event path. The
        noisy path deliberately returns unsupported and no consumption parameters:
        accepted output may carry residual syndromes, while physical correction
        noise and later memory exposure have not been propagated. It never infers
        input_z_error from rejection, loss, or a no-fault product proxy.
        """
        expected = self.preparation_event(preparation, source, parameters)
        if port.content_sha256 != expected.content_sha256:
            raise ValueError(
                "Preparation event has a different actual source or model."
            )
        if (
            not isinstance(values, Mapping)
            or set(values) != {"accepted", "byproduct_class"}
            or values.get("accepted") is not True
            or type(values.get("byproduct_class")) is not int
            or not any(
                dict(o.values) == dict(values) and o.probability > 0
                for o in port.outcomes
            )
        ):
            raise ValueError("Resource quality requires a possible accepted event.")
        params = _event_parameters(parameters)
        if "noise_model" not in params:
            return self.preparation_quality(preparation, params)
        model = port.to_dict()["model"]
        return {
            "status": "unsupported",
            "model_id": "raw_t.accepted_physical_quality.unresolved.v1",
            "source_port_sha256": port.content_sha256,
            "source_noise_model": model["id"],
            "noise_params_hash": model["evidence"]["noise_params_hash"],
            "condition": "raw detector acceptance; known local relation selected",
            "byproduct_class": values["byproduct_class"],
            "consumption_parameters": None,
            "logical_success_probability": None,
            "raw_rejection_is_input_error": False,
            "reasons": [
                "Acceptance does not fix the final physical syndrome sector",
                "Paired bulk readout errors can pass and cause wrong local correction",
                "Open final boundary permits undetected data errors after extraction",
                "Actual correction pulses and later memory noise are not propagated",
                "No recovery convention or conditional output channel is specified",
            ],
            "excluded_effects": model["evidence"]["excluded_effects"],
            "physical_loss": model["evidence"]["physical_loss"],
        }

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Return code-owned conditional quality for the exact final-check model."""
        return factory_output_quality(factory_port)


def _consumption_port(values: dict[str, Any]) -> ProbabilityPort:
    if "input_z_error" not in values:
        return t_injection_port(**values)
    if "magic_density" in values:
        raise ValueError("input_z_error and magic_density cannot be supplied together.")
    p = values["input_z_error"]
    if type(p) not in (int, float) or not isfinite(p) or not 0 <= p <= 1:
        raise ValueError("input_z_error must be a finite probability in [0, 1].")
    off_diagonal = (1 - 2 * p) * np.exp(-1j * np.pi / 4) / 2
    density = np.array([[0.5, off_diagonal], [off_diagonal.conjugate(), 0.5]])
    port = t_injection_port(
        data_density=values.get("data_density"), magic_density=density
    )
    document = port.to_dict()
    model = document["model"]
    model["id"] = "ideal_cnot_independent_phase_flip_magic"
    model["parameters"]["input_z_error"] = p
    model["assumptions"].append(
        "Resource density is (1-p)|A><A| + p Z|A><A|Z; "
        "p is accepted input quality, not rejection"
    )
    return ProbabilityPort.from_dict(document)


def _event_parameters(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy explicit event parameters without accepting a hidden runtime context."""
    if parameters is not None and (
        not isinstance(parameters, Mapping)
        or any(not isinstance(key, str) for key in parameters)
    ):
        raise ValueError("Event parameters require a string-keyed mapping.")
    return dict(parameters or {})
