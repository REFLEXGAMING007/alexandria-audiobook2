"""Voices V2 generated previews: the job board.

The interesting properties of a preview system are all about what happens when
something goes wrong or happens twice, so most of these tests are about refusal,
deduplication, recovery and tolerance rather than the happy path.

The synthesis itself is **not** exercised: rendering audio needs the GPU, and the
point of this module is the orchestration around it. `ensure_lora_preview_audio`
is replaced with a fake that returns the same shape the real primitive does, so
what is under test is V2's job lifecycle and not the engine.
"""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


class PreviewFixture(unittest.TestCase):
    """A temp data dir, one trained adapter, and no GPU."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        import core
        import routers.lora as lora_router
        import voices_v2.preview_jobs as jobs
        import voices_v2.voice_assignment as assignment
        import voices_v2.voice_identity as identity

        self.jobs = jobs
        self.lora = lora_router
        self.requests = []
        self.script = {
            # What the real primitive returns on a miss.
            "generated": {"status": "generated", "audio_url": "/lora_models/tenor/preview_sample.wav"},
            # And on a hit.
            "cached": {"status": "cached", "audio_url": "/lora_models/tenor/preview_sample.wav"},
        }

        # The directory constants live in `core`, but the manifest paths are
        # derived at import time in the modules that read them, so every one of
        # those modules needs the redirect.
        for module in (core, jobs, lora_router, assignment, identity):
            for name, value in (
                ("DATA_DIR", self.tmp),
                ("LORA_MODELS_DIR", os.path.join(self.tmp, "lora_models")),
                ("LORA_MODELS_MANIFEST", os.path.join(self.tmp, "lora_models", "manifest.json")),
                ("BUILTIN_LORA_DIR", os.path.join(self.tmp, "builtin_lora")),
                ("BUILTIN_LORA_MANIFEST", os.path.join(self.tmp, "builtin_lora", "manifest.json")),
                ("CLONE_VOICES_DIR", os.path.join(self.tmp, "clone_voices")),
                ("CLONE_VOICES_MANIFEST", os.path.join(self.tmp, "clone_voices", "manifest.json")),
                ("DESIGNED_VOICES_DIR", os.path.join(self.tmp, "designed_voices")),
                ("DESIGNED_VOICES_MANIFEST",
                 os.path.join(self.tmp, "designed_voices", "manifest.json")),
                ("VOICE_LIBRARY_PATH", os.path.join(self.tmp, "voice_library.json")),
                ("CHARACTER_ALIASES_PATH", os.path.join(self.tmp, "character_aliases.json")),
            ):
                if hasattr(module, name):
                    patcher = patch.object(module, name, value)
                    patcher.start()
                    self.addCleanup(patcher.stop)

        for directory in ("lora_models", "builtin_lora", "clone_voices", "designed_voices"):
            os.makedirs(os.path.join(self.tmp, directory), exist_ok=True)
        self.write_json("voice_config.json", {})
        self.write_json("voice_library.json", {"shared": {}, "casts": {}, "favorites": []})
        self.write_json("builtin_lora/manifest.json", [])
        self.write_json("annotated_script.json", [])
        self.write_json("state.json", {"active_book_id": "book"})

        # One adapter whose bundle exists, so the catalogue calls it available.
        os.makedirs(os.path.join(self.tmp, "lora_models", "tenor"), exist_ok=True)
        self.write_file("lora_models/tenor/adapter_config.json", b"{}")
        self.write_json("lora_models/manifest.json",
                        [{"id": "tenor", "name": "tenor", "description": "Deep tenor"}])

        # Run jobs on a thread we control, so no test races a worker. Without
        # this the real daemon thread would drain the queue between the request
        # and the assertion about what was queued.
        patcher = patch.object(jobs, "_WORK_QUEUE", __import__("queue").Queue())
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(jobs, "_ensure_worker", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        jobs._WORKER = None
        jobs._RECOVERY_DONE = True

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

    def read_jobs(self):
        path = os.path.join(self.tmp, self.jobs.JOB_STORE_NAME)
        if not os.path.isfile(path):
            return {}
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("jobs", {})

    def write_jobs(self, jobs):
        self.write_json(self.jobs.JOB_STORE_NAME,
                        {"schema_version": 1, "jobs": jobs})

    def drain(self, limit=40):
        """Run queued jobs synchronously, as the worker would."""
        ran = []
        while not self.jobs._WORK_QUEUE.empty() and len(ran) < limit:
            job_id = self.jobs._WORK_QUEUE.get()
            try:
                self.jobs._run_job(job_id)
                ran.append(job_id)
            finally:
                self.jobs._WORK_QUEUE.task_done()
        return ran

    def fake_generate(self, mode="generated"):
        def run(native_id):
            self.requests.append(native_id)
            if mode == "http":
                raise HTTPException(status_code=400, detail="Lora test is already running.")
            if mode == "unusable":
                from audio_validation import GeneratedAudioError
                raise GeneratedAudioError("undecodable audio")
            if mode == "boom":
                raise RuntimeError("an internal detail that must never reach a client")
            return dict(self.script[mode])
        return run

    def with_generate(self, mode="generated"):
        patcher = patch.object(self.lora, "ensure_lora_preview_audio", self.fake_generate(mode))
        patcher.start()
        self.addCleanup(patcher.stop)

    def client(self):
        from routers import voices_v2 as v2

        app = FastAPI()
        app.include_router(v2.router)
        return TestClient(app)


class RequestTests(PreviewFixture):
    def test_a_valid_request_queues_a_job_and_returns_immediately(self):
        self.with_generate()
        result = self.jobs.request_preview("lora:tenor")

        self.assertEqual("queued", result["status"])
        self.assertTrue(result["job_id"])
        self.assertEqual("lora:tenor", result["voice_id"])
        self.assertFalse(result["deduplicated"])
        self.assertEqual(1, self.jobs._WORK_QUEUE.qsize(), "queued, not run inline")

    def test_the_default_profile_is_the_one_the_application_already_uses(self):
        from routers.lora import LORA_PREVIEW_TEXT

        self.assertEqual(LORA_PREVIEW_TEXT,
                         self.jobs.PREVIEW_PROFILES["standard"]["text"],
                         "a second preview sentence would make previews incomparable")

    def test_an_unknown_voice_is_refused(self):
        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.request_preview("lora:nope")
        self.assertEqual("unknown_voice", caught.exception.code)
        self.assertEqual(404, caught.exception.status)

    def test_a_voice_with_no_files_is_refused_as_retryable(self):
        self.write_json("lora_models/manifest.json",
                        [{"id": "ghost", "name": "ghost"}])
        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.request_preview("lora:ghost")
        self.assertEqual("voice_unavailable", caught.exception.code)
        self.assertTrue(caught.exception.retryable)

    def test_a_family_that_is_not_generated_is_refused_with_its_reason(self):
        """Clones and designs already own their audio; regenerating them would
        create a second preview for a voice that already has one."""
        self.write_json("designed_voices/manifest.json",
                        [{"id": "d1", "name": "D1", "description": "calm",
                          "filename": "d1_preview.wav"}])
        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.request_preview("design:d1")
        self.assertEqual("preview_not_generated", caught.exception.code)
        self.assertIn("preview recording", caught.exception.message)

    def test_an_unknown_profile_is_refused(self):
        self.with_generate()
        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.request_preview("lora:tenor", "cinematic")
        self.assertEqual("unknown_profile", caught.exception.code)

    def test_a_malformed_voice_id_is_refused_before_any_lookup(self):
        for voice_id in ("", "   ", None, 7, "../etc/passwd", "lora:../../x"):
            with self.subTest(voice_id=voice_id):
                with self.assertRaises(self.jobs.PreviewError) as caught:
                    self.jobs.request_preview(voice_id)
                self.assertIn(caught.exception.code,
                              ("unknown_voice", "preview_not_generated", "voice_unavailable"))

    def test_a_traversing_id_never_becomes_a_path(self):
        """The browser names a voice; the catalogue decides what that means. A
        traversing id resolves to nothing and is refused."""
        self.with_generate()
        for voice_id in ("lora:../evil", "lora:%2e%2e%2fevil", "lora:..\\evil"):
            with self.subTest(voice_id=voice_id):
                with self.assertRaises(self.jobs.PreviewError):
                    self.jobs.request_preview(voice_id)
        self.assertEqual([], self.requests, "nothing was synthesised for a bad id")

    def test_an_odd_name_with_spaces_and_unicode_survives_a_round_trip(self):
        """Identity, not a filename: a name may hold anything the manifest allows,
        and the job still records the id it was given."""
        self.write_json("lora_models/manifest.json", [
            {"id": "voice_1", "name": "Voix Sophisticated — Élite (日本語)"},
            {"id": "tenor", "name": "tenor"}])
        os.makedirs(os.path.join(self.tmp, "lora_models", "voice_1"), exist_ok=True)
        self.write_file("lora_models/voice_1/adapter_config.json", b"{}")
        self.with_generate()

        result = self.jobs.request_preview("lora:voice_1")

        self.assertEqual("lora:voice_1", result["voice_id"])
        self.assertEqual("Voix Sophisticated — Élite (日本語)", result["name"])
        # The board is keyed by the job uuid, so an awkward name is recorded as
        # data and never used to build a path.
        stored = self.read_jobs()
        self.assertEqual([result["job_id"]], list(stored))
        self.drain()
        self.assertEqual(["voice_1"], self.requests)


class CompletionTests(PreviewFixture):
    def test_a_completed_job_records_the_url(self):
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()

        job = self.jobs.get_job(queued["job_id"])
        self.assertEqual("completed", job["status"])
        self.assertEqual("/lora_models/tenor/preview_sample.wav", job["audio_url"])
        self.assertEqual(["tenor"], self.requests)
        self.assertIsNotNone(job["completed_at"])
        self.assertEqual(1.0, self.jobs.public_job(job)["progress"])
        self.assertTrue(self.jobs.public_job(job)["terminal"])

    def test_a_cache_hit_is_recorded_as_such(self):
        self.with_generate("cached")
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()

        self.assertTrue(self.jobs.get_job(queued["job_id"])["cached"])

    def test_unusable_audio_fails_the_job_with_a_safe_message(self):
        self.with_generate("unusable")
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()

        job = self.jobs.get_job(queued["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertEqual("invalid_audio", job["error_code"])
        self.assertNotIn("undecodable", job["error"],
                         "the technical cause stays in the log")

    def test_a_busy_gpu_fails_retryably_rather_than_sticking(self):
        self.with_generate("http")
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()

        job = self.jobs.get_job(queued["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertEqual("busy", job["error_code"])
        self.assertIn("GPU", job["error"])

    def test_an_internal_error_never_reaches_the_client(self):
        self.with_generate("boom")
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()

        job = self.jobs.get_job(queued["job_id"])
        self.assertEqual("failed", job["status"])
        self.assertNotIn("internal detail", job["error"])
        self.assertNotIn("Traceback", job["error"])

    def test_a_response_with_no_audio_fails_the_job(self):
        self.with_generate()
        self.lora.ensure_lora_preview_audio = lambda native_id: {"status": "generated"}
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()
        self.assertEqual("failed", self.jobs.get_job(queued["job_id"])["status"])


class DeduplicationTests(PreviewFixture):
    def test_a_second_request_while_queued_returns_the_same_job(self):
        self.with_generate()
        first = self.jobs.request_preview("lora:tenor")
        second = self.jobs.request_preview("lora:tenor")

        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["deduplicated"])
        self.assertEqual(1, self.jobs._WORK_QUEUE.qsize(),
                         "three clicks must not become three renders")
        self.assertEqual(1, len(self.read_jobs()))

    def test_a_request_while_running_returns_the_same_job(self):
        self.with_generate()
        first = self.jobs.request_preview("lora:tenor")
        self.jobs._update(first["job_id"], status="running", started_at=time.time())

        second = self.jobs.request_preview("lora:tenor")

        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual("running", second["status"])
        self.assertEqual(1, self.jobs._WORK_QUEUE.qsize())

    def test_a_completed_job_with_its_file_present_is_a_cache_hit(self):
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()
        self.write_file("lora_models/tenor/preview_sample.wav")

        again = self.jobs.request_preview("lora:tenor")

        self.assertEqual(queued["job_id"], again["job_id"])
        self.assertTrue(again["deduplicated"])
        self.assertEqual(0, self.jobs._WORK_QUEUE.qsize(), "nothing was re-rendered")
        self.assertEqual(["tenor"], self.requests, "only the first request rendered")

    def test_a_different_profile_is_a_different_request(self):
        self.with_generate()
        jobs_module = self.jobs
        original = dict(jobs_module.PREVIEW_PROFILES)
        jobs_module.PREVIEW_PROFILES["loud"] = dict(original["standard"],
                                                    text="A different sentence entirely.")
        self.addCleanup(jobs_module.PREVIEW_PROFILES.update, original)
        self.addCleanup(jobs_module.PREVIEW_PROFILES.pop, "loud", None)

        first = self.jobs.request_preview("lora:tenor", "standard")
        second = self.jobs.request_preview("lora:tenor", "loud")

        self.assertNotEqual(first["job_id"], second["job_id"],
                            "a different profile is a different request")
        self.assertEqual(2, self.jobs._WORK_QUEUE.qsize())

    def test_the_fingerprint_covers_the_voice_the_profile_and_the_text(self):
        standard = self.jobs.fingerprint("lora:tenor", "standard", "text")
        self.assertNotEqual(standard,
                            self.jobs.fingerprint("lora:other", "standard", "text"))
        self.assertNotEqual(standard,
                            self.jobs.fingerprint("lora:tenor", "loud", "text"))
        self.assertNotEqual(standard,
                            self.jobs.fingerprint("lora:tenor", "standard", "other"))
        self.assertEqual(standard,
                         self.jobs.fingerprint("lora:tenor", "standard", "text"))

    def test_a_fingerprint_is_a_digest_and_leaks_no_name(self):
        digest = self.jobs.fingerprint("lora:Voix Élite", "standard", "text")
        self.assertEqual(64, len(digest))
        self.assertNotIn("lora", digest)


class CancellationTests(PreviewFixture):
    def test_a_queued_job_can_be_cancelled(self):
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")

        cancelled = self.jobs.cancel_job(queued["job_id"])

        self.assertEqual("cancelled", cancelled["status"])
        self.assertTrue(cancelled["terminal"])

    def test_a_cancelled_job_is_not_then_run(self):
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")
        self.jobs.cancel_job(queued["job_id"])

        self.drain()

        self.assertEqual([], self.requests, "a cancelled job never renders")
        self.assertEqual("cancelled", self.jobs.get_job(queued["job_id"])["status"])

    def test_a_running_job_is_reported_as_not_cancellable(self):
        """The primitive owns the GPU claim and the engine call; stopping it would
        release a claim its worker still holds."""
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")
        self.jobs._update(queued["job_id"], status="running", started_at=time.time())

        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.cancel_job(queued["job_id"])

        self.assertEqual("job_running", caught.exception.code)
        self.assertEqual(409, caught.exception.status)
        self.assertEqual("running", self.jobs.get_job(queued["job_id"])["status"])

    def test_cancelling_a_terminal_job_is_a_no_op(self):
        self.with_generate()
        queued = self.jobs.request_preview("lora:tenor")
        self.drain()
        result = self.jobs.cancel_job(queued["job_id"])
        self.assertEqual("completed", result["status"])

    def test_cancelling_an_unknown_job_is_refused(self):
        with self.assertRaises(self.jobs.PreviewError) as caught:
            self.jobs.cancel_job("nope")
        self.assertEqual("unknown_job", caught.exception.code)


class StoreToleranceTests(PreviewFixture):
    def test_a_missing_store_reads_as_empty(self):
        """The ordinary first-run case: nothing has ever generated a preview."""
        self.assertFalse(os.path.isfile(os.path.join(self.tmp, self.jobs.JOB_STORE_NAME)))
        self.assertEqual({}, self.jobs._read_store()["jobs"])

    def test_an_empty_file_reads_as_empty(self):
        self.write_file(self.jobs.JOB_STORE_NAME, b"")
        self.assertEqual({}, self.jobs._read_store()["jobs"])

    def test_a_file_of_junk_reads_as_empty(self):
        for junk in (b"", b"{not json", b"[1,2,3]", b'"a string"', b"null"):
            with self.subTest(junk=junk[:12]):
                self.write_file(self.jobs.JOB_STORE_NAME, junk)
                self.assertEqual({}, self.jobs._read_store()["jobs"])

    def test_a_store_of_the_wrong_shape_reads_as_empty(self):
        for payload in ([1, 2, 3], "a string", {"jobs": "nope"}, {"jobs": [1]}):
            with self.subTest(payload=payload):
                self.write_json(self.jobs.JOB_STORE_NAME, payload)
                self.assertEqual({}, self.jobs._read_store()["jobs"])

    def test_one_broken_record_does_not_take_the_board_with_it(self):
        """The whole point of tolerance: a corrupt entry loses its own job, not
        every other one."""
        self.write_jobs({
            "good": {"job_id": "good", "voice_id": "lora:tenor", "status": "completed",
                     "created_at": 1.0, "audio_url": "/lora_models/tenor/preview_sample.wav"},
            "not-a-dict": "oops",
            "bad-status": {"job_id": "bad-status", "voice_id": "lora:x", "status": "banana"},
            "no-voice": {"job_id": "no-voice", "status": "queued"},
        })

        jobs = self.jobs._read_store()["jobs"]

        self.assertEqual(["good"], list(jobs))

    def test_a_completed_job_whose_file_is_gone_is_stale_not_a_dead_button(self):
        # The record claims a preview that is not on disk, which is exactly the
        # case that would otherwise render a Play button with nothing behind it.
        self.write_jobs({
            "gone": {"job_id": "gone", "voice_id": "lora:tenor", "status": "completed",
                     "created_at": 1.0,
                     "audio_url": "/lora_models/tenor/preview_sample.wav"}})

        self.jobs._RECOVERY_DONE = False
        changed = self.jobs.recover_jobs()

        self.assertEqual(1, changed)
        job = self.jobs.get_job("gone")
        self.assertEqual("stale", job["status"])
        self.assertEqual("file_missing", job["error_code"])
        self.assertIsNone(job["audio_url"])

    def test_a_stale_job_offers_generation_again(self):
        self.write_jobs({
            "gone": {"job_id": "gone", "voice_id": "lora:tenor", "status": "completed",
                     "created_at": 1.0,
                     "audio_url": "/lora_models/tenor/preview_sample.wav"}})
        self.jobs._RECOVERY_DONE = False
        self.jobs.recover_jobs()

        self.write_file("lora_models/tenor/preview_sample.wav")
        result = self.jobs.request_preview("lora:tenor", "standard")

        self.assertEqual("queued", result["status"],
                         "a stale job is not a cache hit: the file is gone, so the "
                         "preview is generated again")
        self.assertNotEqual("gone", result["job_id"])
        self.assertEqual(1, self.jobs._WORK_QUEUE.qsize())


class RecoveryTests(PreviewFixture):
    def test_jobs_left_running_by_a_dead_process_become_stale(self):
        self.write_jobs({
            "a": {"job_id": "a", "voice_id": "lora:tenor", "status": "running",
                  "created_at": 1.0, "started_at": 1.5},
            "b": {"job_id": "b", "voice_id": "lora:tenor", "status": "queued",
                  "created_at": 2.0},
            "c": {"job_id": "c", "voice_id": "lora:tenor", "status": "failed",
                  "created_at": 3.0},
        })
        self.jobs._RECOVERY_DONE = False

        self.assertEqual(2, self.jobs.recover_jobs())
        self.assertEqual("stale", self.jobs.get_job("a")["status"])
        self.assertEqual("stale", self.jobs.get_job("b")["status"])
        self.assertEqual("failed", self.jobs.get_job("c")["status"],
                         "a real failure is not rewritten into staleness")

    def test_recovery_runs_once_per_process(self):
        self.write_jobs({
            "a": {"job_id": "a", "voice_id": "lora:tenor", "status": "running",
                  "created_at": 1.0}})
        self.jobs._RECOVERY_DONE = False
        self.assertEqual(1, self.jobs.recover_jobs())
        self.assertEqual(0, self.jobs.recover_jobs())

    def test_a_valid_completed_job_is_left_alone(self):
        self.write_file("lora_models/tenor/preview_sample.wav")
        self.write_jobs({
            "ok": {"job_id": "ok", "voice_id": "lora:tenor", "status": "completed",
                   "created_at": 1.0,
                   "audio_url": "/lora_models/tenor/preview_sample.wav"}})
        self.jobs._RECOVERY_DONE = False
        self.assertEqual(0, self.jobs.recover_jobs())
        self.assertEqual("completed", self.jobs.get_job("ok")["status"])


class RetentionTests(PreviewFixture):
    def test_the_board_is_bounded_and_old_records_are_dropped_first(self):
        self.jobs.MAX_RETAINED_JOBS = 5
        self.addCleanup(setattr, self.jobs, "MAX_RETAINED_JOBS", 50)
        self.with_generate()
        for index in range(8):
            # Distinct profiles so each request is genuinely a new one; the point
            # is that the board stays bounded, not that the cache is exercised.
            self.jobs.PREVIEW_PROFILES[f"profile{index}"] = {
                "text": "Sentence number %d." % index, "instruct": ""}
            self.addCleanup(self.jobs.PREVIEW_PROFILES.pop, f"profile{index}", None)
            result = self.jobs.request_preview("lora:tenor", f"profile{index}")
            self.drain()
            self.assertEqual("completed", self.jobs.get_job(result["job_id"])["status"])

        jobs = self.read_jobs()

        self.assertLessEqual(len(jobs), 5)
        self.assertEqual(5, len(jobs))

    def test_no_audio_is_ever_deleted_by_retention(self):
        self.write_file("lora_models/tenor/preview_sample.wav")
        self.write_json(self.jobs.JOB_STORE_NAME, {
            "schema_version": 1,
            "jobs": {"old": {"job_id": "old", "voice_id": "lora:tenor",
                             "status": "completed", "created_at": 1.0,
                             "audio_url": "/lora_models/tenor/preview_sample.wav"}}})
        self.jobs.MAX_RETAINED_JOBS = 1
        self.addCleanup(setattr, self.jobs, "MAX_RETAINED_JOBS", 50)
        self.jobs._update("old", error="touch")

        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "lora_models", "tenor",
                                                     "preview_sample.wav")),
                        "pruning job metadata must never delete the application's audio")


class RouteTests(PreviewFixture):
    def test_the_lifecycle_over_http(self):
        self.with_generate()
        with self.client() as client:
            created = client.post("/api/voices-v2/previews",
                                  json={"voice_id": "lora:tenor", "profile": "standard"})
            self.assertEqual(200, created.status_code, created.text)
            job_id = created.json()["job_id"]
            self.assertEqual("queued", created.json()["status"])

            status = client.get(f"/api/voices-v2/previews/{job_id}")
            self.assertEqual(200, status.status_code)
            self.assertEqual(job_id, status.json()["job_id"])
            self.assertEqual(0.0, status.json()["progress"])

            self.drain()
            done = client.get(f"/api/voices-v2/previews/{job_id}").json()
            self.assertEqual("completed", done["status"])
            self.assertEqual(1.0, done["progress"])
            self.assertEqual("/lora_models/tenor/preview_sample.wav", done["preview_url"])
            self.assertTrue(done["terminal"])

    def test_a_status_response_hides_internals(self):
        self.with_generate()
        with self.client() as client:
            job_id = client.post("/api/voices-v2/previews",
                                 json={"voice_id": "lora:tenor"}).json()["job_id"]
        body = client.get(f"/api/voices-v2/previews/{job_id}").json()
        for hidden in ("fingerprint", "native_id", "path", "/tmp", "output_path"):
            self.assertNotIn(hidden, body)

    def test_every_refusal_carries_a_code(self):
        self.write_json("lora_models/manifest.json",
                        [{"id": "ghost", "name": "ghost"},
                         {"id": "tenor", "name": "tenor"}])
        with self.client() as client:
            cases = [
                ({"voice_id": "lora:nope"}, 404, "unknown_voice"),
                ({"voice_id": "lora:ghost"}, 409, "voice_unavailable"),
                ({"voice_id": "lora:tenor", "profile": "cinematic"}, 400, "unknown_profile"),
                ({"voice_id": ""}, 422, None),
            ]
            for body, status, code in cases:
                with self.subTest(body=body):
                    response = client.post("/api/voices-v2/previews", json=body)
                    self.assertEqual(status, response.status_code, response.text)
                    if code:
                        self.assertEqual(code, response.json()["detail"]["code"])

    def test_an_unknown_job_id_is_a_404_with_a_code(self):
        with self.client() as client:
            response = client.get("/api/voices-v2/previews/deadbeef")
        self.assertEqual(404, response.status_code)
        self.assertEqual("unknown_job", response.json()["detail"]["code"])

    def test_cancelling_a_running_job_over_http_is_a_409(self):
        self.with_generate()
        with self.client() as client:
            job_id = client.post("/api/voices-v2/previews",
                                 json={"voice_id": "lora:tenor"}).json()["job_id"]
        self.jobs._update(job_id, status="running", started_at=time.time())
        with self.client() as client:
            response = client.post(f"/api/voices-v2/previews/{job_id}/cancel")
        self.assertEqual(409, response.status_code)
        self.assertEqual("job_running", response.json()["detail"]["code"])

    def test_the_catalogue_reports_preview_state(self):
        self.with_generate()
        with self.client() as client:
            before = client.get("/api/voices-v2/voices").json()
            self.assertEqual(["standard"], before["preview_profiles"])
            self.assertEqual(["lora", "builtin_lora"], before["generated_kinds"])
            states = {row["voice_id"]: row["preview_state"] for row in before["voices"]}
            self.assertEqual("none", states["lora:tenor"])
            self.assertTrue(next(row for row in before["voices"]
                                 if row["voice_id"] == "lora:tenor")["preview_generatable"])
            self.assertFalse(next(row for row in before["voices"]
                                  if row["voice_id"] == "lora:tenor")["available"] is False)

            client.post("/api/voices-v2/previews", json={"voice_id": "lora:tenor"})
            self.drain()
            after = client.get("/api/voices-v2/voices").json()
            row = next(row for row in after["voices"] if row["voice_id"] == "lora:tenor")
            self.assertEqual("none", row["preview_state"],
                             "the file is not on disk, so no preview is claimed")


class IsolationTests(PreviewFixture):
    def test_the_job_store_is_its_own_file_and_not_any_voice_file(self):
        self.with_generate()
        before = {name: self.read_json_bytes(name) for name in
                  ("voice_config.json", "voice_library.json", "lora_models/manifest.json")}
        self.jobs.request_preview("lora:tenor")
        self.drain()

        self.assertTrue(os.path.isfile(os.path.join(self.tmp, self.jobs.JOB_STORE_NAME)))
        for name, content in before.items():
            self.assertEqual(content, self.read_json_bytes(name),
                             "%s must never carry job state" % name)

    def test_voice_config_is_never_touched_by_a_preview(self):
        self.write_json("voice_config.json", {"MIRA": {"type": "custom", "voice": "Ryan"}})
        before = self.read_json_bytes("voice_config.json")
        self.with_generate()

        self.jobs.request_preview("lora:tenor")
        self.drain()

        self.assertEqual(before, self.read_json_bytes("voice_config.json"))

    def test_no_temp_files_are_left_behind_by_a_failed_render(self):
        self.with_generate("boom")
        self.jobs.request_preview("lora:tenor")
        self.drain()
        leftovers = [name for name in os.listdir(os.path.join(self.tmp, "lora_models", "tenor"))
                     if name.startswith(".")]
        self.assertEqual([], leftovers)

    def read_json_bytes(self, name):
        with open(os.path.join(self.tmp, name), "rb") as handle:
            return handle.read()


if __name__ == "__main__":
    unittest.main()