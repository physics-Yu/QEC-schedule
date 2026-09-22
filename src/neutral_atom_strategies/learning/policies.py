"""Untrained controls for adapter acceptance; not production greedy policies."""
import random


class RandomPolicy:
    def __init__(self,seed=0):self.rng=random.Random(seed)

    def __call__(self,observation):
        choices=observation['candidates']
        return self.rng.choice(choices)['id'] if choices else None

    def state_dict(self):
        return {'kind':'random','rng':self.rng.getstate()}

    def load_state_dict(self,state):
        if state['kind']!='random':raise ValueError('Wrong policy checkpoint kind')
        def tuples(value):
            return tuple(tuples(v) for v in value) if isinstance(value,(list,tuple)) else value
        self.rng.setstate(tuples(state['rng']))


class LocalCostPolicy:
    """Independent myopic control: validated service time per effected gate."""
    def __call__(self,observation):
        choices=observation['candidates']
        if not choices:return None
        return min(choices,key=lambda c:(c['duration_us']/max(1,len(c['gate_ids'])),-len(c['gate_ids']),c['id']))['id']
