from __future__ import annotations

import unittest

from hatch_ranker.matching import phrase_in


class PhraseInTests(unittest.TestCase):
    def test_whole_word_positives_still_match(self) -> None:
        self.assertTrue(phrase_in("merchants lose money on returns", "return"))   # plural
        self.assertTrue(phrase_in("back-in-stock alerts", "back-in-stock"))       # hyphen phrase
        self.assertTrue(phrase_in("brands doing under $500k", "under $"))         # currency tail
        self.assertTrue(phrase_in("an ai chatbot for support", "ai"))
        self.assertTrue(phrase_in("ai-powered drafting", "ai"))                   # right hyphen ok
        self.assertTrue(phrase_in("priced at $19/mo flat", "$19/mo"))
        self.assertTrue(phrase_in("sees the sku p&l nightly", "p&l"))

    def test_substring_false_positives_are_blocked(self) -> None:
        self.assertFalse(phrase_in("the details page", "eta"))
        self.assertFalse(phrase_in("shopify admin api", "dm"))
        self.assertFalse(phrase_in("elite merchants only", "lite"))
        self.assertFalse(phrase_in("a polite reminder", "lite"))
        self.assertFalse(phrase_in("closed-loop analytics", "loop"))              # left hyphen blocked
        self.assertFalse(phrase_in("a support portal", "po"))
        self.assertFalse(phrase_in("private label brands", "vat"))
        self.assertFalse(phrase_in("a serial entrepreneur", "epr"))
        self.assertFalse(phrase_in("send branded emails", "ai"))

    def test_negated_phrases_do_not_fire(self) -> None:
        self.assertFalse(phrase_in("no manual upload needed", "manual upload"))
        self.assertFalse(phrase_in("works without a regulator packet", "regulator packet"))
        self.assertFalse(phrase_in("zero merchant uploads required", "merchant uploads"))
        self.assertTrue(phrase_in("builds the regulator packet nightly", "regulator packet"))

    def test_negation_only_looks_at_nearby_words(self) -> None:
        # Negator more than 3 words back does not suppress the match.
        self.assertTrue(
            phrase_in("not only that, it also drafts the regulator packet", "regulator packet")
        )


if __name__ == "__main__":
    unittest.main()
