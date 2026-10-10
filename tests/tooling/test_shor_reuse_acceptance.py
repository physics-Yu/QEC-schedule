"""Static binding counts cannot hide native search or falsely fail reuse."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from basic_shor_audit import reuse_failures


class ShorReuseAcceptanceTests(unittest.TestCase):
    def test_new_interface_binding_is_allowed_only_with_zero_native_work_and_guard(self):
        stats={'geometry_cache_hits':0,'recipe_build_count':8,'strategy_compile_count':0,
               'module_stats':dict.fromkeys(('leaf_compile_count','placement_search_count','routing_search_count','frontier_search_count'),0)}
        guard={'policy':'reuse_only','violation_count':0,'native_compile_allowance':0,'batch_search_allowance':0}
        self.assertEqual(reuse_failures(stats,guard),[])
        self.assertEqual(reuse_failures(stats),['SHOR_COMPILATION_GUARD_MISSING'])
        for key in stats['module_stats']:
            stats['module_stats'][key]=1
            self.assertIn('SHOR_EXECUTION_RECOMPILED',reuse_failures(stats,guard))
            stats['module_stats'][key]=0
        guard['violation_count']=1
        self.assertIn('SHOR_COMPILATION_GUARD_MISSING',reuse_failures(stats,guard))

    def test_legacy_recipe_build_requirement_is_not_relaxed(self):
        stats={'recipe_build_count':1,'strategy_compile_count':0,
               'module_stats':dict.fromkeys(('leaf_compile_count','placement_search_count','routing_search_count','frontier_search_count'),0)}
        self.assertEqual(reuse_failures(stats),['SHOR_EXECUTION_RECOMPILED'])


if __name__=='__main__':unittest.main()
