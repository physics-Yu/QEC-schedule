"""Compare incremental admission with the prior complete-history algorithm."""

import json
import random
from dataclasses import replace

import pytest

from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.src.scheduling import components as implementation


def _node(identity, patches=None, **kwargs):
    return ComponentNode(
        identity,
        ComponentExecutionSpec(
            "toy",
            "gate",
            "macro",
            patches or (identity,),
            (),
            (),
            "profile_parallel",
            0,
        ),
        **kwargs,
    )


def _full_dag_reference(nodes):
    remaining = {key: len(node.after_calls) for key, node in nodes.items()}
    successors = {key: [] for key in nodes}
    for node in nodes.values():
        for dependency in node.after_calls:
            if dependency not in nodes:
                raise ValueError(
                    f"UNKNOWN_DEPENDENCY: {node.id!r} needs {dependency!r}"
                )
            successors[dependency].append(node.id)
    ready = [key for key, count in remaining.items() if not count]
    visited = 0
    while ready:
        visited += 1
        for successor in successors[ready.pop()]:
            remaining[successor] -= 1
            if not remaining[successor]:
                ready.append(successor)
    if visited != len(nodes):
        raise ValueError("DEPENDENCY_CYCLE: component calls are not acyclic")


class FullHistoryReference(ComponentScheduler):
    """Retain the former full-copy add and full-scan frontier independently."""

    def add(self, *nodes):
        proposed, last = dict(self._nodes), dict(self._last_patch)
        added = []
        for node in nodes:
            if not isinstance(node, ComponentNode):
                raise TypeError("INVALID_COMPONENT_NODE: expected ComponentNode")
            if node.id in proposed:
                raise ValueError(f"DUPLICATE_NODE: {node.id!r}")
            predecessors = set(node.after_calls)
            predecessors.update(
                last[patch] for patch in node.spec.participant_blocks if patch in last
            )
            stored = replace(node, after_calls=tuple(sorted(predecessors)))
            proposed[node.id] = stored
            last.update((patch, node.id) for patch in node.spec.participant_blocks)
            added.append(stored)
        _full_dag_reference(proposed)
        if added:
            self._nodes, self._last_patch = proposed, last
            self._revision += 1
        return tuple(added)

    def frontier(self, now_us):
        now = implementation._time(now_us)
        return tuple(
            node
            for node in sorted(
                self._nodes.values(), key=lambda item: (item.priority, item.id)
            )
            if node.id not in self._completed
            and node.id not in self._running
            and node.id not in self._cancelled
            and node.not_before_us <= now
            and all(
                self._completed.get(key, float("inf")) <= now
                for key in node.after_calls
            )
            and all(
                self._events.get(key, float("inf")) <= now
                for key in node.event_dependencies
            )
            and all(
                self._tokens.get(key, float("inf")) <= now
                for key in node.token_dependencies
            )
        )


def _bytes(scheduler):
    return json.dumps(
        scheduler.snapshot(), sort_keys=True, separators=(",", ":")
    ).encode()


def _same_action(left, right, method, *args, **kwargs):
    outcomes = []
    for scheduler in (left, right):
        before = _bytes(scheduler)
        try:
            outcomes.append(("return", getattr(scheduler, method)(*args, **kwargs)))
        except (ValueError, TypeError) as error:
            outcomes.append((type(error).__name__, str(error)))
            assert _bytes(scheduler) == before
    assert outcomes[0] == outcomes[1]
    assert _bytes(left) == _bytes(right)
    return outcomes[0]


@pytest.mark.parametrize("seed", (0, 7, 119, 20261025))
def test_seeded_submission_and_progress_match_full_history_bytes(seed):
    rng = random.Random(seed)
    actual, reference = ComponentScheduler(), FullHistoryReference()
    now = 0.0
    for step in range(80):
        names = [f"call-{step}-{index}" for index in range(rng.randrange(1, 5))]
        known = list(reference._nodes)
        candidates = [*known, *names, "unknown"]
        nodes = tuple(
            _node(
                name,
                tuple(
                    rng.sample([f"patch-{i}" for i in range(8)], rng.randrange(1, 3))
                ),
                after_calls=() if rng.random() < 0.6 else (rng.choice(candidates),),
                event_dependencies=() if rng.random() < 0.8 else (f"event-{step % 3}",),
                token_dependencies=() if rng.random() < 0.8 else (f"token-{step % 3}",),
                not_before_us=now + rng.randrange(3),
                priority=rng.randrange(-1, 3),
            )
            for name in names
        )
        _same_action(actual, reference, "add", *nodes)
        if step % 8 == 0:
            _same_action(actual, reference, "add")
        if known and step % 7 == 0:
            _same_action(actual, reference, "add", _node(rng.choice(known)))
        for kind in ("event", "token"):
            _same_action(
                actual, reference, f"release_{kind}", f"{kind}-{step % 3}", now
            )
        now += 3
        assert actual.frontier(now) == reference.frontier(now)
        result = _same_action(
            actual, reference, "admit", now, snapshot_id=f"world-{step}"
        )
        proposal = result[1]
        if proposal is not None:
            _same_action(actual, reference, "commit_admission", proposal)
            assert actual.frontier(now) == reference.frontier(now)
            for member in proposal.nodes:
                _same_action(actual, reference, "mark_completed", member.id, now + 1)
            now += 1
        pending = sorted(
            set(reference._nodes)
            - reference._running.keys()
            - reference._completed.keys()
        )
        if pending and step % 5 == 0:
            _same_action(
                actual,
                reference,
                "cancel_pending",
                (rng.choice(pending),),
                reason="fixture_stop",
            )


def test_forward_edges_patch_cycles_and_failed_add_preserve_exact_state():
    actual, reference = ComponentScheduler(), FullHistoryReference()
    _same_action(actual, reference, "add", _node("root", ("P",)))
    _same_action(
        actual,
        reference,
        "add",
        _node("forward", ("Q",), after_calls=("later",)),
        _node("later", ("R",)),
    )
    _same_action(
        actual,
        reference,
        "add",
        _node("a", ("P",), after_calls=("b",)),
        _node("b", ("P",)),
    )
    _same_action(actual, reference, "add", _node("self", after_calls=("self",)))
    _same_action(actual, reference, "add", _node("missing", after_calls=("unknown",)))
    _same_action(actual, reference, "add", _node("valid-first", ("P",)), object())
    _same_action(actual, reference, "add", _node("next", ("P",)))
    assert actual._nodes["next"].after_calls == ("root",)


def test_pending_index_removes_started_and_cancelled_but_not_dependents():
    actual, reference = ComponentScheduler(), FullHistoryReference()
    _same_action(
        actual,
        reference,
        "add",
        _node("a"),
        _node("b"),
        _node("dependent", after_calls=("b",)),
    )
    _same_action(actual, reference, "cancel_pending", ("b",), reason="stopped")
    _same_action(actual, reference, "cancel_pending", ("b",), reason="stopped")
    _same_action(
        actual, reference, "cancel_pending", ("a", "missing"), reason="stopped"
    )
    proposal = _same_action(actual, reference, "admit", 0, snapshot_id="world")[1]
    assert proposal.node_ids == ("a",)
    _same_action(actual, reference, "commit_admission", proposal)
    assert actual.frontier(0) == reference.frontier(0) == ()
    _same_action(
        actual, reference, "cancel_pending", ("dependent", "a"), reason="stopped"
    )
    _same_action(actual, reference, "mark_completed", "a", 1)
    _same_action(actual, reference, "cancel_pending", ("dependent",), reason="stopped")
    assert actual.frontier(1) == reference.frontier(1) == ()


def test_add_validation_work_scales_with_new_nodes_not_retained_history(monkeypatch):
    original = implementation._validate_dag
    visits = []

    def measured(nodes, *args, **kwargs):
        visits.append(len(nodes))
        return original(nodes, *args, **kwargs)

    monkeypatch.setattr(implementation, "_validate_dag", measured)
    scheduler = ComponentScheduler()
    for index in range(300):
        scheduler.add(_node(str(index), ("same-patch",)))
    assert sum(visits) == 300
    assert len(scheduler.snapshot()["nodes"]) == 300


def test_frontier_does_not_rescan_completed_history():
    class CountedNodes(dict):
        visits = 0

        def values(self):
            for node in super().values():
                self.visits += 1
                yield node

        def __getitem__(self, key):
            self.visits += 1
            return super().__getitem__(key)

    scheduler = ComponentScheduler()
    scheduler.add(*(_node(f"done-{index}") for index in range(60)))
    proposal = scheduler.admit(0, snapshot_id="world")
    scheduler.commit_admission(proposal)
    for member in proposal.nodes:
        scheduler.mark_completed(member.id, 1)
    scheduler.add(*(_node(f"new-{index}") for index in range(3)))
    counted = CountedNodes(scheduler._nodes)
    scheduler._nodes = counted
    assert len(scheduler.frontier(1)) == 3
    assert counted.visits == 3
