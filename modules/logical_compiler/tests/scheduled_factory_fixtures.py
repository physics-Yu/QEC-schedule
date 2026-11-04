"""Generic scheduling/lifecycle fixtures, not surface or physical evidence."""

from types import SimpleNamespace

from nadit_physical_compiler.device import Region
from test_factory_execution import CODE, FixtureBackend, FixturePhysical

from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim


class DeclaredBackend(FixtureBackend):
    def describe_execution(self, component_id, participants, parameters=()):
        count = int(component_id in ("toy.raw", "toy.plus", "toy.mz", "toy.mx"))
        single = len(participants) == 1 and component_id == "toy.raw"
        return ComponentExecutionSpec(
            CODE,
            component_id,
            component_id if single else None,
            tuple(p.block_id for p in participants),
            tuple(
                SpaceClaim(
                    Region(p.origin.x - 0.1, -0.1, p.origin.x + 0.1, 0.1), "fixture"
                )
                for p in participants
            ),
            (),
            "independent_aods_lockstep" if single else "exclusive",
            count,
        )


class BatchedPhysical(FixturePhysical):
    @property
    def snapshot_id(self):
        return f"fixture:{self.clock_us}:{len(self.committed)}"

    def invoke_batch(self, admission, requests, *, not_before_us=0):
        assert admission.snapshot_id == self.snapshot_id
        start, parts, ends = self.clock_us, [], []
        for request in requests:
            self.clock_us = start
            value = self.invoke(
                request.bound, request.invocation_id, request.result_count
            )
            parts.append((request.invocation_id, value))
            ends.append(self.clock_us)
        self.clock_us = max(ends)
        return SimpleNamespace(member_parts=tuple(parts), action_end_us=self.clock_us)
