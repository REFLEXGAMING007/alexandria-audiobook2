"""Voices V2 single-character voice assignment: the write path.

The whole feature is one sentence — *change one character's voice without losing
anything else* — so most of these tests are about what must survive.

What is pinned:

  - a valid assignment, a replacement, and a clear, each producing the entry the
    Voices tab would produce for the same logical change;
  - every field V2 does not own surviving byte-for-byte, including the fields
    `VoiceConfigItem` does not declare at all (`persona_ref`, `gender`,
    `state_assignments`) and the nested contents of `versions`;
  - a stale `revision` or `book_token` being refused with 409 and no write;
  - refusals for an unknown character, an ambiguous key, an unknown voice, an
    unavailable voice, and a malformed request, each with a stable code;
  - `PROFESSOR FERNANDO` and `PROFESSOR_FERNANDO` staying distinct;
  - the result showing up in the next projection read.

The equivalence target is the important one: the same logical change made in the
Voices tab must leave the same file. That is checked directly against
`_apply_voice_save`, not against a restatement of the merge rule.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from voice_config_store import VoiceConfigConflict, get_voice_config_revision


REVISION = "a" * 64
TOKEN = "b" * 64


def _script(*speakers):
    return [{"speaker": name, "text": "line", "spoken": True}
            for name, lines in speakers for _ in range(lines)]


class AssignmentFixture(unittest.TestCase):
    """A temp data dir, a temp adapter bundle, and the real save path wired up.

    STORED is deliberately hostile: it carries every declared field the Voices tab
    owns, an undeclared field, a nested undeclared field inside a version, and an
    integer seed. Anything the merge drops shows up here first.
    """

    STORED = {
        "MIRA": {
            "type": "lora", "voice": None, "adapter_id": "old_adapter",
            "adapter_path": "lora_models/old_adapter", "description": "a persona",
            "ref_audio": "clone_voices/old.wav", "ref_text": "old words",
            "character_style": "a careful delivery", "default_style": "", "seed": 1786420753,
            "ready": True, "persona_status": "generated", "voice_status": "assigned",
            "active_version": "teen", "age_group": "teen",
            "versions": {"teen": {"type": "clone", "voice": "Ryan", "age_group": "teen",
                                  "persona_ref": "persona_refs/teen.json"}},
            "candidates": [{"name": "c1"}],
            "version_timeline": [{"from_index": 12, "version_id": "teen"}],
            "style_timeline": [{"from_index": 3, "character_style": "s"}],
            "alias_of": "OTHER", "gender": "female",
            # Undeclared by VoiceConfigItem, so it can only survive via the merge.
            "persona_ref": "persona_refs/mira.json",
            "state_assignments": {"MALE|ADULT": {"version_id": "v2"}},
        },
        "OTHER": {"type": "custom", "voice": "Ryan", "seed": "-1"},
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        import core
        import voices_v2.character_projection as projection
        import voices_v2.voice_assignment as assignment
        import voices_v2.voice_identity as identity
        from routers import voices as voices_router

        self.projection = projection
        self.assignment = assignment
        self.identity = identity
        self.voices = voices_router

        self.state_path = os.path.join(self.tmp, "state.json")
        self.script_path = os.path.join(self.tmp, "annotated_script.json")
        self.config_path = os.path.join(self.tmp, "voice_config.json")

        for module in (projection, voices_router):
            for name, value in (
                ("DATA_DIR", self.tmp),
                ("SCRIPT_PATH", self.script_path),
                ("VOICE_CONFIG_PATH", self.config_path),
                ("CHARACTER_ALIASES_PATH", os.path.join(self.tmp, "character_aliases.json")),
                ("CONFIG_PATH", os.path.join(self.tmp, "config.json")),
            ):
                if hasattr(module, name):
                    self._patch(module, name, value)
        self._patch(core, "DATA_DIR", self.tmp)
        self._patch(core, "VOICE_LIBRARY_PATH", os.path.join(self.tmp, "voice_library.json"))
        self._patch(core, "CHARACTER_ALIASES_PATH",
                    os.path.join(self.tmp, "character_aliases.json"))
        self._patch(core, "LORA_MODELS_DIR", os.path.join(self.tmp, "lora_models"))
        self._patch(core, "CLONE_VOICES_DIR", os.path.join(self.tmp, "clone_voices"))
        self._patch(core, "DESIGNED_VOICES_DIR", os.path.join(self.tmp, "designed_voices"))

        self._patch(assignment, "DATA_DIR", self.tmp)
        self._patch(assignment, "VOICE_CONFIG_PATH", self.config_path)
        self._patch(assignment, "LORA_MODELS_DIR", os.path.join(self.tmp, "lora_models"))
        self._patch(assignment, "LORA_MODELS_MANIFEST",
                    os.path.join(self.tmp, "lora_models", "manifest.json"))
        self._patch(assignment, "BUILTIN_LORA_DIR", os.path.join(self.tmp, "builtin_lora"))
        self._patch(assignment, "BUILTIN_LORA_MANIFEST",
                    os.path.join(self.tmp, "builtin_lora", "manifest.json"))
        self._patch(assignment, "CLONE_VOICES_DIR", os.path.join(self.tmp, "clone_voices"))
        self._patch(assignment, "DESIGNED_VOICES_DIR",
                    os.path.join(self.tmp, "designed_voices"))
        self._patch(assignment, "CLONE_VOICES_MANIFEST",
                    os.path.join(self.tmp, "clone_voices", "manifest.json"))
        self._patch(assignment, "DESIGNED_VOICES_MANIFEST",
                    os.path.join(self.tmp, "designed_voices", "manifest.json"))
        self._patch(identity, "CLONE_VOICES_DIR", os.path.join(self.tmp, "clone_voices"))
        self._patch(identity, "DESIGNED_VOICES_DIR",
                    os.path.join(self.tmp, "designed_voices"))
        self._patch(identity, "CLONE_VOICES_MANIFEST",
                    os.path.join(self.tmp, "clone_voices", "manifest.json"))
        self._patch(identity, "DESIGNED_VOICES_MANIFEST",
                    os.path.join(self.tmp, "designed_voices", "manifest.json"))

        self.write_json("state.json", {"active_book_id": "book",
                                       "input_file_path": os.path.join(self.tmp, "B.txt")})
        # Every catalogue source directory has to exist: the read path takes a
        # file lock on each manifest, and a lock on a missing directory fails
        # before any of the code under test runs.
        for directory in ("lora_models", "clone_voices", "designed_voices", "builtin_lora"):
            os.makedirs(os.path.join(self.tmp, directory), exist_ok=True)
        self.write_json("builtin_lora/manifest.json", [])

    def _patch(self, module, name, value):
        patcher = patch.object(module, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_json(self, name, payload, root=None):
        path = os.path.join(root or self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def write_file(self, name, payload=b"RIFF", root=None):
        path = os.path.join(root or self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def stored(self):
        with open(self.config_path, encoding="utf-8") as handle:
            return json.load(handle)

    def revision(self):
        return get_voice_config_revision(self.stored())

    def client(self):
        from routers import voices_v2 as v2

        app = FastAPI()
        app.include_router(v2.router)
        return TestClient(app)

    def seed_design(self, voice_id="narrator_1", name="NARRATOR",
                    description="A calm, measured narrator."):
        self.write_file("designed_voices/narrator_1.wav")
        self.write_json("designed_voices/manifest.json",
                        [{"id": voice_id, "name": name, "description": description,
                          "sample_text": "Once upon a time.", "filename": "narrator_1.wav"}])
        return f"design:{voice_id}"

    def seed_lora(self, adapter_id="tenor_deep"):
        os.makedirs(os.path.join(self.tmp, "lora_models", adapter_id), exist_ok=True)
        self.write_json("lora_models/manifest.json",
                        [{"id": adapter_id, "name": adapter_id, "description": "Deep tenor"}])
        return f"lora:{adapter_id}"

    def seed_clone(self, voice_id="clone_1", filename="clip_1.wav"):
        self.write_file(f"clone_voices/{filename}")
        self.write_json("clone_voices/manifest.json",
                        [{"id": voice_id, "name": "Clip", "filename": filename,
                          "ref_text": "the exact words spoken in the clip"}])
        return f"clone:{voice_id}"

    def seed(self, script=None, config=None):
        if script is not None:
            self.write_json("annotated_script.json", script)
        if config is not None:
            self.write_json("voice_config.json", config)
        return self


class CatalogueTests(AssignmentFixture):
    def test_the_catalogue_lists_every_source_with_its_availability(self):
        design = self.seed_design()
        lora = self.seed_lora()
        clone = self.seed_clone()
        self.seed(script=_script(("MIRA", 3)), config={})

        catalogue = self.assignment.build_voice_catalogue()
        ids = [row["voice_id"] for row in catalogue["voices"]]

        self.assertIn(design, ids)
        self.assertIn(lora, ids)
        self.assertIn(clone, ids)
        self.assertEqual(catalogue["counts"]["total"], 3)
        self.assertEqual(catalogue["counts"]["available"], 3)
        self.assertEqual(catalogue["kinds"], ["lora", "builtin_lora", "clone", "design"])
        self.assertIn("ensemble", catalogue["unsupported_kinds"])

    def test_a_voice_whose_files_are_missing_is_listed_but_unavailable(self):
        self.write_json("lora_models/manifest.json",
                        [{"id": "ghost_adapter", "name": "ghost_adapter"}])
        self.seed(script=_script(("MIRA", 3)), config={})

        row = next(r for r in self.assignment.build_voice_catalogue()["voices"]
                   if r["voice_id"] == "lora:ghost_adapter")

        self.assertFalse(row["available"])
        self.assertIn("not on disk", row["unavailable_reason"])

    def test_a_clone_without_a_transcript_cannot_be_assigned(self):
        self.write_file("clone_voices/clip.wav")
        self.write_json("clone_voices/manifest.json",
                        [{"id": "c1", "name": "Clip", "filename": "clip.wav", "ref_text": ""}])
        self.seed(script=_script(("MIRA", 3)), config={})

        row = next(r for r in self.assignment.build_voice_catalogue()["voices"]
                   if r["voice_id"] == "clone:c1")

        self.assertFalse(row["available"])
        self.assertIn("transcript", row["unavailable_reason"])

    def test_a_malformed_adapter_manifest_costs_only_the_lora_voices(self):
        """One hand-edited manifest row must not take the whole selector down.

        `get_adapter_manifest_rows` refuses an id like `..\\escape` outright, and
        clones and designs share this one catalogue read. Reporting the adapters
        as unreadable and carrying on keeps voice assignment working for every
        other family.
        """
        design = self.seed_design()
        self.write_json("lora_models/manifest.json",
                        [{"id": "..\\escape", "name": "..\\escape"}])
        self.seed(script=_script(("MIRA", 3)), config={})

        catalogue = self.assignment.build_voice_catalogue()

        self.assertEqual([design], [r["voice_id"] for r in catalogue["voices"]])
        self.assertTrue(catalogue["warnings"])
        self.assertIn("LoRA", catalogue["warnings"][0])
        self.assertNotIn("..", json.dumps(catalogue["voices"]),
                         "a traversing id must never reach the catalogue")


class IdentityTests(AssignmentFixture):
    def test_a_key_resolves_to_the_exact_stored_speaker_name(self):
        self.seed(script=_script(("CHUNG MYUNG", 5)),
                  config={"CHUNG MYUNG": {"type": "custom", "voice": "Ryan"}})

        name, record = self.assignment.resolve_writable_character("chung myung")

        self.assertEqual("CHUNG MYUNG", name)
        self.assertTrue(record["present_in_script"])

    def test_two_spellings_stay_two_distinct_characters(self):
        self.seed(script=_script(("PROFESSOR FERNANDO", 2)),
                  config={"PROFESSOR FERNANDO": {"type": "custom", "voice": "Aiden"},
                          "PROFESSOR_FERNANDO": {"type": "custom", "voice": "Ryan"}})

        spaced, _ = self.assignment.resolve_writable_character("professor fernando")
        underscored, _ = self.assignment.resolve_writable_character("professor_fernando")

        self.assertEqual("PROFESSOR FERNANDO", spaced)
        self.assertEqual("PROFESSOR_FERNANDO", underscored)
        self.assertNotEqual(spaced, underscored)

    def test_an_unknown_key_is_refused(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.resolve_writable_character("nobody at all")
        self.assertEqual("unknown_character", caught.exception.code)
        self.assertEqual(404, caught.exception.status)

    def test_a_key_several_records_share_is_refused_rather_than_guessed(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        # Two records can only collide if the projection produced the same key
        # twice; forcing it proves the guard fires instead of picking a winner.
        with patch.object(self.assignment, "build_character_projection") as stub:
            stub.return_value = {
                "characters": [{"key": "dupe", "name": "A", "present_in_script": True,
                                "library_key": "dupe"},
                               {"key": "dupe", "name": "B", "present_in_script": True,
                                "library_key": "dupe"}],
                "orphans": []}
            with self.assertRaises(self.assignment.VoiceCommandError) as caught:
                self.assignment.resolve_writable_character("dupe")
        self.assertEqual("ambiguous_character", caught.exception.code)
        self.assertEqual(409, caught.exception.status)

    def test_a_character_gone_from_the_script_but_present_in_config_is_writable(self):
        """An orphan owns a stored entry, so it must be assignable - the Voices
        tab simply cannot show it."""
        self.seed(script=_script(("MIRA", 3)), config={"GHOST": {"type": "custom", "voice": "Ryan"}})

        name, record = self.assignment.resolve_writable_character("ghost")

        self.assertEqual("GHOST", name)
        self.assertFalse(record["present_in_script"])


class PlanTests(AssignmentFixture):
    """The merge that will be written, checked before anything is written."""

    def test_an_assignment_replaces_only_the_fields_that_describe_the_voice(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        entry = self.assignment.plan_voice_command("assign", "mira", design)["entry"]

        self.assertEqual("design", entry["type"])
        self.assertEqual("A calm, measured narrator.", entry["description"])
        self.assertIsNone(entry["adapter_id"])
        self.assertIsNone(entry["adapter_path"])
        self.assertIsNone(entry["ref_text"])
        # The designed voice's own preview path, kept so the configuration can be
        # mapped back to a catalogue row on the next read.
        self.assertEqual("designed_voices/narrator_1.wav", entry["ref_audio"])

    def test_every_other_field_survives_the_merge(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        entry = self.assignment.plan_voice_command("assign", "mira", design)["entry"]

        for field in ("character_style", "default_style", "ready", "persona_status",
                      "voice_status", "active_version", "age_group", "versions",
                      "candidates", "version_timeline", "style_timeline",
                      "gender", "persona_ref", "state_assignments"):
            with self.subTest(field=field):
                self.assertEqual(self.STORED["MIRA"][field], entry[field],
                                 f"{field} must survive an assignment untouched")
        # alias_of is the one field an assignment does clear: it is a voice
        # reference, and it is resolved ahead of the assigned voice.
        self.assertIsNone(entry["alias_of"])
        # Nested version contents are not flattened or dropped either.
        self.assertEqual("persona_refs/teen.json", entry["versions"]["teen"]["persona_ref"])

    def test_the_seed_is_normalised_to_a_string_as_the_voices_tab_sends_it(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        entry = self.assignment.plan_voice_command("assign", "mira", design)["entry"]

        self.assertEqual("1786420753", entry["seed"])
        self.assertIsInstance(entry["seed"], str)

    def test_a_clear_removes_the_voice_but_keeps_the_review_and_history(self):
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        entry = self.assignment.plan_voice_command("clear", "mira", None)["entry"]

        self.assertEqual("custom", entry["type"])
        for field in ("adapter_id", "adapter_path", "ref_audio", "ref_text", "description",
                      "voice"):
            with self.subTest(field=field):
                self.assertIsNone(entry[field])
        for field in ("versions", "candidates", "version_timeline", "style_timeline",
                      "ready", "persona_status", "persona_ref", "state_assignments"):
            with self.subTest(field=field):
                self.assertEqual(self.STORED["MIRA"][field], entry[field])

    def test_a_lora_assignment_carries_the_namespaced_adapter_path(self):
        lora = self.seed_lora()
        self.seed(script=_script(("MIRA", 30)), config={"MIRA": {"type": "custom", "voice": "Ryan"}})

        entry = self.assignment.plan_voice_command("assign", "mira", lora)["entry"]

        self.assertEqual("lora", entry["type"])
        self.assertEqual("tenor_deep", entry["adapter_id"])
        self.assertEqual("lora_models/tenor_deep", entry["adapter_path"])

    def test_a_clone_assignment_carries_the_reference_and_its_transcript(self):
        clone = self.seed_clone()
        self.seed(script=_script(("MIRA", 30)), config={})

        entry = self.assignment.plan_voice_command("assign", "mira", clone)["entry"]

        self.assertEqual("clone", entry["type"])
        self.assertEqual("clone_voices/clip_1.wav", entry["ref_audio"])
        self.assertEqual("the exact words spoken in the clip", entry["ref_text"])

    def test_an_unknown_voice_is_refused(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.plan_voice_command("assign", "mira", "lora:nope")
        self.assertEqual("unknown_voice", caught.exception.code)

    def test_a_voice_from_an_unsupported_family_is_refused(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        for voice_id in ("ensemble:a", "custom:Ryan", "nonsense", "", None, 7):
            with self.subTest(voice_id=voice_id):
                with self.assertRaises(self.assignment.VoiceCommandError) as caught:
                    self.assignment.plan_voice_command("assign", "mira", voice_id)
                self.assertEqual("invalid_voice", caught.exception.code)

    def test_an_unavailable_voice_is_refused_with_its_reason(self):
        self.write_json("lora_models/manifest.json",
                        [{"id": "ghost", "name": "ghost"}])
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.plan_voice_command("assign", "mira", "lora:ghost")
        self.assertEqual("voice_unavailable", caught.exception.code)
        self.assertIn("not on disk", caught.exception.message)

    def test_an_unknown_command_is_refused(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.plan_voice_command("frobnicate", "mira", None)
        self.assertEqual("unknown_command", caught.exception.code)

    def test_clearing_a_character_with_no_entry_is_refused(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.plan_voice_command("clear", "mira", None)
        self.assertEqual("nothing_to_clear", caught.exception.code)

    def test_planning_never_writes(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)
        before = self.stored()

        self.assignment.plan_voice_command("assign", "mira", design)

        self.assertEqual(before, self.stored())


class WriteTests(AssignmentFixture):
    def _save(self, plan, revision=None, token=None):
        return self.assignment.execute_voice_command(
            plan, revision or self.revision(),
            token or self.projection.build_character_projection()["book"]["token"])

    def test_a_valid_assignment_matches_the_voices_tab_result_it_is_meant_to(self):
        """The equivalence target, stated precisely rather than asserted loosely.

        `collectVoiceConfig` is mirrored faithfully, including the parts that are
        easy to get wrong: the design branch writes only `type`, `description` and
        `seed`; `alias_of` and `ready` are added afterwards only when the card has
        them; the seed is then restored as a string; and thirteen voice-owned keys
        are dropped from the preserved metadata.

        Three groups of field then differ, and every one is deliberate:
        `character_style`/`default_style`, which the design branch does not write
        and which the tab therefore blanks - silently deleting a style prompt
        because the user picked a different voice; `alias_of`, which the tab keeps
        even though an alias is resolved ahead of the assigned voice at synthesis,
        so keeping it would make the assignment appear to work while the alias kept
        winning; and `ref_audio`, which V2 records as an identity anchor so the
        editor can still tell which designed voice it assigned. A fourth is
        `voice`: the design branch never writes it and `VoiceConfigItem` defaults
        it to the built-in "Ryan", so the tab stores a custom voice name on a
        designed-voice entry. V2 stores the design's own name, which is what the
        browser shows as the voice.
        """
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)
        stored_before = self.stored()

        from routers.voices import VoiceConfigItem, _apply_voice_save

        preserved = dict(stored_before["MIRA"])
        seed = preserved.get("seed")
        alias = preserved.get("alias_of")
        ready = preserved.get("ready")
        for key in ("type", "voice", "character_style", "default_style", "seed", "ref_audio",
                    "ref_text", "adapter_id", "adapter_path", "description", "members",
                    "alias_of", "ready"):
            preserved.pop(key, None)
        legacy_branch = {"type": "design", "description": "A calm, measured narrator.",
                         "seed": "-1"}
        if alias:
            legacy_branch["alias_of"] = alias
        if ready:
            legacy_branch["ready"] = True
        legacy_entry = {**preserved, **legacy_branch}
        legacy_entry["seed"] = str(seed if seed is not None else "-1")
        token = self.projection.build_character_projection()["book"]["token"]
        _apply_voice_save({"MIRA": VoiceConfigItem(**legacy_entry)},
                          get_voice_config_revision(stored_before), token)
        legacy_mira = self.stored()["MIRA"]

        # V2, from the same starting state.
        self.write_json("voice_config.json", stored_before)
        plan = self.assignment.plan_voice_command("assign", "mira", design)
        self._save(plan)
        v2_mira = self.stored()["MIRA"]

        divergent = {"ref_audio", "character_style", "default_style", "alias_of",
                      "voice"}
        self.assertEqual({k: v for k, v in legacy_mira.items() if k not in divergent},
                         {k: v for k, v in v2_mira.items() if k not in divergent},
                         "V2 and the Voices tab must agree on every other field")
        self.assertEqual("", legacy_mira["character_style"],
                         "the tab blanks the style because its design branch omits it")
        self.assertEqual(self.STORED["MIRA"]["character_style"], v2_mira["character_style"],
                         "V2 keeps the style: picking a voice is not a style edit")
        self.assertIsNone(legacy_mira["ref_audio"])
        self.assertEqual("designed_voices/narrator_1.wav", v2_mira["ref_audio"])
        self.assertEqual(self.STORED["MIRA"]["default_style"], v2_mira["default_style"])
        self.assertIsNone(v2_mira["alias_of"],
                          "an alias would override the voice just assigned")
        self.assertEqual("Ryan", legacy_mira["voice"])
        self.assertEqual("NARRATOR", v2_mira["voice"],
                         "the design branch writes no voice, and the model default is the built-in "
                         "\"Ryan\"; V2 stores the designed voice's name instead")

    def test_v2_touches_only_the_character_it_was_asked_to_change(self):
        """Deliberately stricter than the Voices tab, in the safe direction.

        The tab scrapes every card and posts the whole map, so a save from it
        normalises *every* entry - rewriting untouched characters with model
        defaults. V2 posts one key, so every other character is left exactly as
        stored. Fewer fields written is the point of a character-scoped command.
        """
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)),
                  config={**self.STORED, "RYAN": {"type": "clone", "voice": "Ryan",
                                                  "seed": "7"}})
        before = self.stored()

        self._save(self.assignment.plan_voice_command("assign", "mira", design))
        after = self.stored()

        self.assertEqual(before["RYAN"], after["RYAN"])
        self.assertEqual(before["OTHER"], after["OTHER"])
        self.assertNotEqual(before["MIRA"], after["MIRA"])
        self.assertNotIn("active_candidate", after["RYAN"],
                         "an untouched entry is not normalised by a V2 save")

    def test_a_replacement_overwrites_the_voice_and_nothing_else(self):
        first = self.seed_design(description="First voice.")
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)
        self._save(self.assignment.plan_voice_command("assign", "mira", first))
        replacement = self.seed_design(voice_id="narrator_2", name="OTHER VOICE",
                                       description="Second voice.")
        self.write_json("designed_voices/manifest.json", json.loads(
            json.dumps([{"id": "narrator_2", "name": "OTHER VOICE",
                         "description": "Second voice.", "sample_text": "x",
                         "filename": "narrator_1.wav"}])))
        self._save(self.assignment.plan_voice_command("assign", "mira", replacement))

        entry = self.stored()["MIRA"]
        self.assertEqual("Second voice.", entry["description"])
        self.assertEqual("a careful delivery", entry["character_style"])
        self.assertEqual(self.STORED["MIRA"]["versions"], entry["versions"])

    def test_a_clear_removes_the_voice_from_disk(self):
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        result = self._save(self.assignment.plan_voice_command("clear", "mira", None))

        self.assertEqual("saved", result["status"])
        self.assertIsNone(result["voice_id"])
        entry = self.stored()["MIRA"]
        self.assertEqual("custom", entry["type"])
        self.assertIsNone(entry["description"])
        self.assertEqual(self.STORED["MIRA"]["persona_ref"], entry["persona_ref"])

    def test_unrelated_characters_are_untouched(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30), ("RYAN", 4)),
                  config={**self.STORED, "RYAN": {"type": "clone", "voice": "Ryan",
                                                  "ref_audio": "clone_voices/r.wav",
                                                  "ref_text": "words", "seed": "7"}})

        self._save(self.assignment.plan_voice_command("assign", "mira", design))

        self.assertEqual({"type": "clone", "voice": "Ryan",
                          "ref_audio": "clone_voices/r.wav", "ref_text": "words",
                          "seed": "7"}, self.stored()["RYAN"])
        self.assertEqual(self.STORED["OTHER"], self.stored()["OTHER"])

    def test_a_stale_revision_is_refused_and_nothing_is_written(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)
        before = self.stored()

        with self.assertRaises(VoiceConfigConflict):
            self._save(self.assignment.plan_voice_command("assign", "mira", design),
                       revision="0" * 64)

        self.assertEqual(before, self.stored())

    def test_a_stale_book_token_is_refused_and_nothing_is_written(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)
        before = self.stored()

        with self.assertRaises(VoiceConfigConflict):
            self._save(self.assignment.plan_voice_command("assign", "mira", design),
                       token="1" * 64)

        self.assertEqual(before, self.stored())

    def test_a_second_save_from_the_same_snapshot_loses_the_first_ones_privilege(self):
        """Two clients reading the same revision: the first wins, the second is
        refused. This is the property the whole token design exists for."""
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config={"MIRA": {"type": "custom",
                                                                  "voice": "Ryan"}})
        shared_revision = self.revision()
        token = self.projection.build_character_projection()["book"]["token"]

        self._save(self.assignment.plan_voice_command("assign", "mira", design),
                   revision=shared_revision, token=token)
        with self.assertRaises(VoiceConfigConflict):
            self._save(self.assignment.plan_voice_command("assign", "mira", design),
                       revision=shared_revision, token=token)

    def test_a_stored_entry_that_cannot_be_validated_is_refused_not_repaired(self):
        """Damage V2 does not own still blocks the save.

        `candidates` is not a field an assignment touches, so a malformed one
        cannot be incidentally fixed by the merge - and dropping it to make the
        save fit would be silent data loss.
        """
        self.seed(script=_script(("MIRA", 30)),
                  config={"MIRA": {"type": "custom", "voice": "Ryan",
                                   "candidates": "not a list"}})
        before = self.stored()

        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self._save(self.assignment.plan_voice_command(
                "assign", "mira", self.seed_design()))

        self.assertEqual("invalid_configuration", caught.exception.code)
        self.assertIn("Nothing was changed", caught.exception.message)
        self.assertIn("candidates", caught.exception.message)
        self.assertEqual(before, self.stored())

    def test_replacing_the_type_of_a_stored_ensemble_with_no_members_succeeds(self):
        """Documented, and the opposite of the case above.

        An ensemble entry with no members is invalid, but `type` is a voice-owned
        field: choosing a different voice replaces it, so the merged entry is
        valid and the write goes through. The user asked for a different voice
        and gets one; nothing is silently discarded to achieve it.
        """
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)),
                  config={"MIRA": {"type": "ensemble", "voice": "Ryan"}})

        self._save(self.assignment.plan_voice_command("assign", "mira", design))

        entry = self.stored()["MIRA"]
        self.assertEqual("design", entry["type"])
        self.assertIsNone(entry["members"])


class RouteTests(AssignmentFixture):
    def test_assign_replaces_and_clear_round_trip_over_http(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config=self.STORED)

        with self.client() as client:
            projection = client.get("/api/voices-v2/characters").json()
            token = projection["book"]["token"]

            assigned = client.post("/api/voices-v2/command", json={
                "command": "assign", "character": "mira", "voice_id": design,
                "revision": projection["revision"], "book_token": token})
            self.assertEqual(200, assigned.status_code, assigned.text)
            self.assertEqual("saved", assigned.json()["status"])
            self.assertEqual("MIRA", assigned.json()["character"])
            self.assertEqual(design, assigned.json()["voice_id"])
            self.assertNotEqual(projection["revision"], assigned.json()["revision"],
                                "the response must carry the new revision")

            after = client.get("/api/voices-v2/characters").json()
            record = next(r for r in after["characters"] if r["name"] == "MIRA")
            self.assertEqual("design", record["voice"]["type"])
            self.assertTrue(record["voice"]["assigned"])
            self.assertEqual(design, record["voice"]["catalogue_voice_id"])
            self.assertEqual("NARRATOR", record["voice"]["label"])

            cleared = client.post("/api/voices-v2/command", json={
                "command": "clear", "character": "mira", "voice_id": None,
                "revision": after["revision"], "book_token": after["book"]["token"]})
            self.assertEqual(200, cleared.status_code, cleared.text)

            final = client.get("/api/voices-v2/characters").json()
            record = next(r for r in final["characters"] if r["name"] == "MIRA")
            self.assertFalse(record["voice"]["assigned"])
            self.assertIsNone(record["voice"]["catalogue_voice_id"])

    def test_a_stale_client_is_refused_with_409_and_a_code(self):
        self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config={"MIRA": {"type": "custom",
                                                                  "voice": "Ryan"}})

        with self.client() as client:
            projection = client.get("/api/voices-v2/characters").json()
            body = {"command": "clear", "character": "mira",
                    "revision": projection["revision"],
                    "book_token": projection["book"]["token"]}
            self.assertEqual(200, client.post("/api/voices-v2/command", json=body).status_code)
            stale = client.post("/api/voices-v2/command", json=body)

        self.assertEqual(409, stale.status_code)
        self.assertEqual("stale_snapshot", stale.json()["detail"]["code"])

    def test_every_refusal_carries_a_stable_code(self):
        self.seed_design()
        self.seed(script=_script(("MIRA", 30)), config={"MIRA": {"type": "custom",
                                                                  "voice": "Ryan"}})
        with self.client() as client:
            projection = client.get("/api/voices-v2/characters").json()
            base = {"revision": projection["revision"],
                    "book_token": projection["book"]["token"]}

            cases = [
                ({"command": "assign", "character": "nobody", "voice_id": None}, 404,
                 "unknown_character"),
                ({"command": "assign", "character": "mira", "voice_id": "lora:nope"}, 404,
                 "unknown_voice"),
                ({"command": "assign", "character": "mira", "voice_id": "ensemble:a"}, 400,
                 "invalid_voice"),
                ({"command": "frobnicate", "character": "mira", "voice_id": None}, 400,
                 "unknown_command"),
                ({"command": "clear", "character": "mira", "voice_id": None,
                  "revision": "0" * 64}, 409, "stale_snapshot"),
            ]
            for extra, status, code in cases:
                with self.subTest(code=code):
                    response = client.post("/api/voices-v2/command", json={**base, **extra})
                    self.assertEqual(status, response.status_code, response.text)
                    self.assertEqual(code, response.json()["detail"]["code"])

    def test_a_malformed_request_is_refused_before_any_handling(self):
        self.seed(script=_script(("MIRA", 3)), config={})
        with self.client() as client:
            for body in (
                {"command": "assign", "character": "mira", "revision": "short",
                 "book_token": TOKEN},
                {"command": "assign", "revision": REVISION, "book_token": TOKEN},
                {"character": "mira", "revision": REVISION, "book_token": TOKEN},
                {"command": "assign", "character": "mira", "voice_id": "lora:x",
                 "revision": REVISION, "book_token": "nope"},
            ):
                with self.subTest(body=body):
                    self.assertEqual(422, client.post("/api/voices-v2/command", json=body).status_code)

    def test_the_catalogue_endpoint_serves_the_assembled_rows(self):
        design = self.seed_design()
        self.seed(script=_script(("MIRA", 3)), config={})

        with self.client() as client:
            response = client.get("/api/voices-v2/voices")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual([design], [row["voice_id"] for row in payload["voices"]])
        self.assertEqual({"total": 1, "available": 1, "unavailable": 0}, payload["counts"])

    def test_the_existing_voices_endpoints_still_answer(self):
        self.seed(script=_script(("MIRA", 30)), config={"MIRA": {"type": "custom",
                                                                  "voice": "Ryan"}})
        app = FastAPI()
        app.include_router(self.voices.router)

        with TestClient(app) as client:
            self.assertEqual(200, client.get("/api/voice_config/snapshot").status_code)
            self.assertEqual(200, client.get("/api/voices").status_code)
            body = client.get("/api/voice_config/snapshot").json()
            self.assertEqual(self.revision(), body["revision"],
                             "V2 and the Voices tab must report the same revision")


if __name__ == "__main__":
    unittest.main()