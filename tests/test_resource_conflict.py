import unittest
from qec_schedule.scheduler import ResourceLock


class ResourceLockTests(unittest.TestCase):
    def test_atomic_capacity_and_release(self):
        locks = ResourceLock({'laser': 1, 'zone': 4})
        self.assertTrue(locks.acquire({'a': {'laser': 1, 'zone': 2}}))
        self.assertFalse(locks.acquire({'b': {'laser': 1}, 'c': {'zone': 2}}))
        self.assertEqual(set(locks.owners), {'a'})
        self.assertTrue(locks.acquire({'c': {'zone': 2}}))
        self.assertFalse(locks.acquire({'d': {'zone': 1}}))
        locks.release('a')
        self.assertTrue(locks.acquire({'b': {'laser': 1}}))

    def test_unknown_and_invalid_resource(self):
        locks = ResourceLock({'laser': 1})
        self.assertFalse(locks.acquire({'a': {'unknown': 1}}))
        with self.assertRaises(ValueError):
            locks.acquire({'a': {'laser': -1}})
        with self.assertRaises(ValueError):
            ResourceLock({'laser': 0})
