"""Voices V2 Voice Library: the normalised catalogue and favourites.

The library's credibility rests on two things that are easy to get wrong, so
they are pinned hardest here:

**A voice is never described with more confidence than its source allows.**
Every record carries `gender_source` / `age_group_source`, and the tests here
assert the *inferred* ones really are marked inferred. A catalogue that quietly
presents a guess as a fact is worse than one that admits ignorance, because the
user cannot tell which to trust.

**Favourites go where the application already keeps them.** They live in
`voice_library.json` as adapter ids, written through the same locked mutator the
Voices tab's own toggle uses. These tests assert that reuse rather than a second
store, and that a family with nowhere to store a favourite is refused with a
reason instead of being accepted and forgotten.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from voices_v2.voice_record import (SOURCE_DECLARED, SOURCE_INFERRED, SOURCE_UNKNOWN,
                                     declared_age_group, declared_gender,
                                     resolve_provenance, stated_added_at)


class CatalogueFixture(unittest.TestCase):
    """A temp data dir with one voice of every supported family."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        import core
        import voices_v2.character_projection as projection
        import voices_v2.voice_assignment as assignment
        import voices_v2.voice_identity as identity
        from routers import lora as lora_router
        from routers import voice_library, voices

        self.projection = projection
        self.assignment = assignment
        self.identity = identity
        self.voice_library_router = voice_library
        self.voices_router = voices
        self.lora_router = lora_router

        self.config_path = os.path.join(self.tmp, "voice_config.json")
        self.library_path = os.path.join(self.tmp, "voice_library.json")

        for module in (projection, voices, assignment, voice_library, lora_router):
            for name, value in (
                ("DATA_DIR", self.tmp),
                ("SCRIPT_PATH", os.path.join(self.tmp, "annotated_script.json")),
                ("VOICE_CONFIG_PATH", self.config_path),
                ("VOICE_LIBRARY_PATH", self.library_path),
                ("CHARACTER_ALIASES_PATH", os.path.join(self.tmp, "character_aliases.json")),
                ("CONFIG_PATH", os.path.join(self.tmp, "config.json")),
                ("LORA_MODELS_DIR", os.path.join(self.tmp, "lora_models")),
                ("BUILTIN_LORA_DIR", os.path.join(self.tmp, "builtin_lora")),
                ("CLONE_VOICES_DIR", os.path.join(self.tmp, "clone_voices")),
                ("DESIGNED_VOICES_DIR", os.path.join(self.tmp, "designed_voices")),
            ):
                if hasattr(module, name):
                    self._patch(module, name, value)
        self._patch(core, "VOICE_LIBRARY_PATH", self.library_path)
        self._patch(assignment, "LORA_MODELS_MANIFEST",
                    os.path.join(self.tmp, "lora_models", "manifest.json"))
        self._patch(assignment, "BUILTIN_LORA_MANIFEST",
                    os.path.join(self.tmp, "builtin_lora", "manifest.json"))
        self._patch(assignment, "CLONE_VOICES_MANIFEST",
                    os.path.join(self.tmp, "clone_voices", "manifest.json"))
        self._patch(assignment, "DESIGNED_VOICES_MANIFEST",
                    os.path.join(self.tmp, "designed_voices", "manifest.json"))
        self._patch(identity, "CLONE_VOICES_MANIFEST",
                    os.path.join(self.tmp, "clone_voices", "manifest.json"))
        self._patch(identity, "DESIGNED_VOICES_MANIFEST",
                    os.path.join(self.tmp, "designed_voices", "manifest.json"))

        for directory in ("lora_models", "builtin_lora", "clone_voices", "designed_voices"):
            os.makedirs(os.path.join(self.tmp, directory), exist_ok=True)
        self.write_json("state.json", {"active_book_id": "book"})
        self.write_json("annotated_script.json", [])
        self.write_json("voice_config.json", {})
        self.write_json("voice_library.json", {"shared": {}, "casts": {}, "favorites": []})
        self.write_json("builtin_lora/manifest.json", [])

    def _patch(self, module, name, value):
        patcher = patch.object(module, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_json(self, name, payload):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def write_file(self, name, payload=b"RIFF"):
        path = os.path.join(self.tmp, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def seed_lora(self, adapter_id="tenor_deep", gender=None, name=None, description="Deep",
                  added_at=None):
        os.makedirs(os.path.join(self.tmp, "lora_models", adapter_id), exist_ok=True)
        row = {"id": adapter_id, "name": name or adapter_id,
               "description": description, "epochs": 12, "sample_count": 40}
        if gender:
            row["gender"] = gender
        if added_at:
            row["created"] = added_at
        manifest = self.read_json("lora_models/manifest.json")
        manifest.append(row)
        self.write_json("lora_models/manifest.json", manifest)
        return f"lora:{adapter_id}"

    def seed_builtin(self, native="watson", gender="male"):
        row = {"id": native, "name": native, "gender": gender,
               "description": "Built-in narrator"}
        manifest = self.read_json("builtin_lora/manifest.json")
        manifest.append(row)
        self.write_json("builtin_lora/manifest.json", manifest)
        # A built-in is only assignable once its files exist.
        os.makedirs(os.path.join(self.tmp, "builtin_lora", f"builtin_{native}"), exist_ok=True)
        self.write_file(f"builtin_lora/builtin_{native}/adapter_config.json")
        return f"builtin_lora:builtin_{native}"

    def seed_clone(self, voice_id="clip_1", filename="clip.wav", ref_text="spoken words"):
        self.write_file(f"clone_voices/{filename}")
        manifest = self.read_json("clone_voices/manifest.json")
        manifest.append({"id": voice_id, "name": "A clip", "filename": filename,
                         "ref_text": ref_text, "imported_at": 1700000000})
        self.write_json("clone_voices/manifest.json", manifest)
        return f"clone:{voice_id}"

    def seed_design(self, voice_id="narrator_1", description="A calm narrator.",
                    with_preview=True):
        if with_preview:
            self.write_file(f"designed_voices/{voice_id}_preview.wav")
        manifest = self.read_json("designed_voices/manifest.json")
        manifest.append({"id": voice_id, "name": voice_id.upper(),
                         "description": description, "sample_text": "Once upon a time.",
                         "filename": f"{voice_id}_preview.wav" if with_preview else ""})
        self.write_json("designed_voices/manifest.json", manifest)
        return f"design:{voice_id}"

    def read_json(self, name):
        path = os.path.join(self.tmp, name)
        if not os.path.isfile(path):
            # A manifest that has never been written is an empty catalogue, which
            # is what a fresh workspace looks like.
            return []
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def catalogue(self):
        return self.assignment.build_voice_catalogue()

    def voices_by_id(self):
        return {row["voice_id"]: row for row in self.catalogue()["voices"]}

    def client(self):
        from routers import voices_v2 as v2

        app = FastAPI()
        app.include_router(v2.router)
        return TestClient(app)


class ProvenanceTests(unittest.TestCase):
    """The rule the whole metadata story rests on."""

    def test_a_stated_value_wins_over_a_guessed_one(self):
        self.assertEqual(("male", SOURCE_DECLARED),
                         resolve_provenance("male", "female"))

    def test_a_guess_is_labelled_as_a_guess(self):
        self.assertEqual(("female", SOURCE_INFERRED),
                         resolve_provenance(None, "female"))

    def test_no_value_stays_unknown_rather_than_becoming_a_guess(self):
        self.assertEqual((SOURCE_UNKNOWN, SOURCE_UNKNOWN),
                         resolve_provenance(None, SOURCE_UNKNOWN))
        self.assertEqual((SOURCE_UNKNOWN, SOURCE_UNKNOWN),
                         resolve_provenance(None, None))

    def test_declared_gender_only_accepts_a_stated_value(self):
        self.assertEqual("male", declared_gender({"gender": "Male"}))
        self.assertEqual("female", declared_gender({"gender": " female "}))
        for absent in ({}, {"gender": ""}, {"gender": "alto"}, {"gender": 3}):
            self.assertIsNone(declared_gender(absent), absent)

    def test_declared_age_only_accepts_a_real_band(self):
        self.assertEqual("young_adult", declared_age_group({"age_group": "Young Adult"}))
        self.assertEqual("young_adult", declared_age_group({"age": "young-adult"}))
        for absent in ({}, {"age_group": "eternal"}, {"age_group": None}):
            self.assertIsNone(declared_age_group(absent), absent)

    def test_a_stated_date_is_read_and_an_absent_one_is_not_invented(self):
        # Keys are named by the caller, because only the source knows which
        # field carries the date in its schema.
        self.assertEqual(1700000000,
                         stated_added_at({"imported_at": 1700000000}, "imported_at"))
        self.assertEqual(1700000000,
                         stated_added_at({"retrained_at": 1700000000, "created": 1},
                                         "retrained_at", "created"))
        self.assertEqual(1, stated_added_at({"retrained_at": None, "created": 1},
                                             "retrained_at", "created"))
        for absent in ({}, {"created": None}, {"created": 0}, {"created": -5},
                       {"created": "yesterday"}, {"created": True}):
            self.assertIsNone(stated_added_at(absent, "created"), absent)
        self.assertIsNone(stated_added_at({}, "imported_at"),
                          "no key named means no date, not an error")


class NormalisationTests(CatalogueFixture):
    def test_every_supported_family_appears_with_its_kind_and_source(self):
        lora = self.seed_lora()
        builtin = self.seed_builtin()
        clone = self.seed_clone()
        design = self.seed_design()

        catalogue = self.catalogue()
        rows = self.voices_by_id()

        self.assertEqual({"lora", "builtin_lora", "clone", "design"}, set(catalogue["kinds"]))
        for voice_id in (lora, builtin, clone, design):
            self.assertIn(voice_id, rows)
        self.assertEqual("Trained LoRA", rows[lora]["source"])
        self.assertEqual("Built-in LoRA", rows[builtin]["source"])
        self.assertEqual("Uploaded clone", rows[clone]["source"])
        self.assertEqual("Designed voice", rows[design]["source"])

    def test_the_identity_is_the_phase_two_scheme(self):
        """The library mints ids with Phase 2's scheme and accepts them back."""
        self.seed_lora()
        self.seed_design()
        rows = self.voices_by_id()
        for voice_id, row in rows.items():
            kind, native = self.identity.split_voice_id(voice_id)
            self.assertIn(kind, ("lora", "builtin_lora", "clone", "design"))
            self.assertEqual(native, row["native_id"])
            self.assertEqual(voice_id, self.identity.voice_id(kind, native))

    def test_a_source_that_states_nothing_is_unknown_not_guessed(self):
        clone = self.seed_clone()
        design = self.seed_design()

        rows = self.voices_by_id()

        for voice_id in (clone, design):
            row = rows[voice_id]
            self.assertEqual(SOURCE_UNKNOWN, row["gender_source"], voice_id)
            self.assertEqual(SOURCE_UNKNOWN, row["age_group_source"], voice_id)
            self.assertEqual(SOURCE_UNKNOWN, row["gender"], voice_id)
            self.assertEqual(SOURCE_UNKNOWN, row["age_group"], voice_id)

    def test_a_stated_gender_is_marked_declared(self):
        lora = self.seed_lora(gender="female", name="alto_f")
        row = self.voices_by_id()[lora]
        self.assertEqual("female", row["gender"])
        self.assertEqual(SOURCE_DECLARED, row["gender_source"])

    def test_a_guessed_gender_is_marked_inferred(self):
        # No `gender` field, but the name says it - the shared inference catches it.
        lora = self.seed_lora(name="breathy_alto_50s_f_fantasy", description="")
        row = self.voices_by_id()[lora]
        self.assertEqual("female", row["gender"])
        self.assertEqual(SOURCE_INFERRED, row["gender_source"],
                         "a guess must never be presented as a stated value")

    def test_realisation_distinguishes_families_that_share_a_kind(self):
        self.seed_lora()
        self.seed_clone()
        self.seed_design()

        rows = self.voices_by_id()

        self.assertEqual("adapter", rows["lora:tenor_deep"]["realisation"])
        self.assertEqual("clone_recording", rows["clone:clip_1"]["realisation"])
        self.assertEqual("description", rows["design:narrator_1"]["realisation"])

    def test_unavailable_voices_are_listed_with_a_reason(self):
        self.write_json("lora_models/manifest.json", [{"id": "ghost", "name": "ghost"}])
        row = self.voices_by_id()["lora:ghost"]
        self.assertFalse(row["available"])
        self.assertEqual("unavailable", row["availability"])
        self.assertIn("not on disk", row["unavailable_reason"])

    def test_a_builtin_that_is_not_downloaded_is_unavailable(self):
        self.write_json("builtin_lora/manifest.json",
                        [{"id": "watson", "name": "watson", "gender": "male"}])
        row = self.voices_by_id()["builtin_lora:builtin_watson"]
        self.assertFalse(row["available"])
        self.assertIn("not been downloaded", row["unavailable_reason"])

    def test_a_clone_without_a_transcript_is_listed_but_unassignable(self):
        self.seed_clone(ref_text="")
        row = self.voices_by_id()["clone:clip_1"]
        self.assertFalse(row["available"])
        self.assertIn("transcript", row["unavailable_reason"])

    def test_a_preview_points_at_a_recording_that_exists(self):
        design = self.seed_design(with_preview=True)
        row = self.voices_by_id()[design]
        self.assertTrue(row["preview_capable"])
        self.assertEqual("/designed_voices/narrator_1_preview.wav", row["preview_url"])
        self.assertEqual("recording", row["preview_kind"])

    def test_a_voice_whose_recording_is_missing_reports_no_preview(self):
        design = self.seed_design(with_preview=False)
        row = self.voices_by_id()[design]
        self.assertFalse(row["preview_capable"])
        self.assertIsNone(row["preview_url"])

    def test_an_adapter_preview_is_offered_only_when_the_sample_is_present(self):
        lora = self.seed_lora()
        self.assertFalse(self.voices_by_id()[lora]["preview_capable"])
        self.write_file("lora_models/tenor_deep/preview_sample.wav")
        self.assertTrue(self.voices_by_id()[lora]["preview_capable"])

    def test_tags_are_empty_rather_than_inferred(self):
        self.seed_lora(description="a warm alto with plenty of breath")
        row = self.catalogue()["voices"][0]
        self.assertEqual([], row["tags"],
                         "no source publishes tags; an inferred tag must not be invented")

    def test_metadata_carries_what_the_source_said_and_nothing_interpreted(self):
        self.seed_lora(added_at=1700000000)
        row = self.catalogue()["voices"][0]
        self.assertEqual(12, row["metadata"]["epochs"])
        self.assertEqual(40, row["metadata"]["sample_count"])
        self.assertEqual(1700000000, row["added_at"])

    def test_malformed_source_rows_are_skipped_not_fatal(self):
        manifest = ["not a row", {"name": "no id"}, {"id": "  "}, None]
        self.write_json("lora_models/manifest.json", manifest)
        self.seed_design()

        catalogue = self.catalogue()

        self.assertEqual(["design:narrator_1"],
                         [row["voice_id"] for row in catalogue["voices"]])

    def test_a_malformed_adapter_manifest_costs_only_the_adapters(self):
        self.write_json("lora_models/manifest.json", [{"id": "..\\escape"}])
        design = self.seed_design()

        catalogue = self.catalogue()

        self.assertEqual([design], [row["voice_id"] for row in catalogue["voices"]])
        self.assertTrue(catalogue["warnings"])
        self.assertIn("LoRA", catalogue["warnings"][0])

    def test_two_families_claiming_one_native_id_stay_two_voices(self):
        self.seed_lora(adapter_id="shared_id")
        self.seed_clone(voice_id="shared_id")

        rows = self.voices_by_id()

        self.assertIn("lora:shared_id", rows)
        self.assertIn("clone:shared_id", rows)
        self.assertNotEqual(rows["lora:shared_id"]["voice_id"], rows["clone:shared_id"]["voice_id"])

    def test_two_identical_ids_within_one_family_are_refused_as_ambiguous(self):
        """Two rows claiming one id would make a selection ambiguous, and a
        guess about which the user meant is not a save."""
        manifest = self.read_json("designed_voices/manifest.json")
        manifest.append({"id": "twin", "name": "twin", "description": "one",
                         "filename": "a.wav"})
        manifest.append({"id": "twin", "name": "twin", "description": "two",
                         "filename": "b.wav"})
        self.write_json("designed_voices/manifest.json", manifest)

        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.catalogue()

        self.assertEqual("duplicate_voice_ids", caught.exception.code)

    def test_unsupported_families_are_reported_rather_than_hidden(self):
        catalogue = self.catalogue()
        self.assertIn("ensemble", catalogue["unsupported_kinds"])
        self.assertIn("custom", catalogue["unsupported_kinds"])
        self.assertIn("several characters", catalogue["unsupported_kinds"]["ensemble"])
        for row in catalogue["voices"]:
            self.assertIn(row["kind"], catalogue["kinds"],
                          "a row of an unlisted family would be a fake row")

    def test_a_designed_voice_keeps_the_identity_an_assignment_stores(self):
        self.seed_design(voice_id="narrator_1")
        row = self.voices_by_id()["design:narrator_1"]
        self.assertEqual("designed_voices/narrator_1_preview.wav", row["ref_audio"])
        self.assertEqual(row["voice_id"], self.identity.catalogue_voice_id_for(
            {"type": "design", "ref_audio": row["ref_audio"]}))

    def test_the_catalogue_carries_a_schema_version(self):
        self.assertEqual(1, self.catalogue()["schema_version"])


class FavoriteTests(CatalogueFixture):
    def test_favouriting_reuses_the_applications_own_store(self):
        lora = self.seed_lora()

        result = self.assignment.set_voice_favorite(lora, True)

        self.assertEqual(["tenor_deep"], self.read_json("voice_library.json")["favorites"])
        self.assertTrue(result["favorite"])
        self.assertEqual(lora, result["voice_id"])

    def test_unfavouriting_removes_it_again(self):
        lora = self.seed_lora()
        self.assignment.set_voice_favorite(lora, True)

        self.assignment.set_voice_favorite(lora, False)

        self.assertEqual([], self.read_json("voice_library.json")["favorites"])

    def test_setting_an_existing_state_is_idempotent_not_a_toggle(self):
        lora = self.seed_lora()
        self.assignment.set_voice_favorite(lora, True)
        self.assignment.set_voice_favorite(lora, True)
        self.assignment.set_voice_favorite(lora, True)

        self.assertEqual(["tenor_deep"], self.read_json("voice_library.json")["favorites"],
                         "an explicit set must not accumulate or undo itself")

    def test_a_family_with_nowhere_to_store_a_favourite_is_refused_with_a_reason(self):
        for voice_id, kind in ((self.seed_clone(), "clone"), (self.seed_design(), "design")):
            with self.subTest(kind=kind):
                with self.assertRaises(self.assignment.VoiceCommandError) as caught:
                    self.assignment.set_voice_favorite(voice_id, True)
                self.assertEqual("favorite_unsupported", caught.exception.code)
                self.assertIn("LoRA", caught.exception.message)
        self.assertEqual([], self.read_json("voice_library.json")["favorites"],
                         "a refused favourite must not be written")

    def test_an_unknown_voice_cannot_be_favourited(self):
        self.seed_lora()
        with self.assertRaises(self.assignment.VoiceCommandError) as caught:
            self.assignment.set_voice_favorite("lora:nope", True)
        self.assertEqual("unknown_voice", caught.exception.code)

    def test_a_malformed_voice_id_is_refused_before_any_lookup(self):
        for voice_id in ("nonsense", "", None, "ensemble:x", "custom:Ryan"):
            with self.subTest(voice_id=voice_id):
                with self.assertRaises(self.assignment.VoiceCommandError) as caught:
                    self.assignment.set_voice_favorite(voice_id, True)
                self.assertIn(caught.exception.code, ("invalid_voice", "unknown_voice"))

    def test_a_voice_whose_files_are_gone_can_still_be_favourited(self):
        """A favourite is a note to self about a voice worth finding again, which
        is most useful exactly when the files are missing."""
        self.write_json("lora_models/manifest.json", [{"id": "gone", "name": "gone"}])
        result = self.assignment.set_voice_favorite("lora:gone", True)
        self.assertTrue(result["favorite"])

    def test_the_catalogue_reports_the_favourite_flag(self):
        lora = self.seed_lora()
        self.assertFalse(self.voices_by_id()[lora]["favorite"])
        self.assignment.set_voice_favorite(lora, True)
        self.assertTrue(self.voices_by_id()[lora]["favorite"])

    def test_only_adapter_families_advertise_favourite_support(self):
        lora = self.seed_lora()
        self.seed_builtin()
        self.seed_clone()
        self.seed_design()

        rows = self.voices_by_id()

        self.assertTrue(rows[lora]["favorite_supported"])
        self.assertTrue(rows["builtin_lora:builtin_watson"]["favorite_supported"])
        self.assertFalse(rows["clone:clip_1"]["favorite_supported"])
        self.assertFalse(rows["design:narrator_1"]["favorite_supported"])
        self.assertEqual(["lora", "builtin_lora"], self.catalogue()["favorite_kinds"])

    def test_the_favourites_endpoint_round_trips(self):
        lora = self.seed_lora()

        with self.client() as client:
            first = client.post("/api/voices-v2/favorite",
                                json={"voice_id": lora, "favorite": True})
            self.assertEqual(200, first.status_code, first.text)
            self.assertEqual(["tenor_deep"], first.json()["favorites"])
            listed = client.get("/api/voices-v2/voices").json()
            self.assertTrue(next(row for row in listed["voices"]
                                 if row["voice_id"] == lora)["favorite"])
            second = client.post("/api/voices-v2/favorite",
                                 json={"voice_id": lora, "favorite": False})
            self.assertEqual([], second.json()["favorites"])

    def test_a_refused_favourite_carries_its_code(self):
        self.seed_design()
        with self.client() as client:
            response = client.post("/api/voices-v2/favorite",
                                   json={"voice_id": "design:narrator_1", "favorite": True})
        self.assertEqual(409, response.status_code)
        self.assertEqual("favorite_unsupported", response.json()["detail"]["code"])

    def test_a_malformed_favourite_request_is_rejected_by_the_schema(self):
        with self.client() as client:
            for body in ({"favorite": True}, {"voice_id": "", "favorite": True},
                         {"voice_id": "lora:x"}):
                with self.subTest(body=body):
                    self.assertEqual(422, client.post("/api/voices-v2/favorite",
                                                      json=body).status_code)


class EndpointShapeTests(CatalogueFixture):
    def test_the_catalogue_endpoint_returns_one_complete_document(self):
        self.seed_lora()
        self.seed_design()

        with self.client() as client:
            response = client.get("/api/voices-v2/voices")

        self.assertEqual(200, response.status_code)
        payload = response.json()
        for key in ("schema_version", "voices", "counts", "kinds", "favorite_kinds",
                    "warnings", "unsupported_kinds"):
            self.assertIn(key, payload)
        self.assertEqual({"total": 2, "available": 2, "unavailable": 0}, payload["counts"])
        # Everything a client-side filter needs, so it never asks again per voice.
        for row in payload["voices"]:
            for key in ("voice_id", "native_id", "kind", "name", "source", "gender",
                        "gender_source", "age_group", "age_group_source", "available",
                        "availability", "favorite", "favorite_supported", "preview_capable",
                        "tags", "metadata"):
                self.assertIn(key, row)

    def test_the_catalogue_read_writes_nothing(self):
        self.seed_lora()
        before = self.snapshot()

        self.catalogue()

        self.assertEqual(before, self.snapshot())

    def snapshot(self):
        out = {}
        for root, _dirs, files in os.walk(self.tmp):
            for name in files:
                if name.endswith(".lock"):
                    continue
                path = os.path.join(root, name)
                with open(path, "rb") as handle:
                    out[os.path.relpath(path, self.tmp)] = handle.read()
        return out

    def test_the_existing_catalogue_endpoints_are_unchanged(self):
        """The library is a consumer of the application's data, not a replacement
        for its own routes."""
        self.seed_lora()
        app = FastAPI()
        app.include_router(self.voices_router.router)
        app.include_router(self.voice_library_router.router)
        app.include_router(self.lora_router.router)

        with TestClient(app) as client:
            self.assertEqual(200, client.get("/api/voice_config/snapshot").status_code)
            self.assertEqual(200, client.get("/api/lora/models").status_code)
            favourites = client.post("/api/voice_library/favorites/tenor_deep")
            self.assertEqual(200, favourites.status_code, favourites.text)
            self.assertEqual(["tenor_deep"], favourites.json()["favorites"])


if __name__ == "__main__":
    unittest.main()