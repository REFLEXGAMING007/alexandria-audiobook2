"""Issues #609, #610, #616: the pass-1 prompt told the model to TTS-normalise
while pass-1's gate demands the source verbatim, and the pass-2 michel2 prompt
opened as a spoken-line task and models dropped the narration entries. These pin
the prompts to what the gates accept.

Pass 1 now classifies by meaning rather than by quote marks (unquoted speech may
be SPOKEN, quoted signage may be NARRATOR), so the two prompts below also pin
that: the semantic rules are present, the old mechanical split is gone, and pass 2
asks for the gender/age_group that pass 2's validator requires on every spoken
line."""
import os
import unittest

from pass_quality import validate_segment_quality

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Pass1PromptMatchesItsGate(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(HERE, "default_prompts_segment.txt"), encoding="utf-8") as h:
            self.prompt = h.read()

    def test_the_prompt_no_longer_asks_for_a_rewrite_the_gate_rejects(self):
        for normalisation in ('"Chapter I" -> "Chapter One"', '"3rd" -> "third"', '"Dr." -> "Doctor"',
                              "TTS-normalize:"):
            self.assertNotIn(normalisation, self.prompt)
        # The prompt must demand the source verbatim, because pass 1's gate
        # compares the reply against the source word for word. The shipped
        # wording is rule 11 ("Preserve the author's text exactly"); earlier
        # revisions phrased it "checked word for word against the source".
        self.assertTrue(
            "Preserve the author's text exactly" in self.prompt
            or "checked word for word against the source" in self.prompt,
            "pass 1's prompt must state that the text is preserved verbatim")

    def test_the_prompt_classifies_by_meaning_not_by_quote_marks(self):
        # The prompt used to pin a mechanical split ("everything inside quotes
        # is SPOKEN"), which is the opposite of what the run now asks for:
        # unquoted vocalizations may be SPOKEN and quoted signage may be
        # NARRATOR. That only works with the quote gate relaxed - see
        # app/config.json generation.three_pass_quoted_must_be_spoken /
        # three_pass_unquoted_must_be_narrator.
        self.assertIn("Unquoted speech can be SPOKEN", self.prompt)
        self.assertIn("Quoted text can be NARRATOR", self.prompt)
        self.assertNotIn("Split at EVERY outer quotation boundary", self.prompt)
        self.assertNotIn("printed without quotes is NARRATOR", self.prompt)
        # Both traps the mechanical rule used to trap models in are still named,
        # only with the opposite verdict.
        self.assertIn("quoted names, terms, titles, labels, or phrases", self.prompt)
        self.assertIn("Haaaaaah", self.prompt)

    def test_the_gate_rejects_the_normalised_reply_and_accepts_the_verbatim_one(self):
        # #610's shape: an ordinal expanded by the model.
        source = ('After each person, the professor read the results. '
                  '"Provisional 3rd Class. 1st, Grade C-. 2nd, Grade C+. 3rd, Grade C-." '
                  'With that said, the evaluation continued. Haaaaaah! she screamed.')
        verbatim = [{"type": "NARRATOR", "text": "After each person, the professor read the results."},
                    {"type": "SPOKEN", "text": "Provisional 3rd Class. 1st, Grade C-. 2nd, Grade C+. 3rd, Grade C-."},
                    {"type": "NARRATOR", "text": "With that said, the evaluation continued. Haaaaaah! she screamed."}]
        self.assertTrue(validate_segment_quality(source, verbatim)["passed"])
        # the unquoted scream tagged SPOKEN is exactly what the gate refuses
        split_scream = verbatim[:2] + [{"type": "NARRATOR", "text": "With that said, the evaluation continued."},
                                       {"type": "SPOKEN", "text": "Haaaaaah!"},
                                       {"type": "NARRATOR", "text": "she screamed."}]
        report = validate_segment_quality(source, split_scream)
        self.assertFalse(report["passed"])
        self.assertTrue({"quote_region_misclassified", "crosses_quote_boundary"} & {f["code"] for f in report["findings"]},
                        report["findings"])

    def test_a_quoted_term_must_be_its_own_spoken_entry(self):
        # #609's shape: the gate splits on the marks, so a quoted term is SPOKEN.
        source = 'That aura would leave something known as a "Mana Trail". It was evidence.'
        as_spoken = [{"type": "NARRATOR", "text": "That aura would leave something known as a"},
                     {"type": "SPOKEN", "text": "Mana Trail"},
                     {"type": "NARRATOR", "text": ". It was evidence."}]
        self.assertTrue(validate_segment_quality(source, as_spoken)["passed"])
        merged = [{"type": "NARRATOR", "text": 'That aura would leave something known as a "Mana Trail". It was evidence.'}]
        report = validate_segment_quality(source, merged)
        self.assertFalse(report["passed"])
        self.assertIn("mixed_quote_region", {f["code"] for f in report["findings"]})


class Pass2PromptLabelsEveryEntry(unittest.TestCase):
    def test_michel2_opens_as_an_every_entry_task_and_names_narration_first(self):
        from attribution_prompt_variants import MICHEL2_SYSTEM
        opening = MICHEL2_SYSTEM.split("\n")[0]
        self.assertTrue(opening.startswith("You label EVERY marked entry"), opening)
        # Both entry kinds are named up front, before the field rules, so a
        # model answering only the spoken lines fails visibly rather than
        # silently omitting narration.
        head = "\n".join(MICHEL2_SYSTEM.split("\n")[:12])
        self.assertIn("spoken lines", head)
        self.assertIn("narration entries", head)
        self.assertIn("Return exactly one object for every marked entry",
                      MICHEL2_SYSTEM)
        self.assertIn("Narration entries", MICHEL2_SYSTEM)
        self.assertNotIn("assign speaker names to the spoken lines", MICHEL2_SYSTEM)

    def test_michel2_asks_for_gender_and_age_group_on_spoken_lines(self):
        # #NNN: the validator requires both on every SPOKEN entry, so the
        # shipped prompt has to ask for them or every batch exhausts.
        from attribution_prompt_variants import MICHEL2_SYSTEM
        self.assertIn('{"n": 0, "speaker": "NARRATOR"}', MICHEL2_SYSTEM)
        self.assertIn('"gender"', MICHEL2_SYSTEM)
        self.assertIn('"age_group"', MICHEL2_SYSTEM)
        for value in ('"MALE"', '"FEMALE"', '"UNSPECIFIED"'):
            self.assertIn(value, MICHEL2_SYSTEM)
        for value in ('"CHILD"', '"TEEN"', '"YOUNG_ADULT"', '"ADULT"',
                      '"MIDDLE_AGED"', '"ELDERLY"', '"AGELESS"'):
            self.assertIn(value, MICHEL2_SYSTEM)
        # Narration stays metadata-free.
        self.assertIn("For narration, return:", MICHEL2_SYSTEM)


if __name__ == "__main__":
    unittest.main()
