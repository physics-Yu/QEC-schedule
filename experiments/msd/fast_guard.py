"""Fail closed if a fast experiment enters known atom-level execution paths.

This is an acceptance instrument, not a security sandbox. It observes Python
calls on the current thread, including aliases captured before guard entry and
modules imported later. Each worker thread/process needs its own guard. Nested
guards on one thread are rejected; an existing profiler is chained and restored.
No physical compiler, component, cache, or quantum package is imported here.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import get_ident, local
from types import CodeType, FrameType
from typing import Any

FORBIDDEN_ENTRYPOINTS: tuple[str, ...] = (
    "nadit_physical_compiler.compiler:compile_physical",
    "nadit_physical_compiler.compiler:_Compilation.run",
    "nadit_physical_compiler.execution:execute",
    "nadit_physical_compiler.execution:_Execution.run",
    "nadit_physical_compiler.replay:replay",
    "nadit_physical_compiler.replay:apply_step",
    "nadit_physical_compiler.validation:validate_result",
    "nadit_physical_compiler.activity:derive_activity",
    "nadit_physical_compiler.serialization:decode_program",
    "nadit_physical_compiler.frontend:loads_qasm",
    "nadit_physical_compiler.frontend.qasm:loads_qasm",
    "modules.logical_compiler.src.protocols.execution_kernel:PhysicalExecutionKernel.execute",
    "modules.logical_compiler.src.protocols.physical:PhysicalContext.invoke",
    "modules.logical_compiler.src.protocols.physical:PhysicalContext.invoke_batch",
    "modules.logical_compiler.src.protocols.physical:PhysicalContext.finalize",
    "modules.logical_compiler.src.protocols.parallel_physical:build_batch",
    "experiments.msd.joint_factory_calibration:compile_joint_actions",
    "experiments.msd.joint_factory_calibration:compile_joint_group",
    "experiments.msd.joint_factory_calibration:evaluate_joint_probabilities",
    "experiments.msd.joint_cache:JointCalibrationCache.get_or_create",
    "modules.codes.*:*.expand",
)
_EXACT_ENTRYPOINTS = frozenset(FORBIDDEN_ENTRYPOINTS[:-1])
_THREAD_STATE = local()


class AtomExecutionForbidden(RuntimeError):
    """A no-atom experiment attempted physical compilation, expansion or replay."""


@dataclass
class NoAtomExecutionAudit:
    """Serializable evidence for one guarded current-thread execution interval."""

    thread_id: int = field(default_factory=get_ident)
    intercepted_call_count: int = 0
    intercepted_entrypoints: list[str] = field(default_factory=list)
    completed: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Describe actual interception and the explicitly limited guard scope."""
        return {
            "schema": "nadit.no_atom_execution_audit/1",
            "guard": "python_profile_call_entry",
            "scope": "current_thread_only; install separately in every worker",
            "thread_id": self.thread_id,
            "forbidden_entrypoints": list(FORBIDDEN_ENTRYPOINTS),
            "intercepted_call_count": self.intercepted_call_count,
            "intercepted_entrypoints": list(self.intercepted_entrypoints),
            "completed": self.completed,
            "passed": self.completed and self.intercepted_call_count == 0,
            "limitations": "Known Python entrypoints only; not a security sandbox or atom-level legality proof",
        }


@contextmanager
def no_atom_execution() -> Iterator[NoAtomExecutionAudit]:
    """Reject known atom execution calls before their bodies run.

    Yields a fresh audit. Raises AtomExecutionForbidden on a forbidden call or
    suppressed interception, and RuntimeError for nesting or profiler changes.
    On every exit the preceding profiler is restored. The guard is deliberately
    thread-local: callers must guard each worker and must not disable profiling.
    """
    if getattr(_THREAD_STATE, "active", False):
        raise RuntimeError("NO_ATOM_GUARD_ALREADY_ACTIVE_ON_THREAD")
    audit = NoAtomExecutionAudit()
    previous = sys.getprofile()
    # Keep a strong reference to each code object so its id cannot be recycled
    # during this context. The module is checked on every call: FunctionType
    # aliases can reuse one code object with a different globals dictionary.
    classifications: dict[int, tuple[CodeType, str, str | None]] = {}

    def observe(frame: FrameType, event: str, arg: Any) -> None:
        if event == "call":
            code = frame.f_code
            module = frame.f_globals.get("__name__", "")
            if not isinstance(module, str):
                module = str(module)
            identity = id(code)
            cached = classifications.get(identity)
            if cached is None or cached[1] != module:
                name = f"{module}:{code.co_qualname}"
                expansion = module.startswith("modules.codes.") and (
                    code.co_name == "expand"
                )
                forbidden = name if name in _EXACT_ENTRYPOINTS or expansion else None
                cached = (code, module, forbidden)
                classifications[identity] = cached
            forbidden = cached[2]
            if forbidden is not None:
                audit.intercepted_call_count += 1
                audit.intercepted_entrypoints.append(forbidden)
                raise AtomExecutionForbidden(f"ATOM_EXECUTION_FORBIDDEN: {forbidden}")
        if previous is not None:
            previous(frame, event, arg)

    _THREAD_STATE.active = True
    try:
        sys.setprofile(observe)
        yield audit
        if audit.intercepted_call_count:
            raise AtomExecutionForbidden("ATOM_EXECUTION_FORBIDDEN_WAS_SUPPRESSED")
        if sys.getprofile() is not observe:
            raise RuntimeError("NO_ATOM_GUARD_PROFILER_CHANGED")
        audit.completed = True
    finally:
        sys.setprofile(previous)
        _THREAD_STATE.active = False
