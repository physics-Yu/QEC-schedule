import unittest
from na_pipeline.runtime.frozen_frontier import join_recipes
from na_pipeline.backend.enola_kernel import StrategyError


def recipe(prefix):
    return {'modules': [dict(id='module:0', dependencies=[], source_ids=[prefix+'0'], dag={}),
                        dict(id='module:1', dependencies=['module:0'], source_ids=[prefix+'1'], dag={})]}


class FrozenFrontierTests(unittest.TestCase):
    def test_interleave_retains_each_original_batch_and_dependencies(self):
        graphs = [recipe('a'), recipe('b')]
        dags = [{'nodes': [{'id': s} for s in ['a0','a1']]}, {'nodes': [{'id': s} for s in ['b0','b1']]}]
        joint = join_recipes(graphs, dags)
        self.assertEqual([m['source_ids'] for m in joint['modules']], [['a0'],['b0'],['a1'],['b1']])
        self.assertEqual(joint['modules'][2]['dependencies'], ['component:0/module:0'])
        self.assertEqual(graphs[0], recipe('a'))
        self.assertFalse(joint['internal_batches_changed'])

    def test_missing_source_is_rejected(self):
        with self.assertRaisesRegex(StrategyError, 'FRONTIER_SOURCE_COVERAGE'):
            join_recipes([recipe('a')], [{'nodes': [{'id':'a0'},{'id':'a1'},{'id':'a2'}]}])

    def test_source_alias_is_rejected(self):
        with self.assertRaisesRegex(StrategyError, 'FRONTIER_SOURCE_COVERAGE'):
            join_recipes([recipe('a'),recipe('a')], [{'nodes':[{'id':'a0'},{'id':'a1'}]}]*2)


if __name__ == '__main__': unittest.main()
