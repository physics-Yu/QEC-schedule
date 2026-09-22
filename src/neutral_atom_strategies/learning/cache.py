"""Bounded exact-state candidate memoization; no approximate physics cache."""
from collections import OrderedDict
from copy import deepcopy
from hashlib import sha256
from time import perf_counter

from neutral_atom_env.replay.serializer import canonical_json
from .adapter import DecisionEnv


class ExactCandidateCache:
    def __init__(self,capacity=128):
        self.capacity=capacity
        self.entries=OrderedDict()
        self.hits=0
        self.misses=0

    def provider(self,delegate):
        cache=self
        class Provider:
            def build(self,env,terminal):
                start=perf_counter()
                key=sha256((env.snapshot()+canonical_json(terminal)+canonical_json(vars(delegate))).encode()).hexdigest()
                if key in cache.entries:
                    cache.hits+=1
                    choices,log=cache.entries.pop(key)
                    cache.entries[key]=(choices,log)
                    result=deepcopy(log)
                    result.update(cache_hit=True,planning_seconds=perf_counter()-start)
                    return list(choices),result
                cache.misses+=1
                choices,log=delegate.build(env,terminal)
                # A timeout depends on machine load: never memoize it as a fact.
                if not log.get('budget_exhausted'):
                    cache.entries[key]=(tuple(choices),deepcopy(log))
                    while len(cache.entries)>cache.capacity:cache.entries.popitem(last=False)
                log=dict(log,cache_hit=False,planning_seconds=perf_counter()-start)
                return choices,log
        return Provider()


def cached_environment(initial,config,cache,checkpoint=None):
    env=DecisionEnv.restore(checkpoint) if checkpoint else DecisionEnv(initial,config)
    env._provider=cache.provider(env._provider)
    return env
