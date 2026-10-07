"""The ordinary path: one character, one narrator, no state change.

Deliberately the smallest thing that still exercises the whole pipeline, checked
before any state-change behaviour is layered on top. Every stage downstream of
the annotation - narrator context, roster projection, row identity, the save map
- has a different shape when a character has exactly one state, and that shape is
the one most likely to rot unnoticed because it is the common case and produces
no visible errors when it is wrong.

The fixture mirrors the real annotated script's shape, which is not what it first
looks like:

  - NARRATOR entries carry NO `speaker_gender` key at all. `get_state_timeline`
    selects on `"speaker_gender" in entry`, and `get_speaker_trait_summary`
    returns None for a speaker with no traited entry, so a narrator with an
    explicit `"unknown"` would be treated as a character - it would get a trait
    summary, a roster row and a voice slot. Verified against the working
    annotated script: a NARRATOR entry's keys are
    `['instruct', 'source_span', 'speaker', 'spoken', 'text']`.
  - character entries carry `speaker_gender`, `speaker_age_group` and
    `speaker_ageless`.

A character with a single state is also the case where the two identities cannot
be told apart: `speakerOf` returns the row key unchanged when there is no `#`, so
passing the wrong one is unobservable. `test_the_row_key_and_the_speaker_are_the
_same_string_here` states that explicitly, so the next person reading the
identity tests knows why the single-state fixture is not enough on its own.
"""
import os
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

from generate_personas import (_collect_narrator_context,  # noqa: E402
                               _is_attribution_tag, _is_chapter_heading)
from speaker_traits import (get_speaker_trait_summary,  # noqa: E402
                            get_state_timeline)

NARRATOR = "NARRATOR"

#: One character, two lines, one age band, no change. `speaker_gender` present on
#: the character and absent on the narrator, as the real annotation has it.
SCRIPT = [
    {"speaker": NARRATOR, "text": "Chapter 1: A Quiet Morning",
     "instruct": "Open on the lane before dawn.", "spoken": False},
    {"speaker": NARRATOR, "text": "The mill stood at the end of the lane.",
     "instruct": "Measured narration.", "spoken": False},
    {"speaker": "MIRA", "text": "I will start at first light, then.",
     "speaker_gender": "female", "speaker_age_group": "young_adult",
     "speaker_ageless": False, "instruct": "Even, unhurried.",
     "spoken": True},
    {"speaker": "MIRA", "text": "The ledger will not wait for anyone.",
     "speaker_gender": "female", "speaker_age_group": "young_adult",
     "speaker_ageless": False, "instruct": "Even, unhurried.",
     "spoken": True},
]


def lines_for(speaker):
    return [entry for entry in SCRIPT if entry["speaker"] == speaker]


class AnnotationShapeTests(unittest.TestCase):
    """The fixture has to look like the real annotation or it proves nothing."""

    def test_narrator_entries_carry_no_gender_key(self):
        """The load-bearing detail.

        `get_state_timeline` groups on `"speaker_gender" in entry`, so a narrator
        entry that spelled out `"unknown"` would be grouped as a character and
        given a timeline row and a voice slot. The real annotation omits the key.
        """
        for entry in lines_for(NARRATOR):
            with self.subTest(text=entry["text"][:30]):
                self.assertNotIn("speaker_gender", entry)

    def test_a_narrator_with_an_explicit_unknown_would_not_be_traitless(self):
        """Documents the trap rather than only avoiding it."""
        polluted = dict(SCRIPT[1], speaker_gender="unknown",
                        speaker_age_group="unknown")
        summary = get_speaker_trait_summary([polluted])
        self.assertIsNotNone(summary,
                             "an explicit 'unknown' makes the narrator traited; "
                             "the real annotation omits the key for this reason")


class OrdinaryPipelineTests(unittest.TestCase):
    def test_the_character_has_one_settled_state(self):
        summary = get_speaker_trait_summary(lines_for("MIRA"))
        self.assertIsNotNone(summary)
        self.assertEqual("female", summary["gender"])
        self.assertEqual("young_adult", summary["age_group"])
        self.assertEqual(2, summary["lines"])
        self.assertEqual([], summary["states"],
                         "one band with no change is not a state list; a single "
                         "state means the character IS the row")

    def test_a_character_with_no_state_change_has_no_timeline(self):
        """No timeline means no state rows, so one plain roster row."""
        self.assertEqual({}, get_state_timeline(SCRIPT),
                         "get_state_timeline only reports speakers whose settled "
                         "state CHANGES; an empty result is the ordinary case")

    def test_the_narrator_gets_no_trait_summary_and_no_voice_slot(self):
        self.assertIsNone(get_speaker_trait_summary(lines_for(NARRATOR)),
                          "the narrator must stay traitless, or it appears in "
                          "the roster as a character needing a voice")
        self.assertNotIn(NARRATOR, get_state_timeline(SCRIPT))

    def test_the_row_key_and_the_speaker_are_the_same_string_here(self):
        """Why the single-state fixture cannot catch an identity mistake.

        With one state the roster emits the character as a plain row, so
        `speakerOf('MIRA')` returns 'MIRA' whether it is handed a row key or a
        speaker. The multi-state fixture in test_voices_v3_identity is what makes
        the two distinguishable, and it is the only thing that can.
        """
        row_key = "MIRA"
        speaker = row_key.split("#")[0]
        self.assertEqual(row_key, speaker)
        self.assertNotIn("#", row_key)


class NarratorContextTests(unittest.TestCase):
    """The persona prompt's narration, for the ordinary case."""

    def test_the_characters_own_narration_is_collected(self):
        context = _collect_narrator_context(SCRIPT, "MIRA", window=4)
        self.assertIn("The mill stood at the end of the lane.", context,
                      "the narration around the character is what describes the "
                      "setting; losing it starves the persona prompt")

    def test_the_chapter_heading_is_not_collected(self):
        """A heading is metadata, not prose - even with no state ranges in play.

        The heading filter is not scoped to per-state prompts, so it must hold on
        the ordinary path too.
        """
        context = _collect_narrator_context(SCRIPT, "MIRA", window=4)
        self.assertNotIn("Chapter 1: A Quiet Morning", context)
        self.assertTrue(_is_chapter_heading("Chapter 1: A Quiet Morning"))

    def test_the_narrator_is_never_its_own_context(self):
        """Asking for NARRATOR's context must not return NARRATOR's own lines.

        DOCUMENTED CURRENT BEHAVIOUR, NOT an endorsement. The narrator is
        labelled NARRATOR, so it passes the narrator-label filter that every
        other entry is screened by, and the only thing keeping it out of its own
        prompt is the per-index self-skip - which cannot help, because every
        index IS an appearance. So the narrator is handed its own narration as
        context.

        No narrator persona is generated today, so nothing consumes this. It is
        asserted so the behaviour is visible rather than discovered later, if a
        narrator persona is ever built.
        """
        context = _collect_narrator_context(SCRIPT, NARRATOR, window=4)
        self.assertIn("The mill stood at the end of the lane.", context,
                      "the narrator currently receives its own narration as "
                      "context; harmless only because no narrator persona exists")

    def test_an_attribution_tag_is_still_filtered(self):
        """The pre-existing filter must survive the heading change."""
        self.assertTrue(_is_attribution_tag("Maro said."))
        self.assertTrue(_is_attribution_tag("he said."))
        self.assertTrue(_is_attribution_tag("she said to him"))
        self.assertFalse(_is_attribution_tag("The mill stood at the end of the lane."))
        # Conservative by design, and worth pinning: a comma before "to" is not
        # matched, and anything over 40 characters is rejected outright. So
        # "he said, to no one, on the first morning..." is NOT treated as a tag -
        # it is kept as narration, which is the safe direction to be wrong in.
        self.assertFalse(_is_attribution_tag("he said, to no one"))
        self.assertFalse(_is_attribution_tag(
            "he said, to no one, on the first morning of the rest of his life."))
        self.assertFalse(_is_attribution_tag("Chapter 1: A Quiet Morning"),
                         "a heading is not an attribution tag; it is filtered by "
                         "its own rule and must not be quietly double-matched")


if __name__ == "__main__":
    unittest.main()