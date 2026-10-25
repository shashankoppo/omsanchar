import json
import unittest
from pathlib import Path

from spec.reference.envelope import EnvelopeError, validate_envelope

VECTORS = Path(__file__).parents[1] / "conformance" / "envelope-vectors.json"


class EnvelopeConformanceTests(unittest.TestCase):
    def test_conformance_vectors(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        for vector in vectors:
            with self.subTest(name=vector["name"]):
                if vector["valid"]:
                    validate_envelope(vector["envelope"])
                else:
                    with self.assertRaises(EnvelopeError):
                        validate_envelope(vector["envelope"])

    def test_relative_deadline_and_zero_cost_budget_are_valid(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        minimal = vectors[0]["envelope"]
        minimal["meta"]["deadlineMs"] = 0
        minimal["meta"]["budget"]["costLimitMicrocredits"] = 0
        validate_envelope(minimal)

    def test_deadline_must_fit_unsigned_64_bit_wire_range(self):
        vectors = json.loads(VECTORS.read_text(encoding="utf-8"))
        envelope = vectors[0]["envelope"]
        envelope["meta"]["deadlineMs"] = str(1 << 64)
        with self.assertRaises(EnvelopeError):
            validate_envelope(envelope)


if __name__ == "__main__":
    unittest.main()
