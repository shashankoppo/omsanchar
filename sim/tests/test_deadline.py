import json
import unittest
from pathlib import Path

from sim.reference.stream import DeadlineError, MonotonicDeadline, SimulatedClock

VECTORS = Path(__file__).parents[2] / "spec" / "conformance" / "deadline-vectors.json"


class DeadlineSimulationTests(unittest.TestCase):
    def test_shared_vectors_with_independent_simulator(self):
        for vector in json.loads(VECTORS.read_text(encoding="utf-8")):
            with self.subTest(name=vector["name"]):
                for wall_jump_ms in vector.get("wallClockJumpMs", [0]):
                    with self.subTest(wall_clock_jump_ms=wall_jump_ms):
                        clock = SimulatedClock(wall_clock_ns=50_000_000_000)
                        deadline = MonotonicDeadline(clock, vector["effectiveMs"])
                        clock.advance(
                            vector["elapsedMonotonicNs"],
                            wall_clock_jump_ns=wall_jump_ms * 1_000_000,
                        )
                        if "error" in vector:
                            with self.assertRaises(DeadlineError) as caught:
                                deadline.remaining_ms(clock)
                            self.assertEqual(caught.exception.code, vector["error"])
                        else:
                            self.assertEqual(deadline.remaining_ms(clock), vector["remainingMs"])

    def test_hop_local_monotonic_budgets_ignore_large_host_clock_skew(self):
        ingress_clock = SimulatedClock(wall_clock_ns=2_000_000_000_000)
        ingress_deadline = MonotonicDeadline(ingress_clock, remaining_ms=100)
        ingress_clock.advance(7_000_000, wall_clock_jump_ns=72 * 60 * 60 * 1_000_000_000)
        forwarded_ms = ingress_deadline.remaining_ms(ingress_clock)
        self.assertEqual(forwarded_ms, 93)

        downstream_clock = SimulatedClock(wall_clock_ns=-900_000_000_000_000)
        downstream_deadline = MonotonicDeadline(downstream_clock, remaining_ms=forwarded_ms)
        downstream_clock.advance(11_000_000, wall_clock_jump_ns=-45 * 24 * 60 * 60 * 1_000_000_000)

        self.assertEqual(downstream_deadline.remaining_ms(downstream_clock), 82)
        self.assertNotEqual(ingress_clock.wall_clock_ns, downstream_clock.wall_clock_ns)

    def test_remaining_wire_duration_is_rounded_down_and_never_zero(self):
        clock = SimulatedClock()
        deadline = MonotonicDeadline(clock, remaining_ms=5)
        clock.advance(999_999)
        self.assertEqual(deadline.remaining_ms(clock), 4)
        clock.advance(3_000_001)
        self.assertEqual(deadline.remaining_ms(clock), 1)
        clock.advance(1)
        with self.assertRaises(DeadlineError) as caught:
            deadline.remaining_ms(clock)
        self.assertEqual(caught.exception.code, "OS-0500")


if __name__ == "__main__":
    unittest.main()
