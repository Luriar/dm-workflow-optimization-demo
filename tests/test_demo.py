import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from demo import Contact, prepare_batch, simulate_delivery

class BatchTests(unittest.TestCase):
    def test_consent_dedup_and_suppression(self):
        x=[Contact("a",True),Contact("a",True),Contact("b",False),Contact("c",True)]
        self.assertEqual(prepare_batch(x,{"c"}),["a"])
    def test_failure_record(self):
        self.assertEqual(simulate_delivery(["a"],{"a"}),[("a","retry_scheduled")])

if __name__ == "__main__":
    unittest.main()
