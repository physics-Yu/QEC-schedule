"""Protocol coarse events depend on real result identities and physical exits."""

from dataclasses import dataclass, field, replace

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef
from nadit_physical_compiler.state import AtomLayout

from modules.codes.contracts.component import (
    ComponentDescription,
    ComponentExpansion,
    MeasurementOutput,
)
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.src.cases.backend import SeededEventBackend
from modules.logical_compiler.src.protocols.events import EventDependency, EventJournal
from modules.logical_compiler.tests.test_event_backend import fixture_document


@dataclass
class Clock:
    clock_us: float = 0.0
    waits: list[tuple[float, str]] = field(default_factory=list)

    def wait_until(self, time_us: float, *, reason: str) -> None:
        self.waits.append((time_us, reason))
        self.clock_us = max(self.clock_us, time_us)


def sample(journal, context, dependencies, *, port=None):
    return journal.sample(
        port or ProbabilityPort.from_dict(fixture_document()),
        invocation_id="protocol",
        attempt=0,
        dependencies=dependencies,
        context=context,
    )


def test_early_result_waits_for_later_physical_exit_before_sampling(monkeypatch):
    clock = Clock()
    original = SeededEventBackend.sample
    observed_clocks = []

    def checked_sample(self, port, occurrence, *, available_at_us):
        observed_clocks.append(clock.clock_us)
        assert clock.clock_us >= 20
        return original(self, port, occurrence, available_at_us=available_at_us)

    monkeypatch.setattr(SeededEventBackend, "sample", checked_sample)
    journal = EventJournal("case", seed=3)
    observation = sample(
        journal, clock, [EventDependency("measurement", 20, ((101, 4),))]
    )
    assert observation.result.available_at_us == 4
    assert observation.released_at_us == 20
    assert observed_clocks == [20]
    assert clock.clock_us == 20
    assert len(clock.waits) == 1 and clock.waits[0][1]


def test_multi_source_joins_last_result_and_includes_measurement_free_exit():
    journal = EventJournal("case", seed=3)
    clock = Clock()
    dependencies = [
        EventDependency("raw", 8, ((101, 9), (102, 11))),
        EventDependency("se", 13, ((103, 18),)),
        EventDependency("related-exit", 22, ()),
    ]
    observation = sample(journal, clock, dependencies)
    assert observation.result.available_at_us == 18
    assert observation.released_at_us == 22
    assert {d["invocation_id"] for d in observation.to_dict()["dependencies"]} == {
        "raw",
        "se",
        "related-exit",
    }


def test_current_clock_is_a_lower_bound_and_does_not_change_result_ready_time():
    observation = sample(
        EventJournal("case", seed=3),
        Clock(30),
        [EventDependency("source", 10, ((5, 12),))],
    )
    assert observation.result.available_at_us == 12
    assert observation.released_at_us == 30


def test_repeated_identical_binding_reuses_observation_and_keeps_one_event():
    journal = EventJournal("case", seed=3)
    clock = Clock()
    dependencies = [
        EventDependency("b", 4, ((8, 5),)),
        EventDependency("a", 5, ((7, 6),)),
    ]
    first = sample(journal, clock, dependencies)
    waits = len(clock.waits)
    assert sample(journal, clock, reversed(dependencies)) is first
    assert len(journal.snapshot()["events"]) == 1
    assert len(clock.waits) == waits


def test_cached_result_is_not_exposed_to_a_context_before_original_release():
    journal = EventJournal("case", seed=3)
    dependencies = [EventDependency("source", 10, ((5, 12),))]
    first = sample(journal, Clock(30), dependencies)
    earlier_clock = Clock(1)
    assert sample(journal, earlier_clock, dependencies) is first
    assert earlier_clock.clock_us >= first.released_at_us
    assert len(journal.snapshot()["events"]) == 1


def test_changed_dependency_identity_is_rejected_even_with_same_ready_time():
    journal = EventJournal("case", seed=3)
    clock = Clock()
    sample(journal, clock, [EventDependency("source", 10, ((5, 12),))])
    with pytest.raises(ValueError, match="EVENT_DEPENDENCY_CONFLICT"):
        sample(journal, clock, [EventDependency("source", 10, ((6, 12),))])
    assert len(journal.snapshot()["events"]) == 1


@pytest.mark.parametrize("change", ["ready", "model"])
def test_changed_backend_binding_preserves_backend_conflict_semantics(change):
    journal = EventJournal("case", seed=3)
    clock = Clock()
    dependencies = [EventDependency("source", 10, ((5, 12),))]
    sample(journal, clock, dependencies)
    document = fixture_document()
    if change == "ready":
        dependencies = [EventDependency("source", 10, ((5, 13),))]
    else:
        document["model"]["evidence"]["revision"] = "other"
    with pytest.raises(ValueError, match="EVENT_BINDING_CONFLICT"):
        sample(journal, clock, dependencies, port=ProbabilityPort.from_dict(document))
    assert len(journal.snapshot()["events"]) == 1


def test_fresh_attempt_records_a_separate_occurrence():
    journal = EventJournal("case", seed=3)
    port = ProbabilityPort.from_dict(fixture_document())
    clock = Clock()
    first = sample(
        journal, clock, [EventDependency("source0", 10, ((5, 12),))], port=port
    )
    second = journal.sample(
        port,
        invocation_id="protocol",
        attempt=1,
        dependencies=[EventDependency("source1", 14, ((6, 16),))],
        context=clock,
    )
    assert first.result.occurrence != second.result.occurrence
    assert len(journal.snapshot()["events"]) == 2


@pytest.mark.parametrize("dependencies", [[], [EventDependency("source", 3, ())]])
def test_sample_requires_sources_and_at_least_one_physical_result(dependencies):
    journal = EventJournal("case", seed=3)
    clock = Clock()
    with pytest.raises(ValueError, match="INVALID_EVENT_DEPENDENCY"):
        sample(journal, clock, dependencies)
    assert journal.snapshot()["events"] == []
    assert clock.waits == []


def test_global_result_identity_cannot_be_reused_across_sources():
    with pytest.raises(ValueError, match="DUPLICATE_RESULT"):
        sample(
            EventJournal("case", seed=3),
            Clock(),
            [
                EventDependency("first", 3, ((5, 4),)),
                EventDependency("second", 4, ((5, 5),)),
            ],
        )


def test_repeated_source_invocation_is_rejected_even_with_disjoint_result_ids():
    with pytest.raises(ValueError, match="DUPLICATE_SOURCE"):
        sample(
            EventJournal("case", seed=3),
            Clock(),
            [
                EventDependency("source", 3, ((5, 4),)),
                EventDependency("source", 3, ((6, 4),)),
            ],
        )


@pytest.mark.parametrize("clock_time", [-1, True, float("nan"), float("inf")])
def test_invalid_context_clock_prevents_sampling(clock_time):
    journal = EventJournal("case", seed=3)
    with pytest.raises(ValueError, match="INVALID_EVENT_CLOCK"):
        sample(journal, Clock(clock_time), [EventDependency("source", 3, ((5, 4),))])
    assert journal.snapshot()["events"] == []


@pytest.mark.parametrize("time", [-1, True, float("nan"), float("inf")])
def test_dependency_rejects_invalid_times(time):
    with pytest.raises(ValueError, match="INVALID_EVENT_DEPENDENCY"):
        EventDependency("source", time, ((5, 1),))
    with pytest.raises(ValueError, match="INVALID_EVENT_DEPENDENCY"):
        EventDependency("source", 1, ((5, time),))


@pytest.mark.parametrize("result_id", [-1, True, "5"])
def test_dependency_requires_global_nonnegative_integer_result_ids(result_id):
    with pytest.raises(ValueError, match="INVALID_EVENT_DEPENDENCY"):
        EventDependency("source", 1, ((result_id, 2),))


def test_duplicate_result_ids_within_source_are_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_RESULT"):
        EventDependency("source", 1, ((5, 2), (5, 2)))


def test_broken_context_cannot_publish_an_event_before_feedback_is_ready():
    class BrokenClock(Clock):
        def wait_until(self, time_us: float, *, reason: str) -> None:
            self.waits.append((time_us, reason))

    journal = EventJournal("case", seed=3)
    with pytest.raises(ValueError, match="CLOCK_NOT_READY"):
        sample(journal, BrokenClock(), [EventDependency("source", 10, ((5, 12),))])
    assert journal.snapshot()["events"] == []
    assert journal.snapshot()["probability_models"] == {}


def test_export_preserves_joint_values_and_model_without_fabricating_physical_bits():
    journal = EventJournal("case", seed=3)
    port = ProbabilityPort.from_dict(fixture_document())
    observation = sample(
        journal, Clock(), [EventDependency("source", 3, ((5, 4),))], port=port
    )
    assert observation.values["left"] == observation.values["right"]
    assert (
        observation.branch_id == port.outcome(observation.result.outcome_key).branch_id
    )
    observation.values["left"] = "external mutation"
    snapshot = journal.snapshot()
    assert snapshot["probability_models"][port.content_sha256] == port.to_dict()
    assert snapshot["events"][0]["evidence_kind"] == "coarse_probability"
    assert snapshot["events"][0]["dependencies"][0]["results"] == [
        {"result_id": 5, "available_at_us": 4.0}
    ]
    assert "physical_bits" not in snapshot["events"][0]
    assert "syndrome" not in snapshot["events"][0]
    snapshot["probability_models"][port.content_sha256]["model"]["id"] = "mutation"
    assert (
        journal.snapshot()["probability_models"][port.content_sha256] == port.to_dict()
    )


def test_from_expansion_extracts_metadata_without_reading_or_assigning_bits():
    # Construct contract metadata only; this is not a physically validated circuit.
    expansion = ComponentExpansion(
        ComponentDescription("fixture", "measure", "1", (), (), (), ()),
        "physical-source",
        "block",
        10,
        AtomLayout(()),
        AtomLayout(()),
        (),
        AtomProgram(),
        PhysicalDAG(0, 0, (), ()),
        (),
        (MeasurementOutput("physical-source", "m", ResultRef(42), 1, 12, None),),
        (),
        (),
    )
    dependency = EventDependency.from_expansion(expansion)
    assert dependency == EventDependency("physical-source", 10, ((42, 12),))
    assert expansion.measurements[0].value is None
    inconsistent = replace(expansion, invocation_id="other-source")
    with pytest.raises(ValueError, match="INVALID_EVENT_DEPENDENCY"):
        EventDependency.from_expansion(inconsistent)
