"""Scripted retry/production acceptance fixture, never an MSD performance model."""

from hashlib import sha256
from typing import Any

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import (
    ComponentCall,
    EventRequest,
    FactoryRecipe,
    ResourcePreparation,
)
from modules.codes.contracts.parallel import ComponentExecutionSpec, ComponentPhase
from modules.codes.rotated_surface.object_readout import SurfaceReadoutCatalog
from modules.codes.rotated_surface_d3.protocols.fast_profile import ComponentCostProfile
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.production import (
    IdealExternalSink,
    ProductionPolicy,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler

CODE = "test_fixture.object_control"
RAW = "test_fixture.raw_postselection"
MEASURE = "test_fixture.final_measurement"


def _port(accepted: bool, selector: str) -> ProbabilityPort:
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "test_fixture." + selector,
            "protocol_id": CODE,
            "protocol_version": "1",
            "model": {
                "id": "scripted_test_fixture",
                "kind": "test_fixture",
                "assumptions": [
                    "Control-flow acceptance only; not a quantum or physical "
                    "probability"
                ],
                "parameters": {},
                "evidence": {},
            },
            "outcomes": [
                {
                    "key": key,
                    "probability": float(value == accepted),
                    "values": {
                        "accepted": value,
                        "byproduct_class": 0 if value else None,
                    },
                    "branch_id": key,
                }
                for key, value in (("accepted", True), ("rejected", False))
            ],
            "branches": [
                {"key": "accepted", "transition": "deliver", "steps": []},
                {"key": "rejected", "transition": "retry", "steps": []},
            ],
        }
    )


def fixture_recipe() -> FactoryRecipe:
    """Two work roles isolate retries, final rejection and next-cycle resets."""
    preps = tuple(
        ResourcePreparation(
            f"initial/{role}",
            role,
            RAW,
            "raw",
            RAW,
            None,
            "working",
            (("injection_rounds", 3),),
        )
        for role in ("W1", "W2")
    )
    final = ComponentCall("final/measure", MEASURE, ("W2",))
    return FactoryRecipe(
        CODE,
        CODE,
        "1",
        ("W1", "W2"),
        "R",
        preps,
        (),
        (final,),
        EventRequest("final/event", "final", (final.key,), ("W2",)),
        (),
        ("W1", "W2"),
        ("W2", "R"),
        "W1",
        "test_fixture.output",
    )


class FixtureCatalog:
    """Prepare synthetic stages once; all timing is explicitly fixture data."""

    def __init__(self, layout_catalog: SurfaceReadoutCatalog | None = None) -> None:
        self.layout_catalog = layout_catalog or SurfaceReadoutCatalog((3,))
        aod = ("aod:transport",)
        raw = [ComponentPhase("reset", 5, "reset", ("local",), "fixture.reset")]
        for index in range(3):
            raw.extend(
                (
                    ComponentPhase(
                        f"round{index}/gate", 2, "gate", ("local",), "fixture.gate"
                    ),
                    ComponentPhase(
                        f"round{index}/load",
                        10,
                        "transfer",
                        aod,
                        "fixture.readout",
                        acquire=aod,
                    ),
                    ComponentPhase(
                        f"round{index}/outbound", 50, "movement", aod, "fixture.readout"
                    ),
                    ComponentPhase(
                        f"round{index}/measure",
                        100,
                        "measurement",
                        (*aod, "camera"),
                        "fixture.readout",
                        results=1,
                    ),
                    ComponentPhase(
                        f"round{index}/return", 50, "movement", aod, "fixture.readout"
                    ),
                    ComponentPhase(
                        f"round{index}/store",
                        10,
                        "transfer",
                        aod,
                        "fixture.readout",
                        release=aod,
                    ),
                )
            )
        stages = {
            RAW: tuple(raw),
            RAW + "/canonicalize": (
                ComponentPhase(
                    "correction", 1, "gate", ("local",), "fixture.correction"
                ),
            ),
            MEASURE: (
                ComponentPhase(
                    "final_measurement",
                    100,
                    "measurement",
                    ("camera",),
                    "fixture.final",
                    results=1,
                ),
            ),
        }
        self.entries = {
            name: ComponentCostProfile(
                name,
                name,
                (),
                0 if name.endswith("canonicalize") else None,
                name,
                tuple(p.duration_us for p in phases),
                (),
                (),
                (),
                {},
                (),
                (),
                {
                    "result_count": sum(p.results for p in phases),
                    "scope": "test_fixture",
                },
                phases,
            )
            for name, phases in stages.items()
        }
        self.template_builds = len(self.entries)
        self.lookups = 0


class FixtureProfile:
    """The regular profile interface supplies finite scripted control-flow costs."""

    def __init__(self, catalog: FixtureCatalog) -> None:
        self.catalog = catalog
        self.profile_sha256 = sha256(b"object_control_fixture/1").hexdigest()
        self.wave_timeout_seconds = 5.0

    def lookup(
        self,
        component_id: str,
        participants: Any,
        selection: Any = None,
        parameters: Any = (),
    ) -> ComponentCostProfile:
        expected = {"injection_rounds": 3} if component_id == RAW else {}
        if dict(parameters) != expected:
            raise ValueError("FIXTURE_PREPARATION_PARAMETERS_NOT_FORWARDED")
        self.catalog.lookups += 1
        return self.catalog.entries[component_id]

    def describe(
        self, component_id: str, participants: Any, parameters: Any = (), *, budget: Any
    ) -> ComponentExecutionSpec:
        entry = self.lookup(component_id, participants, parameters=parameters)
        return ComponentExecutionSpec(
            CODE,
            component_id,
            component_id,
            tuple(p.block_id for p in participants),
            (),
            (),
            "object_wave",
            entry.claim["result_count"],
        )

    def instantiate_wave(self, requests: Any) -> tuple[ComponentCostProfile, ...]:
        return tuple(
            self.lookup(r.call.component_id, (), r.selection, r.call.parameters)
            for r in requests
        )


class FixtureBackend:
    """Force specified rejections; probabilities remain visibly test fixtures."""

    def __init__(
        self, reject_attempts: int, *, reject_final_once: bool = False
    ) -> None:
        self.reject_attempts = reject_attempts
        self.reject_final_once = reject_final_once

    def preparation_event(
        self, preparation: str, source: Any, parameters: Any
    ) -> ProbabilityPort:
        identity = source.invocation_id
        rejected = (
            identity.startswith("factory0/")
            and "/initial/W2/" in identity
            and any(f"/attempt[{i}]/" in identity for i in range(self.reject_attempts))
        )
        return _port(not rejected, "raw")

    def resolve_event_from_sources(
        self, selector: str, parts: Any, parameters: Any, *, event_id: str
    ) -> ProbabilityPort:
        rejected = self.reject_final_once and "/batch[0]/" in event_id
        return _port(not rejected, "final")

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        return {
            "status": "test_fixture",
            "consumption_parameters": {},
            "actual_output_error": None,
        }

    def resolve_event(self, selector: str, parameters: Any = None) -> ProbabilityPort:
        """Require measured-source identities even in this control-flow fixture."""
        raise ValueError("FIXTURE_EVENT_REQUIRES_SOURCE")

    def preparation_quality(
        self, preparation: str, parameters: Any = None
    ) -> dict[str, Any]:
        """This fixture prepares work blocks and has no raw-resource quality model."""
        raise ValueError("FIXTURE_RAW_RESOURCE_QUALITY_UNSUPPORTED")


def run_retry_case(
    catalog: FixtureCatalog,
    *,
    factories: int = 2,
    seed: int = 0,
    reject_attempts: int = 1,
    cycles: int = 2,
    reject_final_once: bool = False,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    """Exercise the existing FactoryProcess, ledger, event journal and ideal sink."""
    layout = catalog.layout_catalog.layout(3, factories)
    profile = FixtureProfile(catalog)
    execution = ProfileExecutionKernel(profile, layout)
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=CODE,
            recipe=fixture_recipe(),
            backend=FixtureBackend(
                reject_attempts, reject_final_once=reject_final_once
            ),
            role_bindings={r: p.block_id for r, p in f.bindings.items()},
            distance=3,
            limits=FactoryLimits(
                raw_attempts=reject_attempts + 1, batches=2 if reject_final_once else 1
            ),
            cohort_id=f.factory_id,
            production_policy=ProductionPolicy(cycles),
            output_sink=IdealExternalSink(True),
        )
        for f in layout.factories
    )
    case = (
        CooperativeFactoryRuntime(
            execution=execution,
            case_id=CODE,
            seed=seed,
            scheduler=ComponentScheduler(),
            processes=processes,
        )
        .run(timeout_seconds=timeout_seconds)
        .to_dict()
    )
    case["interpretation"] = (
        "scripted control-flow fixture; not an MSD factory performance estimate"
    )
    return case
