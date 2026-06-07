"""Guardrail tests locking the contract: the AI edge-case scan must *advance*
the deterministic ranking (layer observations on top) and must never *interfere*
with it (change order, scores, tiers, or the input cards).

These are regression guards, not behaviour-driving tests: they pass against the
current code because the current code already honours the contract. They exist
so that a future edit which lets the AI leak back into the ranking fails loudly.

The Groq HTTP call is always stubbed; these tests never hit the network.
"""

from __future__ import annotations

import copy
import json
import os
import unittest
import urllib.request
from typing import Any
from unittest.mock import patch

from hatch_ranker import ai_scan
from hatch_ranker.ai_scan import Observation, scan_cards
from hatch_ranker.web import ai_scan_payload, rank_payload


def _record(ref: str, title: str, wedge: str) -> dict[str, str]:
    return {
        "ref": ref,
        "title": title,
        "one_liner": f"{title} for Shopify stores",
        "example_customer": "US DTC brands, $500K-$5M",
        "wedge": wedge,
    }


SAMPLE_RECORDS = [
    _record(
        "R-01",
        "Catalog Guard",
        "Crawls the product catalog nightly for broken links, missing images, "
        "and below-cost prices, then sends a morning fix list with an approval queue.",
    ),
    _record(
        "R-02",
        "Refund Rescue",
        "Reads every refund and exchange against a rules engine and drafts a "
        "credit-or-replace decision the merchant approves, recovering margin nightly.",
    ),
    _record(
        "R-03",
        "AR Voice Founder",
        "Generative 3D mesh, drape AR try-on, and a real-time voice clone for "
        "every PDP with zero human in the loop.",
    ),
]


class _FakeResponse:
    """Minimal context-manager stand-in for urllib's urlopen() return value."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False


def _groq_envelope(observations: list[dict[str, Any]]) -> bytes:
    """Wrap observations in the Groq chat-completions response shape."""

    content = json.dumps({"observations": observations})
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")


def _stub_groq(observations: list[dict[str, Any]]):
    """Patch the network call and the API key so scan_cards runs offline."""

    return (
        patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False),
        patch.object(
            urllib.request,
            "urlopen",
            return_value=_FakeResponse(_groq_envelope(observations)),
        ),
    )


def _ranked_cards() -> list[dict[str, Any]]:
    status, body = rank_payload({"items": copy.deepcopy(SAMPLE_RECORDS)})
    assert status == 200 and body["ok"], body
    return body["ranking"]


class ScanIsReadOnlyTests(unittest.TestCase):
    def test_scan_cards_does_not_mutate_input_cards(self) -> None:
        cards = _ranked_cards()
        before = copy.deepcopy(cards)

        env_patch, net_patch = _stub_groq(
            [{"ref": "R-01", "kind": "risk", "note": "Catalog crawl may trip API rate limits."}]
        )
        with env_patch, net_patch:
            scan_cards(cards)

        # The scan reads the cards to build its prompt; it must never write to
        # them. If this fails, the AI layer has started mutating ranking state.
        self.assertEqual(cards, before)

    def test_scan_cards_returns_only_observation_objects(self) -> None:
        cards = _ranked_cards()
        env_patch, net_patch = _stub_groq(
            [{"ref": "R-02", "kind": "opportunity", "note": "Margin-recovery framing widens the buyer set."}]
        )
        with env_patch, net_patch:
            result = scan_cards(cards)

        self.assertTrue(all(isinstance(obs, Observation) for obs in result))
        # Observation is a frozen 3-field dataclass: it cannot carry score/rank.
        self.assertEqual(
            {f for obs in result for f in vars(obs)},
            {"ref", "kind", "note"},
        )


class ScanFilteringTests(unittest.TestCase):
    def test_unknown_refs_are_dropped(self) -> None:
        cards = _ranked_cards()
        env_patch, net_patch = _stub_groq(
            [
                {"ref": "R-01", "kind": "risk", "note": "Valid observation kept."},
                {"ref": "GHOST-99", "kind": "risk", "note": "Ref not in the ranking; must be dropped."},
            ]
        )
        with env_patch, net_patch:
            result = scan_cards(cards)

        refs = {obs.ref for obs in result}
        self.assertIn("R-01", refs)
        self.assertNotIn("GHOST-99", refs)

    def test_at_most_two_observations_per_card(self) -> None:
        cards = _ranked_cards()
        env_patch, net_patch = _stub_groq(
            [
                {"ref": "R-01", "kind": "risk", "note": "First."},
                {"ref": "R-01", "kind": "risk", "note": "Second."},
                {"ref": "R-01", "kind": "risk", "note": "Third should be dropped."},
            ]
        )
        with env_patch, net_patch:
            result = scan_cards(cards)

        self.assertEqual(len([obs for obs in result if obs.ref == "R-01"]), 2)

    def test_unknown_kind_is_coerced_to_risk(self) -> None:
        cards = _ranked_cards()
        env_patch, net_patch = _stub_groq(
            [{"ref": "R-01", "kind": "catastrophe", "note": "Made-up kind."}]
        )
        with env_patch, net_patch:
            result = scan_cards(cards)

        self.assertTrue(result)
        self.assertTrue(all(obs.kind in {"risk", "opportunity"} for obs in result))


class ScanDoesNotChangeRankingTests(unittest.TestCase):
    def test_ai_scan_response_carries_no_ranking_fields(self) -> None:
        with patch(
            "hatch_ranker.web.scan_cards",
            return_value=[Observation("R-01", "risk", "A real edge case.")],
        ):
            status, body = ai_scan_payload({"ranking": [{"ref": "R-01"}]})

        self.assertEqual(status, 200)
        # The AI response channel may only contain advisory observations.
        # No score / rank / tier / order field may ride along.
        self.assertEqual(set(body), {"ok", "count", "observations"})
        for obs in body["observations"]:
            self.assertEqual(set(obs), {"ref", "kind", "note"})

    def test_ranking_is_identical_before_and_after_a_scan(self) -> None:
        before = _ranked_cards()
        snapshot = [(c["ref"], c["rank"], c["score"], c["tier"]) for c in before]
        cards_for_scan = copy.deepcopy(before)

        env_patch, net_patch = _stub_groq(
            [{"ref": before[0]["ref"], "kind": "risk", "note": "Edge case the rulebook misses."}]
        )
        with env_patch, net_patch:
            status, scan_body = ai_scan_payload({"ranking": cards_for_scan})
        self.assertEqual(status, 200)

        after = _ranked_cards()
        self.assertEqual(
            snapshot,
            [(c["ref"], c["rank"], c["score"], c["tier"]) for c in after],
        )
        # Scanning must not have mutated the cards handed to it either.
        self.assertEqual(cards_for_scan, before)
        # And the scan itself must not echo a ranking back.
        self.assertNotIn("ranking", scan_body)


if __name__ == "__main__":
    unittest.main()
