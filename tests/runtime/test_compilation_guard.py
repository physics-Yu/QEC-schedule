"""Compile entrypoints must stop before body execution, including old aliases."""
import unittest
from na_pipeline.runtime.compilation_guard import CompilationGuard, UnexpectedCompilation, ENTRYPOINTS
from na_pipeline.backend.compiled_modules import CompiledModuleLibrary
from na_pipeline.backend.physical_dag import compile_physical_dag as retained_alias
from na_pipeline.backend.enola_kernel import StrategyError
from na_pipeline.device import canonical_surface17_device


class CompilationGuardTests(unittest.TestCase):
    def test_alias_stops_before_argument_validation_and_releases_monitor(self):
        reports=[]
        guard=CompilationGuard(on_violation=reports.append)
        with self.assertRaises(UnexpectedCompilation), guard:
            retained_alias(None,None,None)
        self.assertEqual(len(reports),1)
        self.assertFalse(reports[0]['native_compilation_started'])
        self.assertEqual(reports[0]['entrypoint'],'physical_dag.compile_physical_dag')
        with self.assertRaises(UnexpectedCompilation):guard.check()
        with CompilationGuard():pass

    def test_native_materialization_is_blocked_even_if_caller_allows_it(self):
        library=CompiledModuleLibrary(canonical_surface17_device())
        with self.assertRaises(UnexpectedCompilation), CompilationGuard():
            # Invalid input would fail differently if the body began.
            library.compile_module(None,None)
        self.assertEqual(library.stats['leaf_compile_count'],0)

    def test_compile_retry_handler_cannot_swallow_violation(self):
        retried=False
        with self.assertRaises(UnexpectedCompilation), CompilationGuard():
            try:retained_alias(None,None,None)
            except Exception:retried=True
        self.assertFalse(retried)

    def test_every_guarded_entrypoint_blocks_before_body(self):
        import importlib
        for module,names in ENTRYPOINTS.items():
            for name in names:
                target=importlib.import_module('na_pipeline.backend.'+module)
                for part in name.split('.'):target=getattr(target,part)
                import inspect
                signature=inspect.signature(target)
                args=[None for p in signature.parameters.values() if p.kind in (p.POSITIONAL_ONLY,p.POSITIONAL_OR_KEYWORD)]
                kw={p.name:None for p in signature.parameters.values() if p.kind==p.KEYWORD_ONLY and p.default==p.empty}
                with self.subTest(entrypoint=module+'.'+name):
                    with self.assertRaises(UnexpectedCompilation),CompilationGuard():target(*args,**kw)

    def test_dependency_miss_keeps_cause_and_context_without_retry(self):
        guard=CompilationGuard()
        with self.assertRaises(UnexpectedCompilation),guard,guard.scope(window=7):
            try:raise StrategyError('MODULE_DEPENDENCY_MISSING','not built',key='missing',rejected=[])
            except StrategyError as error:guard.missing_dependency(error)
        self.assertEqual(guard.first_violation['context']['window'],7)
        self.assertEqual(guard.first_violation['context']['dependency_error']['details']['key'],'missing')


if __name__=='__main__':unittest.main()
