import itertools
import random
import unittest
from na_pipeline.validation.geometry import _collision, _swept_candidates, EPS


class SweptCandidateTests(unittest.TestCase):
    def compare(self,p,q):
        exhaustive={tuple(sorted((a,b))) for a,b in itertools.combinations(p,2) if _collision(p[a],q[a],p[b],q[b])}
        broad={tuple(sorted((a,b))) for a,b in _swept_candidates(p,q) if _collision(p[a],q[a],p[b],q[b])}
        self.assertEqual(exhaustive,broad)

    def test_crossings_stationary_coincidence_and_tolerance(self):
        for speed in (1,1000,1e6):
            p={'a':[0,0],'b':[speed*(1+EPS/2),0],'c':[4,4],'d':[4,4]}
            q={**p,'a':[speed,0]}
            self.compare(p,q)
        self.compare({'a':[0,0],'b':[1,1]},{'a':[1,1],'b':[0,0]})

    def test_seeded_differential_against_exhaustive_predicate(self):
        r=random.Random(0)
        for _ in range(500):
            p={str(i):[r.randrange(-10,11),r.randrange(-10,11)] for i in range(25)}
            q={k:([r.randrange(-10,11),r.randrange(-10,11)] if r.random()<.3 else v[:]) for k,v in p.items()}
            self.compare(p,q)

if __name__=='__main__':unittest.main()
