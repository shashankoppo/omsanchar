from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from capability_token import TokenError, attenuate, mint, verify

KEY = b"K" * 32
NOW = 1_800_000_000_000


def root_token(
    *,
    resources: list[str] | None = None,
    actions: list[str] | None = None,
    budget: int = 1_000_000,
    expiry: int = NOW + 100_000,
) -> str:
    return mint(
        KEY,
        tenant="tenant-a",
        subject="agent-a",
        resources=resources or ["om://tenant-a/tool/search", "om://tenant-a/model/default"],
        actions=actions or ["invoke", "read"],
        budget_micros=budget,
        expires_unix_ms=expiry,
        token_id="test-token",
    )


class CapabilityTokenTests(unittest.TestCase):
    def test_mint_attenuate_verify_preserves_every_bound(self) -> None:
        token = root_token()
        token = attenuate(
            token,
            resources=["om://tenant-a/tool/search"],
            actions=["invoke"],
            budget_micros=500_000,
            expires_unix_ms=NOW + 50_000,
        )
        grant = verify(token, KEY, now_unix_ms=NOW, expected_tenant="tenant-a", expected_subject="agent-a")
        self.assertEqual(grant.resources, {"om://tenant-a/tool/search"})
        self.assertEqual(grant.actions, {"invoke"})
        self.assertEqual(grant.budget_micros, 500_000)
        self.assertEqual(grant.expires_unix_ms, NOW + 50_000)
        self.assertEqual(grant.depth, 1)

    def test_attenuation_rejects_widening_each_bound(self) -> None:
        original = root_token()
        widening = (
            {"resources": ["om://tenant-a/tool/search", "om://tenant-a/model/default", "om://other/tool/x"]},
            {"actions": ["invoke", "read", "admin"]},
            {"budget_micros": 1_000_001},
            {"expires_unix_ms": NOW + 100_001},
        )
        for caveat in widening:
            with self.subTest(caveat=caveat), self.assertRaises(TokenError):
                attenuate(original, **caveat)

    def test_property_random_valid_chains_never_widen(self) -> None:
        """Seeded property-style generation covers 250 independently shaped chains."""
        rng = random.Random(0x05A6C0DE)
        all_resources = [f"om://tenant-a/tool/{index}" for index in range(12)]
        all_actions = [f"action-{index}" for index in range(8)]
        for case in range(250):
            root_resources = rng.sample(all_resources, rng.randint(1, len(all_resources)))
            root_actions = rng.sample(all_actions, rng.randint(1, len(all_actions)))
            root_budget = rng.randint(1, 2_000_000)
            root_expiry = NOW + rng.randint(20_000, 200_000)
            token = root_token(
                resources=root_resources,
                actions=root_actions,
                budget=root_budget,
                expiry=root_expiry,
            )
            expected_resources = set(root_resources)
            expected_actions = set(root_actions)
            expected_budget = root_budget
            expected_expiry = root_expiry
            depth = rng.randint(1, 8)
            for _ in range(depth):
                expected_resources &= set(
                    rng.sample(sorted(expected_resources), rng.randint(0, len(expected_resources)))
                )
                expected_actions &= set(rng.sample(sorted(expected_actions), rng.randint(0, len(expected_actions))))
                expected_budget = rng.randint(0, expected_budget)
                expected_expiry = rng.randint(NOW + 1, expected_expiry)
                token = attenuate(
                    token,
                    resources=sorted(expected_resources),
                    actions=sorted(expected_actions),
                    budget_micros=expected_budget,
                    expires_unix_ms=expected_expiry,
                )
            grant = verify(token, KEY, now_unix_ms=NOW)
            with self.subTest(case=case):
                self.assertLessEqual(grant.resources, set(root_resources))
                self.assertLessEqual(grant.actions, set(root_actions))
                self.assertLessEqual(grant.budget_micros, root_budget)
                self.assertLessEqual(grant.expires_unix_ms, root_expiry)
                self.assertEqual(grant.resources, expected_resources)
                self.assertEqual(grant.actions, expected_actions)
                self.assertEqual(grant.budget_micros, expected_budget)
                self.assertEqual(grant.expires_unix_ms, expected_expiry)
                self.assertEqual(grant.depth, depth)

    def test_depth_is_bounded_at_eight(self) -> None:
        token = root_token()
        for index in range(8):
            token = attenuate(token, budget_micros=1_000_000 - index - 1)
        with self.assertRaisesRegex(TokenError, "maximum attenuation depth"):
            attenuate(token, budget_micros=999_990)
        self.assertEqual(verify(token, KEY, now_unix_ms=NOW).depth, 8)

    def test_tampering_wrong_key_context_and_expiry_fail_closed(self) -> None:
        token = root_token()
        with self.assertRaisesRegex(TokenError, "invalid token MAC"):
            verify(token, b"X" * 32, now_unix_ms=NOW)
        with self.assertRaisesRegex(TokenError, "tenant mismatch"):
            verify(token, KEY, now_unix_ms=NOW, expected_tenant="tenant-b")
        with self.assertRaisesRegex(TokenError, "subject mismatch"):
            verify(token, KEY, now_unix_ms=NOW, expected_subject="agent-b")
        with self.assertRaisesRegex(TokenError, "expired"):
            verify(token, KEY, now_unix_ms=NOW + 100_000)
        modified = attenuate(token, actions=["invoke"])
        tampered = modified[:-1] + ("A" if modified[-1] != "A" else "B")
        with self.assertRaises(TokenError):
            verify(tampered, KEY, now_unix_ms=NOW)

    def test_overflow_and_invalid_budget_widening_fail(self) -> None:
        with self.assertRaises(TokenError):
            root_token(budget=(1 << 63))
        token = root_token()
        for _ in range(9):
            token = attenuate(token, budget_micros=1_000_000)
            if _ == 7:
                with self.assertRaises(TokenError):
                    attenuate(token, budget_micros=999_999)
                break


if __name__ == "__main__":
    unittest.main()
