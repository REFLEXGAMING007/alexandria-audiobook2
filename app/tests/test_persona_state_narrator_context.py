"""Per-state narrator context must not describe the NEXT state.

A state row's persona is built from that state's own character lines plus the
narration around them. The character lines were already restricted correctly.
The narration was not, and it leaked across the boundary in both directions:

  - chapter headings are attributed to NARRATOR, so they passed the
    narrator-label filter, and they name the age of the state they open;
  - a forward window from the character's last line reached into the narration
    that sets up the NEXT state.

Measured on state-voice-test.txt, MARO's adult range is entries 50..100 while his
adult lines end at 93. Entries 94-99 narrate him turning old, and a window of 4
from entry 91 alone reached entry 95. The adult prompt therefore contained:

    Chapter 3: The Old Man at Seventy-Four
    The second winter his wife died, and Maro, who was seventy-four, did not...
    At seventy-four he still spoke clearly, which his family counted as...

next to its thirty-eight-year-old lines. Nothing errored. The model simply gets
contradictory evidence about how old the character is, and whichever reading it
picks becomes a synthesised voice. That is the failure this gates.

The fixture is the finished annotated script for state-voice-test.txt, kept
inline so the test states its own facts rather than inheriting whatever the
working copy happens to contain. Entries are built from a declared band layout,
so the boundary under test is explicit.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from generate_personas import (_collect_narrator_context,  # noqa: E402
                               _is_chapter_heading)

NARRATOR = "NARRATOR"

# MARO's bands in the finished state-voice-test.txt annotation.
#
# `young_adult` is present in the annotation and deliberately ABSENT from the
# settled states: it did not clear the trait thresholds, so the roster folds it
# into `teen`. That is a separate defect in speaker_traits, and one of the
# assertions below documents its effect here rather than hiding it.
MARO_BANDS = (
    ("teen", "teen", 4, 24),
    ("young_adult", "young_adult", 29, 47),
    ("adult", "adult", 50, 93),
    ("elderly", "elderly", 100, 147),
)

#: The settled states the roster emits, with the entry ranges it derives for them
#: from the first entry of each. Note `to_entry` is the NEXT state's start, so a
#: range always runs past its own last character line - which is the whole point.
SETTLED = ("teen", "adult", "elderly")


#: Filler used to place a band at its declared absolute index. Narration, so it
#: is collectable context rather than inert padding.
def _filler(index):
    return {"speaker": NARRATOR, "text": f"Ordinary narration, entry {index}."}


#: The transition block, at entries 94-99: everything between MARO's last adult
#: line (93) and his first elderly line (100). A per-state prompt must not see it.
TRANSITION = {
    94: "He was thirty-eight years old, and then he was not.",
    95: "Chapter 3: The Old Man at Seventy-Four",
    96: "The second winter his wife died, and Maro, who was seventy-four.",
    97: "At seventy-four he still spoke clearly.",
    98: "He walked to the mill each morning and back.",
    99: "The lane was quiet.",
}

#: Distinctive narration placed INSIDE each band, immediately after its first
#: character line.
#:
#: Note it cannot go one entry BEFORE the band: a range's lower bound is the
#: first entry of the band, and a backward window is clamped to that bound, so
#: anything before it is out of range by definition and never was available. The
#: clamp this test guards is on the FORWARD side only.
BAND_MARKER = {
    "teen": "Narration inside the teen stretch.",
    "young_adult": "Narration inside the young_adult stretch.",
    "adult": "Narration inside the adult stretch.",
    "elderly": "Narration inside the elderly stretch.",
}


def build_script():
    """A script placed at EXACT declared indices.

    Built by index rather than appended, because the whole test is about where
    the boundaries fall: an off-by-a-few fixture would put the transition block
    somewhere other than where the assertions claim, and the tests would pass for
    the wrong reason.
    """
    last_index = max(last for _band, _label, _first, last in MARO_BANDS)
    total = max(last_index, max(TRANSITION)) + 1
    entries = [_filler(index) for index in range(total)]

    for band, _label, first, last in MARO_BANDS:
        for index in range(first, last + 1):
            entries[index] = {"speaker": "MARO", "text": f"A line of his own, entry {index}.",
                              "speaker_age_group": band}
        if first + 1 <= last:
            entries[first + 1] = {"speaker": NARRATOR, "text": BAND_MARKER[band]}

    for index, text in TRANSITION.items():
        entries[index] = {"speaker": NARRATOR, "text": text}
    return entries


def range_for(index):
    """The (lo, hi) the roster derives for settled state `index`."""
    starts = [first for band, _label, first, _last in MARO_BANDS if band in SETTLED]
    return starts[index], (starts[index + 1] if index + 1 < len(starts) else len(build_script()))


SCRIPT = build_script()


class ChapterHeadingTests(unittest.TestCase):
    """A heading is metadata, not prose, even when NARRATOR-labelled."""

    def test_headings_are_recognised(self):
        for text in ("Chapter 3: The Old Man at Seventy-Four",
                     "chapter 1: the boy at sixteen",
                     "CHAPTER 12", "Part Two", "Section 4",
                     "Book III"):
            with self.subTest(text=text):
                self.assertTrue(_is_chapter_heading(text))

    def test_ordinary_narration_is_not_a_heading(self):
        for text in ("Rain fell all morning.",
                     "He was thirty-eight years old, and then he was not.",
                     "The chapter ended without a word.",
                     "She read the ledger aloud.",
                     "They counted the sheep twice."):
            with self.subTest(text=text):
                self.assertFalse(_is_chapter_heading(text),
                                 "conservative by design: only a leading "
                                 "structural token counts, so real narration "
                                 "is never dropped")


class StateBoundaryTests(unittest.TestCase):
    def test_no_state_sees_another_states_explicit_age(self):
        """Each state's context must not name a different state's age."""
        # The age each settled state is allowed to reference in narration.
        allowed = {"teen": ("sixteen",), "adult": ("thirty-eight",),
                   "elderly": ("seventy-four", "eighty")}
        for index, band in enumerate(SETTLED):
            lo, hi = range_for(index)
            context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                                entry_range=(lo, hi))
            joined = " ".join(context)
            for other, ages in allowed.items():
                if other == band:
                    continue
                for age in ages:
                    with self.subTest(state=band, leaked=other, age=age):
                        self.assertNotIn(
                            f"who was {age}", joined,
                            f"the {band} prompt was handed narration about {age}, "
                            f"which belongs to the {other} state")
                        self.assertNotIn(
                            f"Chapter {other}", joined)

    def test_the_adult_state_never_reaches_the_transition_block(self):
        """The specific regression, asserted directly.

        MARO's adult range is 50..100 and his adult lines end at 93. The window
        used to be clamped to 100, so entries 94-99 - which narrate him turning
        old - entered the prompt.
        """
        lo, hi = range_for(SETTLED.index("adult"))
        context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                            entry_range=(lo, hi))
        joined = " ".join(context)
        for line in ("Chapter 3: The Old Man at Seventy-Four",
                     "The second winter his wife died, and Maro, who was seventy-four.",
                     "At seventy-four he still spoke clearly."):
            with self.subTest(line=line[:40]):
                self.assertNotIn(line, joined)

    def test_the_heading_is_dropped_even_when_it_is_in_range(self):
        """Clamping the window is not enough on its own.

        The heading sits at entry 95, inside the range but past the last adult
        line. A reader who only fixed the clamp would still be exposed to any
        heading that landed before the character's final line.
        """
        lo, hi = range_for(SETTLED.index("adult"))
        context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                            entry_range=(lo, hi))
        self.assertNotIn("Chapter 3: The Old Man at Seventy-Four",
                         " ".join(context))

    def test_in_band_narration_is_still_collected(self):
        """The clamp must not cost real context.

        Backward context is bounded by `lo`, so narration inside the band is
        still reached. A fix that truncated to the last line would pass every
        leak test above and quietly starve the prompt.
        """
        lo, hi = range_for(SETTLED.index("adult"))
        context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                            entry_range=(lo, hi))
        self.assertTrue(any("inside the adult stretch" in line for line in context),
                        "the fix dropped the band's own narration")

    def test_a_state_whose_last_line_is_the_last_entry_keeps_everything(self):
        """No cost when there is no next state to bleed into."""
        lo, hi = range_for(SETTLED.index("elderly"))
        context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                            entry_range=(lo, hi))
        self.assertTrue(context)
        self.assertTrue(any("inside the elderly stretch" in line for line in context))

    def test_a_heading_is_dropped_even_on_the_whole_book_read(self):
        """The heading filter is unconditional, not range-scoped.

        Without a range this is the character-level persona path, which is not
        per-state - but a heading is still metadata rather than prose there, and
        "Chapter 3: The Old Man at Seventy-Four" is worse than useless in any
        prompt because it names an age.
        """
        context = _collect_narrator_context(SCRIPT, "MARO", window=4)
        joined = " ".join(context)
        self.assertNotIn("Chapter 3", joined)
        # The whole-book read still crosses every boundary: it is the
        # character-level path and is not trying to be per-state.
        self.assertIn("who was seventy-four", joined,
                      "the whole-book read must still see the whole book")

    def test_teen_absorbs_the_unsettled_young_adult_band(self):
        """Documents the OTHER boundary defect, which this fix does not address.

        `young_adult` never became a settled state, so the roster gives `teen` the
        range 4..50 and entries 29-47 come with it. Their narration is correct
        for where it sits - the band is wrong, not the collector. Fixed in
        speaker_traits, not here.
        """
        lo, hi = range_for(SETTLED.index("teen"))
        self.assertEqual((4, 50), (lo, hi))
        context = _collect_narrator_context(SCRIPT, "MARO", window=4,
                                            entry_range=(lo, hi))
        self.assertTrue(any("young_adult" in line for line in context),
                        "if this now passes, young_adult became a settled state "
                        "and the fold-in is gone - update this test")


if __name__ == "__main__":
    unittest.main()