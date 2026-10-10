"""Fail before native compilation/search starts during a frozen-component run.

Observe Python code entry, so imported aliases cannot bypass the guard. Python
3.12 monitoring limits callbacks to these code objects; older interpreters use
a profiling fallback. Static linking, port binding and validation stay allowed.
"""
from contextlib import contextmanager
from copy import deepcopy
import importlib
import sys

from na_pipeline.backend.enola_kernel import digest


class UnexpectedCompilation(BaseException):
    """Not caught by a compiler's ordinary fallback/retry Exception handler."""
    code = 'UNEXPECTED_COMPILATION_BLOCKED'

    def __init__(self, details):
        self.details = details
        super().__init__(self.code + ': ' + details['entrypoint'])


ENTRYPOINTS = {
    'compiled_modules': ['CompiledModuleLibrary.compile_module'],
    'physical_dag': ['compile_physical_dag'],
    'physical_window': ['compile_operation_window'],
    'module_graph': ['module_graph'],
    'frontier_store': ['select_frontier'],
    'batch_search': ['select_batch'],
    'enola_kernel': ['EnolaKernel.select', 'group_route'],
    'enola_scheduler': ['EnolaReadyScheduler.partition'],
    'joint_kernel': ['JointEnolaKernel.select'],
}


class CompilationGuard:
    def __init__(self, *, on_violation=None):
        self.on_violation = on_violation
        self.first_violation = None
        self.context = {}
        self._codes = {}
        self._tool_id = None

    @contextmanager
    def scope(self, **context):
        old = self.context
        self.context = {**old, **deepcopy(context)}
        try:
            self.check()
            yield
            self.check()
        finally:
            self.context = old

    def check(self):
        if self.first_violation is not None:
            raise UnexpectedCompilation(self.first_violation)

    def _trip(self, entrypoint, frame):
        if self.first_violation is None:
            frames = []
            current = frame
            # Record exact failing fragment and enclosing live component call.
            fragment = world = None
            context = deepcopy(self.context)
            while current is not None:
                values = current.f_locals
                frames.append({'file': current.f_code.co_filename,
                               'function': current.f_code.co_name, 'line': current.f_lineno})
                if fragment is None:
                    fragment = values.get('dag', values.get('physical_dag'))
                if world is None:
                    world = values.get('world', values.get('initial_state'))
                if current.f_code.co_name == 'prepare_dags':
                    context.update(component=values.get('name'),
                                   requested_dags=deepcopy(values.get('dags')))
                current = current.f_back
            details = {'schema_version': 'CompilationViolation/0.1', 'entrypoint': entrypoint,
                       'context': context, 'call_stack': frames,
                       'native_compilation_started': False, 'automatic_retry_allowed': False}
            if isinstance(fragment, dict):
                details.update(fragment=deepcopy(fragment), fragment_hash=digest(fragment))
            if isinstance(world, dict):
                details.update(world=deepcopy(world), world_hash=digest(world))
            self.first_violation = details
            if self.on_violation is not None:
                self.on_violation(deepcopy(details))
        raise UnexpectedCompilation(self.first_violation)

    def missing_dependency(self, error):
        """A cache-only miss is a stopped run, never an invitation to retry."""
        self.context['dependency_error'] = {'code': error.code, 'details': error.details}
        tb = error.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        self._trip('cache_dependency_missing', tb.tb_frame)

    def _monitor(self, code, offset):
        self._trip(self._codes[code], sys._getframe(1))

    def _profile(self, frame, event, arg):
        if event == 'call' and frame.f_code in self._codes:
            self._trip(self._codes[frame.f_code], frame)

    def __enter__(self):
        self.check()
        for module, names in ENTRYPOINTS.items():
            owner = importlib.import_module('na_pipeline.backend.' + module)
            for name in names:
                target = owner
                for part in name.split('.'):
                    target = getattr(target, part)
                self._codes[target.__code__] = module + '.' + name
        if hasattr(sys, 'monitoring'):
            for tool_id in range(5, -1, -1):
                if sys.monitoring.get_tool(tool_id) is None:
                    sys.monitoring.use_tool_id(tool_id, 'frozen-component-compilation-guard')
                    self._tool_id = tool_id
                    break
            if self._tool_id is None:
                raise RuntimeError('COMPILATION_GUARD_MONITOR_UNAVAILABLE')
            sys.monitoring.register_callback(self._tool_id, sys.monitoring.events.PY_START, self._monitor)
            for code in self._codes:
                sys.monitoring.set_local_events(self._tool_id, code, sys.monitoring.events.PY_START)
        else:
            self._previous_profile = sys.getprofile()
            if self._previous_profile is not None:
                raise RuntimeError('COMPILATION_GUARD_PROFILE_ALREADY_IN_USE')
            sys.setprofile(self._profile)
        return self

    def __exit__(self, *exc):
        if self._tool_id is not None:
            for code in self._codes:
                sys.monitoring.set_local_events(self._tool_id, code, 0)
            sys.monitoring.register_callback(self._tool_id, sys.monitoring.events.PY_START, None)
            sys.monitoring.free_tool_id(self._tool_id)
            self._tool_id = None
        else:
            sys.setprofile(self._previous_profile)
        return False

    def receipt(self):
        return {'schema_version': 'CompilationGuard/0.1', 'policy': 'reuse_only',
                'guarded_entrypoints': sorted(self._codes.values()),
                'violation_count': int(self.first_violation is not None),
                'first_violation': deepcopy(self.first_violation),
                'native_compile_allowance': 0, 'batch_search_allowance': 0,
                'static_binding_and_validation_allowed': True}
