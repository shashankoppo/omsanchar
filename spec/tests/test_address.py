import json
import random
import unittest
from pathlib import Path

from spec.reference.address import AddressError, OMAddress, parse_address


class AddressParserTests(unittest.TestCase):
    def test_conformance_vectors(self):
        vectors_path = Path(__file__).parents[1] / "conformance" / "address-vectors.json"
        vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
        for vector in vectors:
            with self.subTest(address=vector["address"]):
                if vector["valid"]:
                    parsed = parse_address(vector["address"])
                    self.assertEqual(parsed.tenant, vector["tenant"])
                    self.assertEqual(parsed.kind, vector["kind"])
                    self.assertEqual(parsed.name, vector["name"])
                    self.assertEqual(parsed.version, vector["version"])
                else:
                    with self.assertRaises(AddressError):
                        parse_address(vector["address"])

    def test_parse_and_render_examples(self):
        cases = (
            "om://acme/model/gpt-4o@v1",
            "om://research/tool/vector-search",
            "om://acme/topic/orders.v2",
        )
        for address in cases:
            with self.subTest(address=address):
                self.assertEqual(str(parse_address(address)), address)

    def test_structured_address(self):
        self.assertEqual(
            parse_address("om://tenant-1/agent/orchestrator_v2@release-3"),
            OMAddress("tenant-1", "agent", "orchestrator_v2", "release-3"),
        )

    def test_rejects_noncanonical_or_malformed_values(self):
        invalid = (
            "OM://acme/model/name",
            "om://Acme/model/name",
            "om://acme/unknown/name",
            "om://acme/model/name/child",
            "om://acme/model/name@",
            "om://acme/model/name?region=west",
            "om://acme/model/name#fragment",
            "om://acme/model/a%2fb",
            "om://acme/model/-leading",
            "om://acme/model/trailing-",
            "om://acme//name",
            " om://acme/model/name",
            "om://acme/model/name ",
            "om://" + "a" * 64 + "/model/name",
            "om://acme/model/" + "a" * 128,
            "om://acme/model/name@" + "a" * 64,
        )
        for address in invalid:
            with self.subTest(address=address):
                with self.assertRaises(AddressError):
                    parse_address(address)

    def test_deterministic_mutation_fuzz(self):
        rng = random.Random(20261025)
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789._-@/%?# "
        accepted = 0
        for _ in range(5000):
            candidate = "om://acme/model/item"
            index = rng.randrange(len(candidate))
            candidate = candidate[:index] + rng.choice(alphabet) + candidate[index + 1 :]
            try:
                parsed = parse_address(candidate)
            except AddressError:
                continue
            accepted += 1
            self.assertEqual(str(parsed), candidate)
        self.assertLess(accepted, 5000)


if __name__ == "__main__":
    unittest.main()
