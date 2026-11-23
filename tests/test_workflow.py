import tempfile
import unittest
from pathlib import Path
from workflow import Target, Workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "outbox.sqlite")
        self.flow = Workflow(self.db)
        self.flow.define_campaign("demo", "Hello, demo")
        self.flow.upsert_targets([Target("a", True), Target("b", True),
                                  Target("c", False), Target("d", True, True)])

    def tearDown(self):
        self.flow.close()
        self.temp.cleanup()

    def test_idempotent_plan_requires_consent(self):
        self.assertEqual(self.flow.plan("demo", 0), 2)
        self.assertEqual(self.flow.plan("demo", 0), 0)
        self.assertEqual(self.flow.summary(), {"queued": 2})

    def test_retry_and_audit(self):
        self.flow.plan("demo", 0)
        calls = []
        def flaky(code, message):
            calls.append((code, message))
            return code != "b" or calls.count(("b", "Hello, demo")) > 1
        self.assertEqual(self.flow.run(0, flaky), {"delivered": 1, "retry": 1})
        self.assertEqual(self.flow.run(59, flaky), {})
        self.assertEqual(self.flow.run(60, flaky), {"delivered": 1})
        self.assertEqual(self.flow.summary(), {"delivered": 2})
        self.assertEqual(len(self.flow.audit()), 3)

    def test_opt_out_after_plan_blocks_delivery(self):
        self.flow.plan("demo", 0)
        self.flow.upsert_targets([Target("a", False)])
        self.flow.run(0, lambda code, body: True)
        self.assertEqual(self.flow.summary(), {"delivered": 1, "skipped": 1})

    def test_retries_exhaust_to_dead(self):
        self.flow.plan("demo", 0)
        self.flow.run(0, lambda *_: False, max_attempts=2)
        self.flow.run(60, lambda *_: False, max_attempts=2)
        self.assertEqual(self.flow.summary(), {"dead": 2})

    def test_persists_across_reopen(self):
        self.flow.plan("demo", 0)
        self.flow.close()
        self.flow = Workflow(self.db)
        self.assertEqual(self.flow.summary(), {"queued": 2})

    def test_transport_exception_is_safe(self):
        self.flow.plan("demo", 0)
        def broken(*_):
            raise RuntimeError("simulated outage")
        self.flow.run(0, broken)
        self.assertEqual(self.flow.summary(), {"retry": 2})
        self.assertNotIn("simulated outage", str(self.flow.audit()))


if __name__ == "__main__":
    unittest.main()
