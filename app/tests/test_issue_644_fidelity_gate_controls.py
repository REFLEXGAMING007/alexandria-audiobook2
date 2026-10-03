"""Issue #644: quote classification constraints are independent and optional."""
import json
import unittest
from types import SimpleNamespace

from generate_script import LLMGenParams
from pass_quality import validate_segment_quality
import three_pass_generate as tp


QUOTED_TERM = 'That aura would leave something known as a "Mana Trail". It was evidence.'
MERGED_TERM = [{"type": "NARRATOR", "text": QUOTED_TERM}]


class _Client:
    def __init__(self, entries):
        self.calls = []

        def create(**kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(entries)),
                finish_reason="stop")], usage=None)

        self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))


class FidelityGateControlTests(unittest.TestCase):
    def test_quoted_rule_can_be_disabled_without_disabling_other_checks(self):
        strict = validate_segment_quality(QUOTED_TERM, MERGED_TERM)
        self.assertFalse(strict["passed"])
        relaxed = validate_segment_quality(
            QUOTED_TERM, MERGED_TERM, quoted_must_be_spoken=False)
        self.assertTrue(relaxed["passed"], relaxed["findings"])

        dropped = [{"type": "NARRATOR", "text":
                    'That aura would leave something known as a "Mana Trail".'}]
        report = validate_segment_quality(
            QUOTED_TERM, dropped, quoted_must_be_spoken=False)
        self.assertFalse(report["passed"])
        self.assertIn("low_source_token_recall",
                      {finding["code"] for finding in report["findings"]})

    def test_unquoted_rule_can_be_disabled_independently(self):
        source = 'She said "Go." Then the unquoted cry rang out. Haaaaaah!'
        entries = [
            {"type": "NARRATOR", "text": "She said"},
            {"type": "SPOKEN", "text": "Go."},
            {"type": "NARRATOR", "text": "Then the unquoted cry rang out."},
            {"type": "SPOKEN", "text": "Haaaaaah!"},
        ]
        strict = validate_segment_quality(source, entries)
        self.assertFalse(strict["passed"])
        relaxed = validate_segment_quality(
            source, entries, unquoted_must_be_narrator=False)
        self.assertTrue(relaxed["passed"], relaxed["findings"])

    def test_auto_asks_the_model_and_does_not_rewrite_its_quoted_narrator(self):
        client = _Client(MERGED_TERM)
        params = LLMGenParams(
            max_tokens=500, segmentation="auto", quoted_must_be_spoken=False)
        out = tp.segment_chunk_adaptively(client, "m", QUOTED_TERM, params)
        self.assertEqual(MERGED_TERM, out)
        self.assertEqual(1, len(client.calls))
        system = client.calls[0]["messages"][0]["content"]
        self.assertIn("Quoted text is not required to be SPOKEN", system)
        self.assertIn("Unquoted text MUST be NARRATOR", system)

    def test_controls_change_checkpoint_identity_only_when_nondefault(self):
        default = tp.three_pass_fingerprint(
            "text", "m", 3000, LLMGenParams(segmentation="auto"))
        quoted_relaxed = tp.three_pass_fingerprint(
            "text", "m", 3000,
            LLMGenParams(segmentation="auto", quoted_must_be_spoken=False))
        unquoted_relaxed = tp.three_pass_fingerprint(
            "text", "m", 3000,
            LLMGenParams(segmentation="auto", unquoted_must_be_narrator=False))
        self.assertNotEqual(default, quoted_relaxed)
        self.assertNotEqual(default, unquoted_relaxed)
        self.assertNotEqual(quoted_relaxed, unquoted_relaxed)


class DefaultConfigMatchesSemanticPass1Tests(unittest.TestCase):
    """Pass 1 now classifies speech by meaning, not by quote marks
    (default_prompts_segment.txt): quoted signage may be NARRATOR and an
    unquoted cry may be SPOKEN. The committed defaults must accept that, so a
    fresh install does not reject exactly what the shipped prompt asks for."""

    SOURCE = ('He saw the sign. "KEEP OUT." The guard turned. '
              'Then the unquoted cry rang out. Haaaaaah—!')

    SEMANTIC = [
        {"type": "NARRATOR", "text": "He saw the sign. "},
        {"type": "NARRATOR", "text": "KEEP OUT."},
        {"type": "NARRATOR", "text": " The guard turned. "
                                     "Then the unquoted cry rang out. "},
        {"type": "SPOKEN", "text": "Haaaaaah—!"},
    ]

    def _resolved(self, generation):
        return tp.resolve_three_pass_generation_settings(
            {"generation": generation}, None)

    def test_generation_config_defaults_disable_both_quote_rules(self):
        from config_settings import GenerationConfig
        gen = GenerationConfig()
        self.assertFalse(gen.three_pass_quoted_must_be_spoken)
        self.assertFalse(gen.three_pass_unquoted_must_be_narrator)

    def test_fresh_config_resolves_to_the_semantic_gate(self):
        # No generation keys at all: the fallback must not resurrect the
        # mechanical rule.
        settings = self._resolved({})
        self.assertFalse(settings["quoted_must_be_spoken"])
        self.assertFalse(settings["unquoted_must_be_narrator"])

    def test_default_settings_accept_unquoted_speech_and_quoted_narration(self):
        settings = self._resolved({})
        report = validate_segment_quality(
            self.SOURCE, self.SEMANTIC,
            quoted_must_be_spoken=settings["quoted_must_be_spoken"],
            unquoted_must_be_narrator=settings["unquoted_must_be_narrator"])
        self.assertTrue(report["passed"], report["findings"])

    def test_default_segmentation_auto_asks_the_model(self):
        # With a quote rule relaxed, "auto" must not pre-segment by marks.
        settings = self._resolved({})
        self.assertEqual("auto", settings["segmentation"])
        entries, resolution = tp.quote_regions_decision(
            settings["segmentation"], self.SOURCE, None,
            quoted_must_be_spoken=settings["quoted_must_be_spoken"],
            unquoted_must_be_narrator=settings["unquoted_must_be_narrator"])
        self.assertIsNone(entries)
        self.assertIsNone(resolution)

    def test_explicit_true_still_restores_the_strict_mechanical_gate(self):
        settings = self._resolved({
            "three_pass_quoted_must_be_spoken": True,
            "three_pass_unquoted_must_be_narrator": True,
        })
        self.assertTrue(settings["quoted_must_be_spoken"])
        self.assertTrue(settings["unquoted_must_be_narrator"])
        report = validate_segment_quality(
            self.SOURCE, self.SEMANTIC,
            quoted_must_be_spoken=True, unquoted_must_be_narrator=True)
        self.assertFalse(report["passed"])
        self.assertTrue(
            {"quote_region_misclassified", "crosses_quote_boundary"}
            & {finding["code"] for finding in report["findings"]},
            report["findings"])

    def test_explicit_true_restores_auto_pre_segmentation(self):
        # The strict path is still reachable: both rules on, "auto" decides by
        # quote marks again.
        entries, resolution = tp.quote_regions_decision(
            "auto", QUOTED_TERM, tp.analyze_outer_quote_regions(QUOTED_TERM),
            quoted_must_be_spoken=True, unquoted_must_be_narrator=True)
        self.assertIsNotNone(entries)
        self.assertIsNotNone(resolution)


if __name__ == "__main__":
    unittest.main()
