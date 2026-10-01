"""Tests for the Character Registry module."""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from character_registry import (
    build_character_registry,
    save_character_registry,
    load_character_registry,
    is_character_registry_current,
    ensure_character_registry,
    _compute_script_fingerprint,
    _classify_character,
    _normalize_gender,
    _normalize_age_group,
    _compute_display_name,
    _is_group_speaker,
    CHARACTER_REGISTRY_PATH,
    VALID_GENDERS,
    VALID_AGE_GROUPS,
)


class CharacterRegistryTests(unittest.TestCase):
    """Test the character registry module."""

    def setUp(self):
        """Set up test fixtures."""
        self.test_entries = [
            {"speaker": "NARRATOR", "text": "The story begins.", "instruct": "Neutral narration."},
            {"speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "CHILD", "text": "I will train.", "instruct": "Determined child."},
            {"speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "TEEN", "text": "I am ready.", "instruct": "Confident teen."},
            {"speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "ADULT", "text": "Let us begin.", "instruct": "Mature leader."},
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT", "text": "Halt!", "instruct": "Authoritative guard."},
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT", "text": "Move along.", "instruct": "Bored guard."},
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "MIDDLE_AGED", "text": "I've seen it all.", "instruct": "World-weary veteran."},
            {"speaker": "STUDENT_GROUP_01", "gender": "UNSPECIFIED", "age_group": "TEEN", "text": "Yes, teacher!", "instruct": "Excited group."},
            {"speaker": "UNKNOWN", "gender": "UNSPECIFIED", "age_group": "UNSPECIFIED", "text": "Who goes there?", "instruct": "Mysterious voice."},
            {"speaker": "NARRATOR", "text": "The chapter ends.", "instruct": "Closing narration."},
        ]

        self.cast_names = {"ARTHUR_LEYWIN", "NARRATOR"}
        self.aliases = {}

    def test_named_single_state_character(self):
        """Test a named character with a single state."""
        entries = [
            {"speaker": "ELENA", "gender": "FEMALE", "age_group": "ADULT", "text": "Hello.", "instruct": "Warm greeting."},
        ]
        registry = build_character_registry(entries, cast_names={"ELENA"})
        char = registry["characters"]["ELENA"]
        self.assertEqual(char["character_type"], "NAMED")
        self.assertEqual(char["display_name"], "Elena")
        self.assertEqual(len(char["states"]), 1)
        state = char["states"]["FEMALE|ADULT"]
        self.assertEqual(state["gender"], "FEMALE")
        self.assertEqual(state["age_group"], "ADULT")
        self.assertEqual(state["line_indices"], [0])
        self.assertEqual(state["line_count"], 1)

    def test_named_multi_state_character(self):
        """Test a named character with multiple age states."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["ARTHUR_LEYWIN"]
        self.assertEqual(char["character_type"], "NAMED")
        self.assertEqual(len(char["states"]), 3)
        # Check each state
        self.assertIn("MALE|CHILD", char["states"])
        self.assertIn("MALE|TEEN", char["states"])
        self.assertIn("MALE|ADULT", char["states"])
        # Verify line indices
        self.assertEqual(char["states"]["MALE|CHILD"]["line_indices"], [1])
        self.assertEqual(char["states"]["MALE|TEEN"]["line_indices"], [2])
        self.assertEqual(char["states"]["MALE|ADULT"]["line_indices"], [3])

    def test_named_gender_change(self):
        """Test a named character with a gender change."""
        entries = [
            {"speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "ADULT", "text": "I am Arthur.", "instruct": "Male voice."},
            {"speaker": "ARTHUR_LEYWIN", "gender": "FEMALE", "age_group": "ADULT", "text": "I am transformed.", "instruct": "Female voice."},
        ]
        registry = build_character_registry(entries, cast_names={"ARTHUR_LEYWIN"})
        char = registry["characters"]["ARTHUR_LEYWIN"]
        self.assertEqual(len(char["states"]), 2)
        self.assertIn("MALE|ADULT", char["states"])
        self.assertIn("FEMALE|ADULT", char["states"])

    def test_background_character(self):
        """Test a background character."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["GUARD_01"]
        self.assertEqual(char["character_type"], "BACKGROUND")
        self.assertEqual(len(char["states"]), 2)
        self.assertIn("MALE|ADULT", char["states"])
        self.assertIn("MALE|MIDDLE_AGED", char["states"])
        # MALE|ADULT should have 2 lines
        self.assertEqual(char["states"]["MALE|ADULT"]["line_count"], 2)
        self.assertEqual(char["states"]["MALE|ADULT"]["line_indices"], [4, 5])

    def test_background_character_state_change(self):
        """Test a background character with age change."""
        entries = [
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT", "text": "Line 1.", "instruct": ""},
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "MIDDLE_AGED", "text": "Line 2.", "instruct": ""},
        ]
        registry = build_character_registry(entries, cast_names=set())
        char = registry["characters"]["GUARD_01"]
        self.assertEqual(char["character_type"], "BACKGROUND")
        self.assertEqual(len(char["states"]), 2)
        self.assertIn("MALE|ADULT", char["states"])
        self.assertIn("MALE|MIDDLE_AGED", char["states"])

    def test_background_character_gender_change(self):
        """Test a background character with gender change."""
        entries = [
            {"speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT", "text": "Line 1.", "instruct": ""},
            {"speaker": "GUARD_01", "gender": "FEMALE", "age_group": "ADULT", "text": "Line 2.", "instruct": ""},
        ]
        registry = build_character_registry(entries, cast_names=set())
        char = registry["characters"]["GUARD_01"]
        self.assertEqual(char["character_type"], "BACKGROUND")
        self.assertEqual(len(char["states"]), 2)
        self.assertIn("MALE|ADULT", char["states"])
        self.assertIn("FEMALE|ADULT", char["states"])

    def test_group_speaker(self):
        """Test a group speaker."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["STUDENT_GROUP_01"]
        self.assertEqual(char["character_type"], "GROUP")
        self.assertEqual(len(char["states"]), 1)
        self.assertIn("UNSPECIFIED|TEEN", char["states"])

    def test_unknown_speaker(self):
        """Test UNKNOWN speaker."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["UNKNOWN"]
        self.assertEqual(char["character_type"], "UNKNOWN")
        self.assertFalse(char.get("assignable", True))
        self.assertEqual(len(char["states"]), 1)
        self.assertIn("UNSPECIFIED|UNSPECIFIED", char["states"])

    def test_unknown_with_metadata(self):
        """Test UNKNOWN with actual gender/age metadata."""
        entries = [
            {"speaker": "UNKNOWN", "gender": "MALE", "age_group": "ADULT", "text": "Hello.", "instruct": ""},
        ]
        registry = build_character_registry(entries, cast_names=set())
        char = registry["characters"]["UNKNOWN"]
        self.assertEqual(char["character_type"], "UNKNOWN")
        self.assertFalse(char.get("assignable", True))
        self.assertIn("MALE|ADULT", char["states"])

    def test_narrator(self):
        """Test NARRATOR speaker."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["NARRATOR"]
        self.assertEqual(char["character_type"], "NARRATOR")
        self.assertEqual(char["display_name"], "Narrator")
        # Narrator should have no states
        self.assertEqual(char["states"], {})

    def test_missing_metadata_old_script(self):
        """Test handling of old scripts without gender/age_group."""
        entries = [
            {"speaker": "OLD_CHARACTER", "text": "Old line.", "instruct": "Old style."},
            {"speaker": "NARRATOR", "text": "Narration.", "instruct": "Neutral."},
        ]
        registry = build_character_registry(entries, cast_names={"OLD_CHARACTER"})
        char = registry["characters"]["OLD_CHARACTER"]
        self.assertEqual(char["character_type"], "NAMED")
        self.assertIn("UNSPECIFIED|UNSPECIFIED", char["states"])
        state = char["states"]["UNSPECIFIED|UNSPECIFIED"]
        self.assertEqual(state["gender"], "UNSPECIFIED")
        self.assertEqual(state["age_group"], "UNSPECIFIED")

    def test_line_index_tracking(self):
        """Test that line indices are correctly tracked."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        char = registry["characters"]["ARTHUR_LEYWIN"]
        # First appearance at index 1
        self.assertEqual(char["states"]["MALE|CHILD"]["first_line"], 1)
        self.assertEqual(char["states"]["MALE|CHILD"]["last_line"], 1)
        # Non-contiguous indices
        char = registry["characters"]["GUARD_01"]
        self.assertEqual(char["states"]["MALE|ADULT"]["line_indices"], [4, 5])
        self.assertEqual(char["states"]["MALE|ADULT"]["first_line"], 4)
        self.assertEqual(char["states"]["MALE|ADULT"]["last_line"], 5)
        self.assertEqual(char["states"]["MALE|MIDDLE_AGED"]["first_line"], 6)
        self.assertEqual(char["states"]["MALE|MIDDLE_AGED"]["last_line"], 6)

    def test_first_last_line_and_line_count(self):
        """Test first_line, last_line, and line_count values."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        # GUARD_01 has MALE|ADULT at indices 4,5 and MALE|MIDDLE_AGED at 6
        char = registry["characters"]["GUARD_01"]
        adult = char["states"]["MALE|ADULT"]
        self.assertEqual(adult["line_count"], 2)
        self.assertEqual(adult["first_line"], 4)
        self.assertEqual(adult["last_line"], 5)
        middle = char["states"]["MALE|MIDDLE_AGED"]
        self.assertEqual(middle["line_count"], 1)
        self.assertEqual(middle["first_line"], 6)
        self.assertEqual(middle["last_line"], 6)

    def test_registry_save_load_round_trip(self):
        """Test saving and loading the registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_registry.json")
            registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
            save_character_registry(registry, path)
            loaded = load_character_registry(path)
            self.assertEqual(loaded["version"], 1)
            self.assertEqual(loaded["book_id"], registry["book_id"])
            self.assertEqual(loaded["script_fingerprint"], registry["script_fingerprint"])
            self.assertEqual(set(loaded["characters"].keys()), set(registry["characters"].keys()))

    def test_fingerprint_match(self):
        """Test fingerprint matching for current registry."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        self.assertTrue(is_character_registry_current(registry, self.test_entries))

    def test_fingerprint_mismatch_causes_rebuild(self):
        """Test that fingerprint mismatch detects stale registry."""
        registry = build_character_registry(self.test_entries, cast_names=self.cast_names)
        # Modify entries - fingerprint should change
        modified_entries = self.test_entries + [{"speaker": "NEW", "text": "New.", "instruct": ""}]
        self.assertFalse(is_character_registry_current(registry, modified_entries))

    def test_deterministic_rebuild(self):
        """Test that same input produces equivalent registry."""
        registry1 = build_character_registry(self.test_entries, cast_names=self.cast_names)
        registry2 = build_character_registry(self.test_entries, cast_names=self.cast_names)
        # Compare everything except generated_at (timestamp)
        self.assertEqual(registry1["version"], registry2["version"])
        self.assertEqual(registry1["book_id"], registry2["book_id"])
        self.assertEqual(registry1["script_fingerprint"], registry2["script_fingerprint"])
        self.assertEqual(registry1["characters"], registry2["characters"])

    def test_ensure_character_registry_creates_when_missing(self):
        """Test that ensure_character_registry builds when missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "character_registry.json")
            with patch("character_registry.CHARACTER_REGISTRY_PATH", path):
                registry = ensure_character_registry(self.test_entries, cast_path=path.replace("character_registry.json", "cast.json"))
                self.assertTrue(os.path.exists(path))
                self.assertEqual(registry["version"], 1)

    def test_ensure_character_registry_reuses_when_current(self):
        """Test that ensure_character_registry reuses current registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "character_registry.json")
            with patch("character_registry.CHARACTER_REGISTRY_PATH", path):
                registry1 = ensure_character_registry(self.test_entries, cast_path=path.replace("character_registry.json", "cast.json"))
                time.sleep(0.01)  # Ensure timestamp would differ
                registry2 = ensure_character_registry(self.test_entries, cast_path=path.replace("character_registry.json", "cast.json"))
                # Should be the same registry (same fingerprint)
                self.assertEqual(registry1["script_fingerprint"], registry2["script_fingerprint"])

    def test_ensure_character_registry_rebuilds_when_stale(self):
        """Test that ensure_character_registry rebuilds when fingerprint changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "character_registry.json")
            with patch("character_registry.CHARACTER_REGISTRY_PATH", path):
                registry1 = ensure_character_registry(self.test_entries, cast_path=path.replace("character_registry.json", "cast.json"))
                modified_entries = self.test_entries + [{"speaker": "NEW", "text": "New.", "instruct": ""}]
                registry2 = ensure_character_registry(modified_entries, cast_path=path.replace("character_registry.json", "cast.json"))
                # Should have different fingerprint
                self.assertNotEqual(registry1["script_fingerprint"], registry2["script_fingerprint"])

    def test_classify_character(self):
        """Test character classification logic."""
        cast = {"ARTHUR_LEYWIN", "NARRATOR"}
        aliases = {"ART": "ARTHUR_LEYWIN"}
        self.assertEqual(_classify_character("NARRATOR", cast, aliases), "NARRATOR")
        self.assertEqual(_classify_character("UNKNOWN", cast, aliases), "UNKNOWN")
        self.assertEqual(_classify_character("ARTHUR_LEYWIN", cast, aliases), "NAMED")
        self.assertEqual(_classify_character("ART", cast, aliases), "NAMED")  # alias
        self.assertEqual(_classify_character("GUARD_01", cast, aliases), "BACKGROUND")
        self.assertEqual(_classify_character("STUDENT_GROUP_01", cast, aliases), "GROUP")
        self.assertEqual(_classify_character("MAN_1", cast, aliases), "BACKGROUND")  # generic

    def test_normalize_gender(self):
        """Test gender normalization."""
        self.assertEqual(_normalize_gender("MALE"), "MALE")
        self.assertEqual(_normalize_gender("male"), "MALE")
        self.assertEqual(_normalize_gender("FEMALE"), "FEMALE")
        self.assertEqual(_normalize_gender("UNSPECIFIED"), "UNSPECIFIED")
        self.assertEqual(_normalize_gender("BOY"), "UNSPECIFIED")  # invalid
        self.assertEqual(_normalize_gender(None), "UNSPECIFIED")
        self.assertEqual(_normalize_gender(""), "UNSPECIFIED")

    def test_normalize_age_group(self):
        """Test age_group normalization."""
        self.assertEqual(_normalize_age_group("CHILD"), "CHILD")
        self.assertEqual(_normalize_age_group("teen"), "TEEN")
        self.assertEqual(_normalize_age_group("YOUNG_ADULT"), "YOUNG_ADULT")
        self.assertEqual(_normalize_age_group("ADULT"), "ADULT")
        self.assertEqual(_normalize_age_group("MIDDLE_AGED"), "MIDDLE_AGED")
        self.assertEqual(_normalize_age_group("ELDERLY"), "ELDERLY")
        self.assertEqual(_normalize_age_group("AGELESS"), "AGELESS")
        self.assertEqual(_normalize_age_group("UNSPECIFIED"), "UNSPECIFIED")
        self.assertEqual(_normalize_age_group("YOUNG"), "UNSPECIFIED")  # invalid
        self.assertEqual(_normalize_age_group(None), "UNSPECIFIED")

    def test_compute_display_name(self):
        """Test display name computation."""
        self.assertEqual(_compute_display_name("NARRATOR", "NARRATOR"), "Narrator")
        self.assertEqual(_compute_display_name("UNKNOWN", "UNKNOWN"), "Unknown")
        self.assertEqual(_compute_display_name("ARTHUR_LEYWIN", "NAMED"), "Arthur Leywin")
        self.assertEqual(_compute_display_name("GUARD_01", "BACKGROUND"), "Guard 01")
        self.assertEqual(_compute_display_name("STUDENT_GROUP_01", "GROUP"), "Student Group 01")

    def test_is_group_speaker(self):
        """Test group speaker detection."""
        self.assertTrue(_is_group_speaker("STUDENT_GROUP_01"))
        self.assertTrue(_is_group_speaker("VILLAGERS_GROUP"))
        self.assertTrue(_is_group_speaker("CROWD GROUP"))
        self.assertFalse(_is_group_speaker("ARTHUR_LEYWIN"))
        self.assertFalse(_is_group_speaker("GUARD_01"))
        self.assertFalse(_is_group_speaker("NARRATOR"))

    def test_compute_script_fingerprint(self):
        """Test script fingerprint computation."""
        fp1 = _compute_script_fingerprint(self.test_entries)
        fp2 = _compute_script_fingerprint(self.test_entries)
        self.assertEqual(fp1, fp2)
        # Different entries should produce different fingerprint
        modified = self.test_entries + [{"speaker": "NEW", "text": "New."}]
        fp3 = _compute_script_fingerprint(modified)
        self.assertNotEqual(fp1, fp3)


if __name__ == "__main__":
    unittest.main()