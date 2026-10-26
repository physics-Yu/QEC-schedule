"""Portable probability schema, joint outcomes, and immutable provenance."""

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort


@pytest.fixture
def document():
    return {
        "schema": "nadit.event_probability/1",
        "port_id": "rotated_surface_d3.t_injection.logical_z",
        "protocol_id": "rotated_surface_d3.t_injection.data_to_magic_mz",
        "protocol_version": "1",
        "model": {
            "id": "ideal_equatorial_magic",
            "kind": "ideal_exact",
            "assumptions": ["Independent canonical magic resource"],
            "parameters": {"nested": {"values": [0.25, True, None]}},
            "evidence": {"calculation": {"version": "1"}},
        },
        "outcomes": [
            {
                "key": "m0",
                "probability": 0.5,
                "values": {"logical_m": 0},
                "branch_id": "none",
            },
            {
                "key": "m1",
                "probability": 0.5,
                "values": {"logical_m": 1},
                "branch_id": "s",
            },
        ],
        "branches": [
            {"key": "none", "transition": "continue", "steps": []},
            {
                "key": "s",
                "transition": "continue",
                "steps": [
                    {
                        "component_id": "rotated_surface_d3/logical_s",
                        "participant_roles": ["data"],
                    }
                ],
            },
        ],
    }


def test_round_trip_lookup_and_canonical_identity(document):
    port = ProbabilityPort.from_dict(document)
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    assert port.to_dict() == document
    assert port.content_sha256 == hashlib.sha256(canonical.encode()).hexdigest()
    assert port.port_id == document["port_id"]
    assert port.protocol_id == document["protocol_id"]
    assert port.protocol_version == "1"
    assert port.outcome("m1").values == (("logical_m", 1),)
    assert port.outcome("m1").branch_id == "s"
    assert port.branch("s").steps[0].participant_roles == ("data",)
    assert port.branch("s").steps[0].component_id.endswith("/logical_s")
    assert (
        ProbabilityPort.from_dict(json.loads(canonical)).content_sha256
        == port.content_sha256
    )
    with pytest.raises(KeyError):
        port.outcome("missing")
    with pytest.raises(KeyError):
        port.branch("missing")


def test_deep_immutability_and_fresh_export(document):
    expected = copy.deepcopy(document)
    port = ProbabilityPort.from_dict(document)
    document["model"]["parameters"]["nested"]["values"].append("changed")
    document["outcomes"][0]["values"]["logical_m"] = 999
    export = port.to_dict()
    export["model"]["evidence"]["calculation"]["version"] = "changed"
    export["branches"][1]["steps"][0]["participant_roles"].append("magic")
    assert port.to_dict() == expected
    with pytest.raises(FrozenInstanceError):
        port.outcomes = ()
    with pytest.raises(FrozenInstanceError):
        port.outcome("m0").probability = 0.2
    with pytest.raises(FrozenInstanceError):
        port.branch("s").steps[0].component_id = "other"


@pytest.mark.parametrize(
    "kind", ("ideal_exact", "pauli_exact", "estimated", "test_fixture")
)
def test_all_declared_model_kinds(kind, document):
    document["model"]["kind"] = kind
    assert ProbabilityPort.from_dict(document).to_dict()["model"]["kind"] == kind


@pytest.mark.parametrize(
    "probability", (float("nan"), float("inf"), -0.1, 1.1, True, "0.5")
)
def test_reject_invalid_probability(probability, document):
    document["outcomes"][0]["probability"] = probability
    with pytest.raises(ValueError):
        ProbabilityPort.from_dict(document)


def test_probability_tolerance_does_not_normalize(document):
    document["outcomes"][0]["probability"] = 0.5 + 5e-13
    port = ProbabilityPort.from_dict(document)
    assert port.outcome("m0").probability == document["outcomes"][0]["probability"]
    assert port.to_dict() == document
    document["outcomes"][0]["probability"] = 0.5 + 2e-12
    with pytest.raises(ValueError):
        ProbabilityPort.from_dict(document)


def test_deterministic_acceptance_preserves_zero_probability_retry(document):
    for outcome, probability, accepted in zip(
        document["outcomes"], (1, 0), (True, False), strict=True
    ):
        outcome["probability"] = probability
        outcome["values"] = {"accepted": accepted}
    document["branches"][0]["transition"] = "deliver"
    document["branches"][1]["transition"] = "retry"
    document["branches"][1]["steps"] = []
    port = ProbabilityPort.from_dict(document)
    assert [o.probability for o in port.outcomes] == [1, 0]
    assert port.outcomes[1].values == (("accepted", False),)
    assert port.branch(port.outcomes[1].branch_id).transition == "retry"
    assert port.to_dict() == document


@pytest.mark.parametrize(
    "change",
    (
        lambda d: d.update(schema="unknown"),
        lambda d: d.update(seed=42),
        lambda d: d.pop("model"),
        lambda d: d["model"].update(kind="syndrome_decoder"),
        lambda d: d["model"].update(version="extra"),
        lambda d: d["model"].update(parameters={"x": float("nan")}),
        lambda d: d["model"].update(evidence={"nested": [float("inf")]}),
        lambda d: d["model"].update(parameters={1: "non-string-key"}),
        lambda d: d["model"].update(parameters={"x": (1, 2)}),
        lambda d: d["outcomes"].clear(),
        lambda d: d["outcomes"][1].update(key="m0"),
        lambda d: d["outcomes"][0].update(branch_id="missing"),
        lambda d: d["outcomes"][0].update(values={"different_field": 0}),
        lambda d: d["outcomes"][0].update(values={"logical_m": [0]}),
        lambda d: d["outcomes"][0].update(values={"logical_m": float("nan")}),
        lambda d: d["outcomes"][0].update(clock_us=0),
        lambda d: d["branches"][1].update(key="none"),
        lambda d: d["branches"][0].update(transition="abort"),
        lambda d: d["branches"][1]["steps"][0].update(participant_roles=[123]),
        lambda d: d["branches"][1]["steps"][0].update(
            participant_roles=["data", "data"]
        ),
        lambda d: d["branches"][1]["steps"][0].update(atom_ids=[123]),
    ),
)
def test_schema_rejects_incoherent_or_unportable_documents(change, document):
    change(document)
    with pytest.raises(ValueError):
        ProbabilityPort.from_dict(document)


def test_joint_values_and_provenance_are_fingerprinted(document):
    for outcome in document["outcomes"]:
        outcome["values"]["accepted"] = True
    original = ProbabilityPort.from_dict(document)
    document["model"]["evidence"]["calculation"]["version"] = "2"
    assert ProbabilityPort.from_dict(document).content_sha256 != original.content_sha256
    assert original.outcomes[0].values == (("accepted", True), ("logical_m", 0))


def test_reject_cyclic_model_metadata(document):
    cyclic = {}
    cyclic["self"] = cyclic
    document["model"]["evidence"] = cyclic
    with pytest.raises(ValueError):
        ProbabilityPort.from_dict(document)
