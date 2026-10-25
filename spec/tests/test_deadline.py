import json
import unittest
from pathlib import Path

from spec.reference.deadline import DeadlineError, effective_deadline_ms, remaining_deadline_ms

VECTORS = Path(__file__).parents[1] / "conformance" / "deadline-vectors.json"


class DeadlineConformanceTests(unittest.TestCase):
    def test_shared_relative_deadline_vectors(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        for vector in vectors:
            with self.subTest(name=vector["name"]):
                effective = effective_deadline_ms(vector["requestedMs"], vector["policyMaxMs"])
                self.assertEqual(effective, vector["effectiveMs"])
                if "error" in vector:
                    with self.assertRaises(DeadlineError) as caught:
                        remaining_deadline_ms(effective, vector["elapsedMonotonicNs"])
                    self.assertEqual(caught.exception.code, vector["error"])
                else:
                    self.assertEqual(
                        remaining_deadline_ms(effective, vector["elapsedMonotonicNs"]), vector["remainingMs"]
                    )
                    for _wall_clock_jump_ms in vector.get("wallClockJumpMs", []):
                        self.assertEqual(
                            remaining_deadline_ms(effective, vector["elapsedMonotonicNs"]), vector["remainingMs"]
                        )

    def test_remaining_duration_never_increases_and_expires_at_submillisecond_boundary(self):
        for initial_ms in range(1, 33):
            previous = initial_ms
            for elapsed_ns in range(0, initial_ms * 1_000_000, 100_000):
                try:
                    current = remaining_deadline_ms(initial_ms, elapsed_ns)
                except DeadlineError as error:
                    self.assertEqual(error.code, "OS-0500")
                    break
                self.assertLessEqual(current, previous)
                previous = current
            with self.assertRaises(DeadlineError) as caught:
                remaining_deadline_ms(initial_ms, initial_ms * 1_000_000 - 1)
            self.assertEqual(caught.exception.code, "OS-0500")


if __name__ == "__main__":
    unittest.main()
