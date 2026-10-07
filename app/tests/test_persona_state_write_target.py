"""A per-state persona must reach versions[age_group] and nothing else.

`--age-group` makes a persona run describe one settled state of a character, so
its output belongs in `versions[age_group]`. It did not: `_save_generated_preview`
had no `age_group` parameter and wrote `voice_config[speaker]` unconditionally,
and the version snapshot was then taken from that already-rewritten entry. Every
state therefore landed on the character as well, which is how generating `adult`
overwrote MARO's own voice with a thirty-eight-year-old's and set its seed.

The overwrite was deferred rather than fixed while the state rows were being
built, on the reasoning that once all three states are generated every row is
correct and nothing is lost. That is true of the versions and false of the base
entry: it ends up holding whichever state ran last, and the character row then
disagrees with its own adult version.

The legacy Voices tab runs this same file with no `--age-group` and must keep
writing the base entry exactly as before, so the no-age-group case is asserted
here too rather than assumed.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP))

import generate_personas as personas  # noqa: E402


class FakeEngine:
    """Stands in for the TTS engine: writes a file, returns a path."""

    def __init__(self):
        self.calls = []

    def generate_voice_design(self, description, sample_text):
        self.calls.append((description, sample_text))
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.write(b"RIFF----WAVEfake")
        handle.close()
        return handle.name, None


def base_config():
    """A character whose own entry is the placeholder it starts life with."""
    return {"MARO": {"type": "custom", "voice": "Aiden", "description": "",
                     "ref_audio": "", "ref_text": "", "seed": -1,
                     "versions": {}}}


class StateWriteTargetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.engine = FakeEngine()

    def generate(self, config, age_group):
        return personas._save_generated_preview(
            self.tmp, self.engine, config, "MARO", "A described voice.",
            "A representative line.", book_id="book-1",
            age_group=age_group)

    # ---- the fix ----

    def test_a_state_persona_does_not_touch_the_character_entry(self):
        config = base_config()
        self.assertTrue(self.generate(config, "adult"))
        maro = config["MARO"]
        self.assertEqual("custom", maro["type"],
                         "the character's own entry was rewritten by a "
                         "single state's persona")
        self.assertEqual("Aiden", maro["voice"])
        self.assertEqual("", maro["description"])
        self.assertEqual(-1, maro["seed"])
        self.assertEqual("", maro["ref_audio"])

    def test_the_state_persona_lands_in_its_own_version(self):
        config = base_config()
        self.generate(config, "adult")
        version = config["MARO"]["versions"]["adult"]
        self.assertEqual("adult", version["age_group"])
        self.assertEqual("clone", version["type"])
        self.assertEqual("A described voice.", version["description"])
        self.assertEqual("A representative line.", version["ref_text"])
        self.assertTrue(version["ref_audio"].endswith("preview.wav"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, version["ref_audio"])))

    def test_three_states_do_not_destroy_each_other(self):
        """The real scenario: teen, then adult, then elderly, in order."""
        config = base_config()
        for band, description in (("teen", "A boy's voice."),
                                  ("adult", "A man's voice at thirty-eight."),
                                  ("elderly", "An old man's voice.")):
            personas._save_generated_preview(self.tmp, self.engine, config, "MARO",
                                             description, f"A {band} line.",
                                             book_id="book-1", age_group=band)
        versions = config["MARO"]["versions"]
        self.assertEqual({"teen", "adult", "elderly"}, set(versions))
        self.assertEqual("A boy's voice.", versions["teen"]["description"])
        self.assertEqual("A man's voice at thirty-eight.", versions["adult"]["description"])
        self.assertEqual("An old man's voice.", versions["elderly"]["description"])
        # And the character still has nothing of theirs.
        self.assertEqual("custom", config["MARO"]["type"])
        self.assertEqual("", config["MARO"]["description"])

    def test_each_state_keeps_its_own_preview(self):
        config = base_config()
        for band in ("teen", "adult", "elderly"):
            personas._save_generated_preview(self.tmp, self.engine, config, "MARO",
                                             f"The {band} voice.", f"A {band} line.",
                                             book_id="book-1", age_group=band)
        refs = {band: config["MARO"]["versions"][band]["ref_audio"]
                for band in ("teen", "adult", "elderly")}
        self.assertEqual(3, len(set(refs.values())),
                         "two states share one preview file")

    # ---- the legacy path must be untouched ----

    def test_without_an_age_group_the_base_entry_is_written_as_before(self):
        config = base_config()
        self.assertTrue(self.generate(config, None))
        maro = config["MARO"]
        self.assertEqual("clone", maro["type"])
        self.assertEqual("A described voice.", maro["description"])
        self.assertEqual("A described voice.", maro["character_style"])
        self.assertEqual("generated", maro["persona_status"])
        self.assertTrue(maro["ref_audio"].endswith("preview.wav"))
        self.assertNotEqual(-1, maro["seed"])
        self.assertEqual({}, maro.get("versions") or {},
                         "a character-level run must not invent a version")

    def test_without_an_age_group_the_seed_is_the_character_seed(self):
        config = base_config()
        self.generate(config, None)
        self.assertEqual(personas.character_voice_seed("MARO"),
                         config["MARO"]["seed"])

    # ---- failures must not half-write a state ----

    def test_a_synthesis_failure_writes_no_version_and_no_base_change(self):
        """A failed preview previously wrote `type: design` to the base.

        For a per-state run that would put a half-written state persona on the
        character AND silently skip the version the user actually asked for.
        """
        class BrokenEngine:
            def generate_voice_design(self, description, sample_text):
                raise RuntimeError("CUDA out of memory")

        config = base_config()
        result = personas._save_generated_preview(
            self.tmp, BrokenEngine(), config, "MARO", "A described voice.",
            "A line.", book_id="book-1", age_group="adult")
        self.assertFalse(result)
        self.assertEqual({}, config["MARO"]["versions"],
                         "a state version was written despite no preview")
        self.assertEqual("custom", config["MARO"]["type"],
                         "the base entry was rewritten on a failed synthesis")
        self.assertEqual("Aiden", config["MARO"]["voice"])

    def test_a_synthesis_failure_still_writes_the_base_for_a_character_run(self):
        """The legacy behaviour is preserved: a failed bulk run degrades."""

        class BrokenEngine:
            def generate_voice_design(self, description, sample_text):
                raise RuntimeError("CUDA out of memory")

        config = base_config()
        result = personas._save_generated_preview(
            self.tmp, BrokenEngine(), config, "MARO", "A described voice.",
            "A line.", book_id="book-1", age_group=None)
        self.assertFalse(result)
        self.assertEqual("design", config["MARO"]["type"])
        self.assertEqual("A described voice.", config["MARO"]["description"])

    def test_an_existing_version_survives_a_later_failed_state(self):
        config = base_config()
        self.generate(config, "adult")
        before = dict(config["MARO"]["versions"]["adult"])

        class BrokenEngine:
            def generate_voice_design(self, description, sample_text):
                raise RuntimeError("boom")

        personas._save_generated_preview(self.tmp, BrokenEngine(), config, "MARO",
                                         "A failed voice.", "A line.",
                                         book_id="book-1", age_group="elderly")
        self.assertEqual(before, config["MARO"]["versions"]["adult"])
        self.assertNotIn("elderly", config["MARO"]["versions"])

    # ---- helper ----

    def test_build_generated_entry_does_not_mutate_the_config(self):
        config = base_config()
        before = dict(config["MARO"])
        entry = personas._build_generated_entry(config, "MARO", "A voice.",
                                                "A line.", ref_audio="clone_voices/x.wav")
        self.assertEqual(before, config["MARO"],
                         "_build_generated_entry must be side-effect free; the "
                         "version snapshot reads the generated entry, not the base")
        self.assertEqual("clone", entry["type"])
        self.assertEqual("clone_voices/x.wav", entry["ref_audio"])
        self.assertNotIn("versions", entry,
                         "the snapshot filters these out, so they must not be "
                         "carried into a version and nest versions inside versions")

    def test_a_version_does_not_carry_a_nested_versions_dict(self):
        config = base_config()
        self.generate(config, "teen")
        personas._save_generated_preview(self.tmp, self.engine, config, "MARO",
                                         "The adult voice.", "An adult line.",
                                         book_id="book-1", age_group="adult")
        for band, version in config["MARO"]["versions"].items():
            with self.subTest(band=band):
                self.assertNotIn("versions", version)
                self.assertNotIn("candidates", version)


if __name__ == "__main__":
    unittest.main()