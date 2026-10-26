"""Drive independent initial preparation chains through the component frontier."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING

from modules.codes.contracts.component import ComponentExpansion
from modules.codes.contracts.factory_recipe import ComponentCall, ResourcePreparation

from .parallel_physical import PhysicalBatchRequest

if TYPE_CHECKING:
    from .factory import FactoryExecutor


@dataclass
class _Preparation:
    preparation: ResourcePreparation
    identity: str
    attempt: int = 0
    parts: tuple[ComponentExpansion, ...] | None = None
    done: bool = False

    @property
    def attempt_scope(self) -> str:
        return f"{self.identity}/attempt[{self.attempt}]"

    @property
    def body_id(self) -> str:
        return self.attempt_scope + "/body"

    @property
    def call(self) -> ComponentCall:
        return ComponentCall(
            "body",
            self.preparation.component_id,
            (self.preparation.role,),
            self.preparation.parameters,
        )


def prepare_initial(executor: FactoryExecutor, scope: str) -> None:
    """Submit independent bodies, handling each patch's own feedback and retry.

    Only the active attempt is submitted. Accepted chains finish before a failed
    chain can reset its own carrier again. Events may release at a completed-wave
    boundary later than their physical availability; no action or result is moved.
    Physical failures commit neither a partial batch nor a partial ledger update.
    """
    from .factory import _Stop

    scheduler = executor.scheduler
    assert scheduler is not None
    states = [
        _Preparation(preparation, f"{scope}/{preparation.key}")
        for preparation in executor.recipe.initial_preparations
    ]
    for state in states:
        executor._queue_call(state.call, state.attempt_scope)
    while any(not state.done for state in states):
        for state in states:
            if (
                state.parts is None
                or max(p.results_ready_us for p in state.parts)
                > executor.physical.clock_us
            ):
                continue
            preparation = state.preparation
            source = executor.physical.source(state.body_id)
            hook = getattr(executor.backend, "preparation_event", None)
            port = (
                hook(preparation.canonicalization_id, source, executor.parameters)
                if callable(hook)
                else executor.backend.resolve_event(preparation.event_selector)
            )
            observation = executor._sample(
                port, state.identity, state.attempt, state.parts
            )
            accepted = observation.values.get("accepted")
            if type(accepted) is not bool:
                raise ValueError(
                    "INVALID_PREPARATION_EVENT: Boolean acceptance is required"
                )
            carrier_id = executor.roles[preparation.role]
            executor._mark(
                "preparation_decision",
                preparation=state.identity,
                attempt=state.attempt,
                accepted=accepted,
                carrier_id=carrier_id,
            )
            if accepted:
                token = executor._accept_preparation(
                    preparation,
                    state.identity,
                    state.attempt,
                    scope,
                    source,
                    port,
                    observation,
                )
                if token is not None:
                    scheduler.release_token(token.token_id, token.ready_at_us)
                state.parts, state.done = None, True
            else:
                if state.attempt + 1 == executor.limits.raw_attempts:
                    raise _Stop(
                        "input_supply_exhausted",
                        f"Preparation {state.identity!r} exhausted its local budget",
                    )
                executor.ledger.complete_use(
                    carrier_id, owner=scope, at_us=executor.physical.clock_us
                )
                state.attempt += 1
                state.parts = None
                executor._queue_call(state.call, state.attempt_scope)
        if all(state.done for state in states):
            break
        admission = scheduler.admit(
            executor.physical.clock_us, snapshot_id=executor.physical.snapshot_id
        )
        if admission is None:
            deadlines = [
                max(p.results_ready_us for p in state.parts)
                for state in states
                if state.parts is not None
            ]
            if not deadlines:
                raise ValueError(
                    "INITIAL_PREPARATION_DEADLOCK: no ready call or future result"
                )
            executor.physical.wait_until(
                min(deadlines), reason=f"initial_preparation_feedback:{scope}"
            )
            continue
        selected = {
            state.body_id: state
            for state in states
            if not state.done and state.parts is None
        }
        if not set(admission.node_ids) <= selected.keys():
            raise ValueError("INITIAL_PREPARATION_FRONTIER: unexpected component")
        if (
            len(executor.calls) + len(admission.nodes)
            > executor.limits.max_component_calls
        ):
            raise _Stop("expansion_budget_exhausted", "Maximum component calls reached")
        next_ledger = deepcopy(executor.ledger)
        requests = []
        for node in admission.nodes:
            state = selected[node.id]
            role = state.preparation.role
            next_ledger.begin_preparation(
                executor.roles[role], owner=scope, at_us=admission.start_us
            )
            executor._stage = node.id
            try:
                bound = executor.backend.bind_call(
                    state.call.component_id,
                    (executor.physical.bindings[executor.roles[role]],),
                    state.call.parameters,
                )
            except (ValueError, NotImplementedError) as error:
                raise _Stop("physical_failure", str(error)) from error
            if bound.result_count != node.spec.result_count:
                raise ValueError("RESULT_DECLARATION_MISMATCH")
            requests.append(PhysicalBatchRequest(node.id, bound, bound.result_count))
        executor._stage = admission.batch_id
        try:
            if len(requests) == 1:
                request = requests[0]
                outputs = {
                    request.invocation_id: executor.physical.invoke(
                        request.bound, request.invocation_id, request.result_count
                    )
                }
            else:
                batch = executor.physical.invoke_batch(admission, tuple(requests))
                outputs = dict(batch.member_parts)
        except (ValueError, NotImplementedError) as error:
            raise _Stop("physical_failure", str(error)) from error
        scheduler.commit_admission(admission)
        for node in admission.nodes:
            state = selected[node.id]
            parts = outputs[node.id]
            end = max(part.action_end_us for part in parts)
            next_ledger.extend_use(
                executor.roles[state.preparation.role],
                owner=scope,
                at_us=admission.start_us,
                safe_exit_at_us=end,
            )
            scheduler.mark_completed(node.id, end)
            executor._sources[node.id] = parts
            executor.calls.append(
                {
                    "invocation_id": node.id,
                    "component_id": state.call.component_id,
                    "parameters": dict(state.call.parameters),
                    "participant_roles": [state.preparation.role],
                    "start_us": admission.start_us,
                    "end_us": end,
                    "after_calls": list(node.after_calls),
                    "event_dependencies": [
                        json.loads(key) for key in node.event_dependencies
                    ],
                    "part_invocations": [part.invocation_id for part in parts],
                    "consumed_token_id": None,
                    "batch_id": admission.batch_id,
                }
            )
            executor._role_calls[state.preparation.role] = node.id
            state.parts = parts
        executor.ledger = next_ledger
        executor._mark(
            "component_batch_completed",
            batch_id=admission.batch_id,
            invocation_ids=list(admission.node_ids),
            start_us=admission.start_us,
            end_us=executor.physical.clock_us,
            width=len(admission.nodes),
        )
    executor._mark(
        "initial_preparations_ready", roles=[state.preparation.role for state in states]
    )
