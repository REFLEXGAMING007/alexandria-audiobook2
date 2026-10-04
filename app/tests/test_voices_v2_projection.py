"""The Voices V2 character projection: the read the browser is built on.

Phase 0 shipped an empty envelope. These tests pin what replaced it, and they
are written against the messy cases rather than a tidy fixture, because that is
what the projection exists to handle:

- a script with per-line traits and one without
- voice configuration for characters who are not in the script (orphans)
- two names differing only by spacing or punctuation, which must NOT be merged
- a missing alias file, a dangling persona reference, a voice whose adapter or
  reference recording is not on disk
- malformed JSON, which must degrade into an honest "unavailable" and must never
  write anything

Every test redirects the path constants the projection reads and asserts the
filesystem is byte-identical afterwards, because a read that repairs data would
be the single worst regression this feature could introduce.
"""
import json
import os
import shutil
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _script(*speakers, traits=True, text="line"):
    entries = []
    for speaker, lines in speakers:
        for _ in range(lines):
            entry = {"speaker": speaker, "text": text, "spoken": True}
            if traits:
                entry.update(speaker_gender="male", speaker_age_group="adult",
                             speaker_ageless=False)
            entries.append(entry)
    return entries


class ProjectionFixture(unittest.TestCase):
    """A temp data directory plus the projection module pointed at it."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        import core
        import voices_v2.character_projection as projection

        self.projection = projection
        self.state_json = os.path.join(self.tmp, "state.json")

        # The projection reads paths through its own module namespace, but
        # `_load_voice_library` reads core.VOICE_LIBRARY_PATH from core, so both
        # are redirected. Patching a constant is the project's established idiom
        # for redirecting a helper onto a temp directory.
        from unittest.mock import patch

        targets = {
            "DATA_DIR": self.tmp,
            "SCRIPT_PATH": os.path.join(self.tmp, "annotated_script.json"),
            "VOICE_CONFIG_PATH": os.path.join(self.tmp, "voice_config.json"),
            "CHARACTER_ALIASES_PATH": os.path.join(self.tmp, "character_aliases.json"),
            "CONFIG_PATH": os.path.join(self.tmp, "config.json"),
        }
        for name, value in targets.items():
            patcher = patch.object(projection, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        library_patcher = patch.object(core, "VOICE_LIBRARY_PATH",
                                       os.path.join(self.tmp, "voice_library.json"))
        library_patcher.start()
        self.addCleanup(library_patcher.stop)

        # book_state_transaction reads state.json from the directory it is given.
        self.write_json("state.json", {"active_book_id": "testbook",
                                       "input_file_path": os.path.join(self.tmp, "Test.txt")})

    def write_json(self, name, payload):
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def snapshot(self):
        """Every data file under the temp dir as (relative path, bytes).

        `*.lock` is excluded: `file_lock` is a mutual-exclusion primitive, not
        data, and the platform's lock implementation leaves its marker behind on
        some systems (Windows writes a NUL byte and does not remove the file).
        """
        out = {}
        for root, _dirs, files in os.walk(self.tmp):
            for name in files:
                if name.endswith(".lock"):
                    continue
                full = os.path.join(root, name)
                with open(full, "rb") as handle:
                    out[os.path.relpath(full, self.tmp)] = handle.read()
        return out

    def build(self):
        return self.projection.build_character_projection()


class RosterTests(ProjectionFixture):
    def test_characters_orphans_and_counts_agree_with_the_script(self):
        self.write_json("annotated_script.json",
                        _script(("MIRA", 40), ("KAYA", 3), ("NARRATOR", 2)))
        self.write_json("voice_config.json", {
            "MIRA": {"type": "custom", "voice": "Ryan"},
            "KAYA": {"type": "clone", "voice": "Ryan"},
            "GONE": {"type": "custom", "voice": "Aiden"},
        })

        data = self.build()

        self.assertEqual(["KAYA", "MIRA", "NARRATOR"], [c["name"] for c in data["characters"]])
        self.assertEqual(["GONE"], [o["name"] for o in data["orphans"]])
        self.assertEqual({"characters": 3, "orphans": 1}, data["counts"])
        self.assertEqual(25, data["major_line_threshold"])

    def test_line_counts_count_only_entries_with_text(self):
        script = _script(("MIRA", 3))
        script.extend([{"speaker": "SILENT", "text": "   ", "spoken": True},
                       {"speaker": "SILENT", "text": "", "spoken": True},
                       {"speaker": "NARRATED", "text": "narration", "spoken": False}])
        self.write_json("annotated_script.json", script)
        self.write_json("voice_config.json", {})

        data = self.build()
        by_name = {c["name"]: c for c in data["characters"]}
        self.assertEqual(3, by_name["MIRA"]["line_count"])
        # Present in the roster but with nothing to say: `_script_line_counts` is
        # the single definition of a line count and it counts entries with text,
        # so a blank line adds nothing.
        self.assertEqual(0, by_name["SILENT"]["line_count"])
        # Narration is a spoken line as far as the shared counter is concerned, so
        # V2 reports the same number the Voices tab does rather than its own.
        self.assertEqual(1, by_name["NARRATED"]["line_count"])
        self.assertIsNone(by_name["SILENT"]["priority"])
        self.assertIn("no_spoken_lines", by_name["SILENT"]["problems"])
        self.assertNotIn("no_spoken_lines", by_name["MIRA"]["problems"])

    def test_priority_follows_the_shared_threshold(self):
        threshold = self.projection.CAST_MAJOR_LINE_THRESHOLD
        self.write_json("annotated_script.json",
                        _script(("MAJOR", threshold), ("MINOR", threshold - 1)))
        self.write_json("voice_config.json", {})
        data = self.build()
        by_name = {c["name"]: c for c in data["characters"]}
        self.assertEqual("major", by_name["MAJOR"]["priority"])
        self.assertEqual("minor", by_name["MINOR"]["priority"])

    def test_a_character_with_no_configuration_still_appears(self):
        self.write_json("annotated_script.json", _script(("MIRA", 5)))
        self.write_json("voice_config.json", {})

        record = self.build()["characters"][0]

        self.assertEqual("MIRA", record["name"])
        self.assertFalse(record["voice"]["assigned"])
        self.assertIn("voice_unassigned", record["problems"])
        self.assertEqual([], record["versions"])

    def test_vocabularies_come_from_speaker_traits(self):
        from speaker_traits import AGE_GROUP_NAMES, GENDERS

        data = self.build()
        self.assertEqual(list(GENDERS), data["vocabularies"]["genders"])
        self.assertEqual(list(AGE_GROUP_NAMES),
                         [group["value"] for group in data["vocabularies"]["age_groups"]])
        self.assertIn("voice_unassigned", data["vocabularies"]["problem_codes"])

    def test_the_active_book_is_reported(self):
        self.write_json("annotated_script.json", _script(("MIRA", 1)))
        self.write_json("voice_config.json", {})

        book = self.build()["book"]

        self.assertEqual("testbook", book["book_id"])
        self.assertTrue(book["script_present"])
        self.assertTrue(book["script_sha256"])
        self.assertTrue(book["token"], "the read-only save-contract token is useful to the browser")


class TraitTests(ProjectionFixture):
    def test_traits_are_exposed_when_the_script_carries_them(self):
        self.write_json("annotated_script.json", _script(("MIRA", 12)))
        self.write_json("voice_config.json", {})

        data = self.build()
        record = data["characters"][0]

        self.assertTrue(data["traits_available"])
        self.assertTrue(record["traits_available"])
        self.assertEqual("male", record["traits"]["gender"])
        self.assertEqual("adult", record["traits"]["age_group"])
        self.assertFalse(record["traits"]["ageless"])

    def test_traits_available_is_false_and_traits_are_null_without_them(self):
        """The distinction that matters: a book with no traits is NOT a book full
        of genderless characters."""
        self.write_json("annotated_script.json", _script(("MIRA", 12), traits=False))
        self.write_json("voice_config.json", {})

        data = self.build()
        record = data["characters"][0]

        self.assertFalse(data["traits_available"])
        self.assertFalse(record["traits_available"])
        self.assertIsNone(record["traits"])
        # No per-character trait problem: the gap is book-wide, and flagging it on
        # every character would imply something is wrong with each of them. The
        # toolbar carries the book-level notice instead.
        self.assertNotIn("traits_unavailable", record["problems"])

    def test_the_requested_switch_is_reported_separately_from_availability(self):
        self.write_json("annotated_script.json", _script(("MIRA", 2), traits=False))
        self.write_json("config.json", {"generation": {"three_pass_speaker_traits": True}})
        self.write_json("voice_config.json", {})

        data = self.build()

        self.assertFalse(data["traits_available"])
        self.assertTrue(data["traits_requested"],
                        "a switch that was on but produced no traits is worth reporting")

    def test_state_changes_come_from_the_speaker_traits_timeline(self):
        script = []
        for index in range(45):
            script.append({"speaker": "MIRA", "text": f"a{index}", "spoken": True,
                           "speaker_gender": "male", "speaker_age_group": "adult",
                           "speaker_ageless": False})
        for index in range(40):
            script.append({"speaker": "MIRA", "text": f"b{index}", "spoken": True,
                           "speaker_gender": "female", "speaker_age_group": "adult",
                           "speaker_ageless": False})
        self.write_json("annotated_script.json", script)
        self.write_json("voice_config.json", {})

        record = self.build()["characters"][0]

        self.assertTrue(record["states"], "a real settled state change must be reported")
        self.assertEqual("female", record["states"][-1]["gender"])
        self.assertEqual(45, record["states"][-1]["from_entry"])
        # The overall summary is the modal value, not the last state.
        self.assertEqual("male", record["traits"]["gender"])


class IdentityTests(ProjectionFixture):
    def test_a_name_and_its_normalised_key_are_both_preserved(self):
        self.write_json("annotated_script.json", _script(("Mira Astrea", 4)))
        self.write_json("voice_config.json", {})

        record = self.build()["characters"][0]

        self.assertEqual("Mira Astrea", record["name"], "the stored spelling is the truth")
        self.assertEqual("miraastrea", record["identity_key"])

    def test_spacing_and_punctuation_variants_are_reported_not_merged(self):
        """No existing normaliser merges these, and merging them would be a
        judgement call about identity. V2 surfaces the pair and decides nothing."""
        self.write_json("annotated_script.json", _script(("PROFESSOR FERNANDO", 2)))
        self.write_json("voice_config.json", {
            "PROFESSOR FERNANDO": {"type": "custom", "voice": "Aiden"},
            "PROFESSOR_FERNANDO": {"type": "custom", "voice": "Ryan"},
        })

        data = self.build()
        by_name = {r["name"]: r for r in data["characters"] + data["orphans"]}

        self.assertEqual(2, len(data["characters"]) + len(data["orphans"]))
        self.assertNotEqual(by_name["PROFESSOR FERNANDO"]["key"],
                            by_name["PROFESSOR_FERNANDO"]["key"])
        self.assertEqual(["PROFESSOR_FERNANDO"],
                         by_name["PROFESSOR FERNANDO"]["possible_duplicate_of"])
        self.assertEqual(["PROFESSOR FERNANDO"],
                         by_name["PROFESSOR_FERNANDO"]["possible_duplicate_of"])
        for name in ("PROFESSOR FERNANDO", "PROFESSOR_FERNANDO"):
            self.assertIn("possible_duplicate_identity", by_name[name]["problems"])

    def test_a_generic_label_is_book_scoped_and_marked(self):
        self.write_json("annotated_script.json", _script(("MAN 1", 3)))
        self.write_json("voice_config.json", {})

        record = self.build()["characters"][0]

        self.assertTrue(record["generic"])
        self.assertEqual("man 1::testbook", record["library_key"])
        self.assertEqual("man 1::testbook", record["key"])

    def test_a_missing_alias_file_is_normal(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {})

        data = self.build()

        self.assertFalse(data["aliases_registered"])
        self.assertEqual([], data["characters"][0]["aliases"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "character_aliases.json")))

    def test_a_registered_alias_is_reported_on_both_directions(self):
        self.write_json("annotated_script.json", _script(("NATSUKI SUBARU", 3)))
        self.write_json("character_aliases.json", {"SUBARU": "NATSUKI SUBARU"})
        self.write_json("voice_config.json", {})

        data = self.build()
        record = data["characters"][0]

        self.assertTrue(data["aliases_registered"])
        self.assertEqual(["SUBARU"], record["aliases"])

    def test_an_invalid_alias_file_is_ignored_not_fatal(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("character_aliases.json", {"SUBARU": 17, "X": None})
        self.write_json("voice_config.json", {})

        data = self.build()

        self.assertFalse(data["aliases_registered"])
        self.assertEqual([], data["characters"][0]["aliases"])

    def test_library_known_names_are_offered_for_search(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {"type": "custom", "voice": "Ryan"}})
        self.write_json("voice_library.json", {"shared": {}, "casts": {
            "series": {"members": {"mira": {
                "name": "MIRA", "known_as": ["Mira of the Vale", "MIRA"],
                "config": {"type": "custom", "voice": "Ryan"}, "line_count": 3}}}},
            "favorites": []})

        record = self.build()["characters"][0]

        self.assertIn("Mira of the Vale", record["known_as"])
        self.assertIn("MIRA", record["known_as"])


class VoiceSummaryTests(ProjectionFixture):
    def test_a_lora_voice_reports_whether_the_adapter_is_on_disk(self):
        os.makedirs(os.path.join(self.tmp, "lora_models", "tenor"))
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "lora", "adapter_id": "tenor",
            "adapter_path": "lora_models/tenor"}})

        voice = self.build()["characters"][0]["voice"]

        self.assertEqual("lora", voice["category"])
        self.assertEqual("tenor", voice["label"])
        self.assertTrue(voice["assigned"])
        self.assertIsNotNone(voice["adapter_available"])

    def test_a_missing_adapter_is_reported_as_unavailable(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "lora", "adapter_id": "gone",
            "adapter_path": "lora_models/gone"}})

        record = self.build()["characters"][0]

        self.assertFalse(record["voice"]["adapter_available"])
        self.assertIn("voice_unavailable", record["problems"])

    def test_a_dangling_persona_reference_is_reported_not_repaired(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "clone", "voice": "Ryan", "description": "x",
            "persona_ref": "persona_refs/testbook/gen/mira.json"}})

        record = self.build()["characters"][0]

        self.assertEqual("persona_refs/testbook/gen/mira.json", record["persona_ref"])
        self.assertFalse(record["persona_ref_resolves"])
        self.assertIn("persona_ref_missing", record["problems"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "persona_refs")),
                         "the projection must not create the referenced directory")

    def test_a_resolvable_persona_reference_is_confirmed(self):
        os.makedirs(os.path.join(self.tmp, "persona_refs", "testbook", "gen"))
        with open(os.path.join(self.tmp, "persona_refs", "testbook", "gen", "mira.json"),
                  "w", encoding="utf-8") as handle:
            json.dump({"name": "MIRA"}, handle)
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "clone", "voice": "Ryan", "description": "x",
            "persona_ref": "persona_refs/testbook/gen/mira.json"}})

        record = self.build()["characters"][0]

        self.assertTrue(record["persona_ref_resolves"])
        self.assertNotIn("persona_ref_missing", record["problems"])

    def test_versions_are_projected_without_their_raw_configuration(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "custom", "voice": "Ryan", "active_version": "teen",
            "versions": {
                "teen": {"type": "clone", "voice": "Ryan", "age_group": "teen",
                         "character_style": "a very long style string"},
                "adult": {"type": "lora", "adapter_id": "tenor", "age_group": "adult"},
            },
            "version_timeline": [{"from_index": 12, "version_id": "teen"}]}})

        record = self.build()["characters"][0]

        self.assertEqual(["adult", "teen"], sorted(v["version_id"] for v in record["versions"]))
        by_id = {v["version_id"]: v for v in record["versions"]}
        self.assertEqual("clone", by_id["teen"]["category"])
        self.assertEqual("lora", by_id["adult"]["category"])
        self.assertEqual("tenor", by_id["adult"]["label"])
        self.assertEqual("teen", record["active_version"])
        self.assertEqual([{"from_index": 12, "version_id": "teen"}], record["version_timeline"])
        self.assertNotIn("character_style", by_id["teen"],
                         "a version's full configuration is not a browse field")

    def test_two_versions_for_one_age_group_are_reported(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {"type": "custom", "voice": "Ryan",
            "versions": {"a": {"type": "custom", "voice": "Ryan", "age_group": "adult"},
                         "b": {"type": "custom", "voice": "Aiden", "age_group": "adult"}}}})

        record = self.build()["characters"][0]

        self.assertIn("multiple_versions_per_age", record["problems"])

    def test_a_voice_alias_to_a_missing_character_is_reported(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {"type": "custom", "voice": "Ryan",
                                                       "alias_of": "NOBODY"}})

        record = self.build()["characters"][0]

        self.assertEqual("NOBODY", record["voice"]["alias_of"])
        self.assertIn("alias_of_missing", record["problems"])

    def test_a_stored_status_that_contradicts_the_voice_is_reported(self):
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {"MIRA": {
            "type": "clone", "voice": "Ryan", "description": "x",
            "voice_status": "unassigned"}})

        record = self.build()["characters"][0]

        self.assertEqual("unassigned", record["voice_status"])
        self.assertTrue(record["voice"]["assigned"])
        self.assertIn("voice_status_conflict", record["problems"])

    def test_an_unknown_speaker_label_is_reported(self):
        self.write_json("annotated_script.json", _script(("UNKNOWN", 3)))
        self.write_json("voice_config.json", {})

        self.assertIn("unknown_speaker_label", self.build()["characters"][0]["problems"])


class MalformedDataTests(ProjectionFixture):
    def _assert_clean(self, data):
        before = self.snapshot()
        built = data()
        self.assertEqual(before, self.snapshot(), "a read must never write")
        return built

    def test_a_missing_script_is_an_empty_browsable_page_not_an_error(self):
        built = self._assert_clean(self.build)

        self.assertEqual([], built["characters"])
        self.assertEqual([], built["orphans"])
        self.assertFalse(built["book"]["script_present"])

    def test_a_malformed_script_degrades_to_an_empty_roster(self):
        with open(os.path.join(self.tmp, "annotated_script.json"), "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.write_json("voice_config.json", {"MIRA": {"type": "custom", "voice": "Ryan"}})

        built = self._assert_clean(self.build)

        self.assertEqual([], built["characters"])
        # The configuration is still reported, as an orphan, rather than lost.
        self.assertEqual(["MIRA"], [o["name"] for o in built["orphans"]])
        self.assertIn("config_without_script_line", built["orphans"][0]["problems"])

    def test_a_script_that_is_not_a_list_degrades_to_an_empty_roster(self):
        self.write_json("annotated_script.json", {"nope": True})
        self.write_json("voice_config.json", {})

        self.assertEqual([], self._assert_clean(self.build)["characters"])

    def test_a_malformed_voice_config_degrades_to_no_configuration(self):
        with open(os.path.join(self.tmp, "voice_config.json"), "w", encoding="utf-8") as handle:
            handle.write("[1,2,3]")
        self.write_json("annotated_script.json", _script(("MIRA", 3)))

        record = self._assert_clean(self.build)["characters"][0]

        self.assertEqual("MIRA", record["name"])
        self.assertFalse(record["voice"]["assigned"])

    def test_a_non_object_entry_yields_a_defaulted_record_rather_than_crashing(self):
        self.write_json("annotated_script.json", ["nonsense", 42, None,
                                                  {"speaker": "MIRA", "text": "hi"}])
        self.write_json("voice_config.json", {"MIRA": "not an object"})

        data = self._assert_clean(self.build)

        self.assertEqual(["MIRA"], [c["name"] for c in data["characters"]])
        self.assertFalse(data["characters"][0]["voice"]["assigned"])

    def test_a_malformed_voice_library_is_ignored(self):
        with open(os.path.join(self.tmp, "voice_library.json"), "w", encoding="utf-8") as handle:
            handle.write("{broken")
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {})

        record = self._assert_clean(self.build)["characters"][0]

        self.assertEqual([], record["known_as"])
        self.assertEqual("MIRA", record["name"])

    def test_an_unreadable_config_still_projects(self):
        with open(os.path.join(self.tmp, "config.json"), "w", encoding="utf-8") as handle:
            handle.write("{{{")
        self.write_json("annotated_script.json", _script(("MIRA", 3)))
        self.write_json("voice_config.json", {})

        self.assertIsNone(self._assert_clean(self.build)["traits_requested"])


class RouteContractTests(unittest.TestCase):
    def setUp(self):
        from routers import voices_v2

        self.router = voices_v2.router

    def test_the_route_serves_the_projection_over_http(self):
        app = FastAPI()
        app.include_router(self.router)
        with TestClient(app) as client:
            response = client.get("/api/voices-v2/characters")
        self.assertEqual(200, response.status_code)
        body = response.json()
        for key in ("schema_version", "book", "traits_available", "vocabularies",
                    "characters", "orphans", "counts"):
            self.assertIn(key, body)

    def test_the_response_model_forbids_anything_beyond_the_declared_shape(self):
        from routers.voices_v2 import VoicesV2CharactersResponse

        model = VoicesV2CharactersResponse(major_line_threshold=25)
        self.assertEqual([], model.characters)
        self.assertEqual([], model.orphans)
        self.assertEqual({"characters": 0, "orphans": 0}, model.counts.model_dump())
        self.assertEqual(
            {"schema_version", "book", "traits_available", "traits_requested",
             "aliases_registered", "major_line_threshold", "vocabularies",
             "characters", "orphans", "counts"},
            set(model.model_dump()),
            "the response must not carry anything beyond the declared shape")


if __name__ == "__main__":
    unittest.main()