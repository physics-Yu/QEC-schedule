"""The named asynchronous policy preserves the existing scheduler behavior."""

from dataclasses import FrozenInstanceError

import pytest

from modules.logical_compiler.src.protocols.factory_strategy import (
    AsynchronousStrategy,
    SynchronousStrategy,
    resolve_factory_strategy,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler


def test_asynchronous_descriptor_retains_independent_cohorts_and_parallel_frontier():
    strategy = resolve_factory_strategy()
    assert isinstance(strategy, AsynchronousStrategy)
    assert strategy.strategy_id == "asynchronous/v1"
    assert strategy.cohort_id("factory0") == "factory0"
    assert strategy.cohort_id("factory7") == "factory7"
    first, second = strategy.make_scheduler(), strategy.make_scheduler()
    assert first is not second
    assert first.snapshot() == ComponentScheduler().snapshot()
    assert first.mode == "parallel" and first.max_parallel is None
    description = strategy.to_dict()
    assert description["selection"] == "greedy_ready_frontier"
    assert description["service_order"] == "fair_service"
    assert description["correction_priority"] == -1
    assert description["retries"] == "independent"
    assert description["deliberate_hold"] is False
    description["id"] = "changed"
    assert strategy.to_dict()["id"] == "asynchronous/v1"
    with pytest.raises(FrozenInstanceError):
        strategy.name = "synchronous"


@pytest.mark.parametrize("name", ["asynchronous", "async", "asynchronous/v1"])
def test_asynchronous_names_resolve_to_the_same_policy(name):
    assert resolve_factory_strategy(name) == AsynchronousStrategy()


@pytest.mark.parametrize("factory_id", ["", " ", None, 1])
def test_cohort_rejects_invalid_factory_identifiers(factory_id):
    with pytest.raises(ValueError, match="FACTORY_ID"):
        AsynchronousStrategy().cohort_id(factory_id)


@pytest.mark.parametrize("name", ["synchronous", "sync", "synchronous/v2"])
def test_synchronous_policy_uses_fixed_cohort_and_original_parallel_scheduler(name):
    policy = resolve_factory_strategy(name)
    assert isinstance(policy, SynchronousStrategy)
    assert policy.strategy_id == "synchronous/v2"
    assert policy.cohort_id("factory0") == policy.cohort_id("factory1")
    assert policy.make_scheduler().snapshot() == ComponentScheduler().snapshot()
    assert policy.to_dict()["deliberate_hold"] is True
    assert policy.to_dict()["member_failure"] == "abort_estimate"
    with pytest.raises(ValueError, match="FACTORY_ID"):
        policy.cohort_id("")


def test_old_success_quota_strategy_cannot_be_silently_reinterpreted():
    with pytest.raises(ValueError, match="SUPERSEDED_SYNCHRONOUS_V1"):
        resolve_factory_strategy("synchronous/v1")


@pytest.mark.parametrize("name", ["", "other", None, 1])
def test_unknown_strategy_is_an_explicit_error(name):
    with pytest.raises(ValueError, match="UNKNOWN_FACTORY_STRATEGY"):
        resolve_factory_strategy(name)
