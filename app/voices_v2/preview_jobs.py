"""Voices V2 — generated voice preview jobs.

The application already knows how to render one preview for an adapter:
`routers.lora.ensure_lora_preview_audio` does the whole thing - it resolves the
adapter to a backend-owned directory, returns a cached `preview_sample.wav`
without touching the GPU, otherwise claims the GPU under the `lora_test` slot,
synthesises through the shared engine, validates the decoded audio, and publishes
it atomically with the existing retention policy. **This module does not
reimplement any of that.** It wraps it.

What this module adds is the part the synchronous endpoint cannot provide: a job
the browser can watch.

Why a job at all
----------------

`/api/lora/preview` blocks until generation finishes, which can take a model
load plus a render. A browser cannot usefully hold a request open for that, and
three rapid clicks must not become three renders. So a V2 request validates,
deduplicates and enqueues, and returns a job id immediately.

Scheduling
----------

One worker thread drains one FIFO queue, so V2 never has two syntheses in flight.
`ensure_lora_preview_audio` claims the GPU itself under the existing
`lora_test` slot, so **V2 takes no GPU claim of its own** - a second claim would
either deadlock against the primitive or serialise audiobook generation behind
something that does not need the GPU. What V2 contributes is the queue in front
of it; the existing claim remains the single point of GPU exclusion, and
audiobook generation is unaffected.

A primitive that raises because the GPU is busy (HTTP 400 from
`check_global_gpu_lock`) becomes a retryable job failure, not a stuck job.

Identity and path safety
------------------------

A browser sends `voice_id`, never a path. It is resolved through the catalogue to
a record, and only the record's `native_id` is handed to the existing primitive,
which resolves it under the adapter-manifest lock. Job records are keyed by a
uuid and fingerprinted by a hash, so no user-supplied string ever becomes a
filesystem path - including names with spaces, punctuation, mixed case or
non-ASCII, which are common in this catalogue.

Persistence
-----------

`voices_v2_preview_jobs.json` in the data directory, written atomically under a
lock. It is a cache and a status board, not a source of truth: a corrupt entry
is dropped, a missing file is an empty store, and a completed job whose audio has
been deleted reports `stale` so the library offers to generate again rather than
showing a dead play button.
"""
import hashlib
import json
import logging
import os
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from audio_validation import GeneratedAudioError, validate_generated_audio
from core import DATA_DIR
from utils import atomic_json_write, file_lock, safe_load_json

from voices_v2.voice_assignment import build_voice_catalogue
from voices_v2.voice_record import PREVIEW_KIND_RECORDED


logger = logging.getLogger("AlexandriaUI")

JOB_STORE_NAME = "voices_v2_preview_jobs.json"
SCHEMA_VERSION = 1

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
STATUS_STALE = "stale"
TERMINAL_STATUSES = (STATUS_COMPLETED, STATUS_FAILED, STATUS_CANCELLED, STATUS_STALE)
ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_RUNNING)

#: One profile for now. The concept exists so a later phase can add short,
#: cinematic, narrator or character-specific profiles without reshaping the job.
PROFILE_STANDARD = "standard"
PREVIEW_PROFILES = {
    PROFILE_STANDARD: {
        # The sentence the application already uses for adapter previews. Reusing
        # it is what makes two previews comparable, and it is what the existing
        # cache was built from.
        "text": "The ancient library stood at the crossroads of two forgotten paths, "
                "its weathered stone walls covered in ivy that had been growing for centuries.",
        "instruct": "",
    },
}

#: Families whose preview is synthesised. A design voice already has a generated
#: recording from the Voice Designer and a clone has an uploaded recording, so
#: neither is regenerated: the existing recording is exposed instead.
GENERATED_KINDS = ("lora", "builtin_lora")

#: How many job records to keep. Metadata only - the audio is the application's
#: own cache and its retention is `apply_lora_test_retention`.
MAX_RETAINED_JOBS = 50

_STORE_LOCK = threading.RLock()
_WORK_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKER: Optional[threading.Thread] = None
_RECOVERY_DONE = False


class PreviewError(Exception):
    """A refused or failed preview, carrying a stable code and a safe message.

    The technical cause is logged, never returned: a browser must not receive a
    traceback or a filesystem path.
    """

    def __init__(self, code: str, message: str, status: int = 400, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


def job_store_path() -> str:
    return os.path.join(DATA_DIR, JOB_STORE_NAME)


# ── Store ────────────────────────────────────────────────────────────────────

def _empty_store() -> Dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "jobs": {}}


def _read_store() -> Dict[str, Any]:
    """The job store, tolerant of anything.

    A preview cache losing its bookkeeping is an inconvenience, never a failure of
    the library: an unreadable, malformed or wrong-shaped store becomes an empty
    one. Individual broken job records are dropped rather than failing the read,
    so one bad entry cannot take the whole board with it.
    """
    raw = safe_load_json(job_store_path(), default=None)
    if not isinstance(raw, dict):
        return _empty_store()
    jobs = raw.get("jobs")
    if not isinstance(jobs, dict):
        return _empty_store()
    clean: Dict[str, Any] = {}
    for job_id, job in jobs.items():
        if not isinstance(job_id, str) or not job_id:
            continue
        if not isinstance(job, dict):
            continue
        status = job.get("status")
        if status not in (STATUS_QUEUED, STATUS_RUNNING, STATUS_COMPLETED,
                          STATUS_FAILED, STATUS_CANCELLED, STATUS_STALE):
            continue
        if not isinstance(job.get("voice_id"), str) or not job["voice_id"]:
            continue
        clean[job_id] = job
    return {"schema_version": SCHEMA_VERSION, "jobs": clean}


def _write_store(store: Dict[str, Any]) -> None:
    path = job_store_path()
    try:
        with file_lock(path):
            atomic_json_write(store, path)
    except TimeoutError:
        # Losing a status update is recoverable; the next request re-reads the
        # file and the worst case is one extra render that the cache absorbs.
        logger.warning("Voices V2 preview job store is busy; skipping this write")


def _prune(jobs: Dict[str, Any]) -> Dict[str, Any]:
    """Keep the newest records; never delete audio.

    Completed jobs are worth keeping because they are how a cached preview is
    recognised without re-reading the manifest. Nothing here removes a file.
    """
    if len(jobs) <= MAX_RETAINED_JOBS:
        return jobs
    ordered = sorted(jobs.values(), key=lambda job: job.get("created_at") or 0,
                     reverse=True)
    return {job["job_id"]: job for job in ordered[:MAX_RETAINED_JOBS] if job.get("job_id")}


def _update(job_id: str, **changes) -> Optional[Dict[str, Any]]:
    """Apply changes to one job under the store lock and persist."""
    with _STORE_LOCK:
        store = _read_store()
        job = store["jobs"].get(job_id)
        if job is None:
            return None
        job.update(changes)
        store["jobs"][job_id] = job
        _write_store({"schema_version": SCHEMA_VERSION,
                      "jobs": _prune(store["jobs"])})
        return dict(job)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    if not isinstance(job_id, str) or not job_id:
        return None
    with _STORE_LOCK:
        job = _read_store()["jobs"].get(job_id)
        return dict(job) if job else None


def latest_job_for_voice(voice_id: str) -> Optional[Dict[str, Any]]:
    """The most recent job for a voice, whoever it is for.

    Drives the card's preview state, so a job started before a reload is still
    visible afterwards.
    """
    with _STORE_LOCK:
        candidates = [job for job in _read_store()["jobs"].values()
                      if job.get("voice_id") == voice_id]
    if not candidates:
        return None
    return dict(max(candidates, key=lambda job: job.get("created_at") or 0))


def list_jobs_for_voice(voice_id: str) -> List[Dict[str, Any]]:
    with _STORE_LOCK:
        jobs = [dict(job) for job in _read_store()["jobs"].values()
                if job.get("voice_id") == voice_id]
    return sorted(jobs, key=lambda job: job.get("created_at") or 0, reverse=True)


# ── Fingerprint and identity ─────────────────────────────────────────────────

def _profile_or_refuse(profile: str) -> Dict[str, Any]:
    chosen = profile or PROFILE_STANDARD
    settings = PREVIEW_PROFILES.get(chosen)
    if settings is None:
        raise PreviewError("unknown_profile",
                           f"'{chosen}' is not a preview profile.", status=400)
    return settings


def fingerprint(voice_id: str, profile: str, text: str) -> str:
    """A stable digest of everything that materially changes the render.

    The underlying adapter cache is keyed by adapter alone, because today the
    profile and text are fixed. Hashing them anyway means a future profile can be
    told apart from the cached render that predates it, instead of silently
    reusing audio made with different words.
    """
    digest = hashlib.sha256()
    digest.update(voice_id.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(profile.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def resolve_generatable_voice(voice_id: str) -> Dict[str, Any]:
    """The catalogue record a preview may be generated for.

    Identity is resolved through the catalogue, so the browser's string is never
    turned into a path here; the primitive receives only the record's own
    `native_id`.
    """
    if not isinstance(voice_id, str) or not voice_id.strip():
        raise PreviewError("unknown_voice", "No voice was named.", status=400)
    for row in build_voice_catalogue()["voices"]:
        if row["voice_id"] == voice_id:
            if row["kind"] not in GENERATED_KINDS:
                raise PreviewError(
                    "preview_not_generated",
                    f"A {row['source']} already has its own preview recording, so "
                    f"nothing is generated for it.", status=409)
            if not row["available"]:
                raise PreviewError(
                    "voice_unavailable",
                    f"{row['name']} cannot be previewed: "
                    f"{row['unavailable_reason'] or 'its files are not on disk.'}",
                    status=409, retryable=True)
            return row
    raise PreviewError("unknown_voice", "No voice is registered as that.", status=404)


# ── Request ──────────────────────────────────────────────────────────────────

def request_preview(voice_id: str, profile: str = PROFILE_STANDARD) -> Dict[str, Any]:
    """Validate, deduplicate and enqueue. Returns immediately.

    Three rapid clicks produce one job: an identical queued or running job is
    returned, and a completed job whose audio is still on disk is returned as a
    cache hit rather than rendered again.
    """
    record = resolve_generatable_voice(voice_id)
    settings = _profile_or_refuse(profile)
    digest = fingerprint(record["voice_id"], profile, settings["text"])

    with _STORE_LOCK:
        store = _read_store()
        for job in store["jobs"].values():
            if job.get("fingerprint") != digest:
                continue
            status = job.get("status")
            if status in ACTIVE_STATUSES:
                logger.info("Voices V2 preview %s reuses in-flight job %s",
                            voice_id, job.get("job_id"))
                return {**public_job(job), "deduplicated": True}
            if status == STATUS_COMPLETED and job.get("audio_url"):
                logger.info("Voices V2 preview %s reuses cached job %s",
                            voice_id, job.get("job_id"))
                return {**public_job(job), "deduplicated": True}

        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "voice_id": record["voice_id"],
            "kind": record["kind"],
            "native_id": record["native_id"],
            "name": record["name"],
            "profile": profile,
            "fingerprint": digest,
            "status": STATUS_QUEUED,
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "audio_url": None,
            "error": None,
            "error_code": None,
            "cached": False,
        }
        store["jobs"][job_id] = job
        _write_store({"schema_version": SCHEMA_VERSION, "jobs": _prune(store["jobs"])})

    logger.info("Voices V2 preview queued: job=%s voice=%s profile=%s",
                job_id, record["voice_id"], profile)
    _ensure_worker()
    _WORK_QUEUE.put(job_id)
    return {**public_job(job), "deduplicated": False}


def cancel_job(job_id: str) -> Dict[str, Any]:
    """Cancel a queued job.

    A running synthesis is not cancellable: the primitive owns the GPU claim and
    the engine call, and killing it would release a claim its worker still holds
    and could corrupt an unrelated render. The caller is told so.
    """
    job = get_job(job_id)
    if job is None:
        raise PreviewError("unknown_job", "No preview job with that id.", status=404)
    status = job["status"]
    if status == STATUS_RUNNING:
        raise PreviewError(
            "job_running",
            "That preview is already rendering and will finish on its own.",
            status=409, retryable=True)
    if status in TERMINAL_STATUSES:
        return public_job(job)
    updated = _update(job_id, status=STATUS_CANCELLED, completed_at=time.time())
    logger.info("Voices V2 preview cancelled: job=%s voice=%s",
                job_id, job.get("voice_id"))
    return public_job(updated or job)


# ── Worker ───────────────────────────────────────────────────────────────────

def _ensure_worker() -> None:
    global _WORKER
    with _STORE_LOCK:
        if _WORKER is not None and _WORKER.is_alive():
            return
        _WORKER = threading.Thread(target=_drain, name="voices-v2-preview",
                                   daemon=True)
        _WORKER.start()


def _drain() -> None:
    """Render one job at a time, forever.

    Serial by construction: the primitive claims the GPU itself, so two V2
    renders at once would contend for the same slot and one would fail. Draining
    one at a time is what keeps a queue of previews from turning into a queue of
    conflicts.
    """
    while True:
        job_id = _WORK_QUEUE.get()
        try:
            _run_job(job_id)
        except Exception:  # noqa: BLE001 - a worker must never die
            logger.exception("Voices V2 preview worker failed on job %s", job_id)
        finally:
            _WORK_QUEUE.task_done()


def _run_job(job_id: str) -> None:
    job = get_job(job_id)
    if job is None or job["status"] != STATUS_QUEUED:
        return
    _update(job_id, status=STATUS_RUNNING, started_at=time.time())
    logger.info("Voices V2 preview running: job=%s voice=%s profile=%s",
                job_id, job["voice_id"], job["profile"])

    from routers.lora import ensure_lora_preview_audio

    try:
        result = ensure_lora_preview_audio(job["native_id"])
    except GeneratedAudioError as error:
        logger.warning("Voices V2 preview produced unusable audio: job=%s %s",
                       job_id, error)
        _update(job_id, status=STATUS_FAILED, completed_at=time.time(),
                error="The generated audio was not usable. Try again.",
                error_code="invalid_audio")
        return
    except HTTPException as error:
        code, message, retryable = _classify_http(error)
        logger.warning("Voices V2 preview refused: job=%s code=%s detail=%s",
                       job_id, code, error.detail)
        _update(job_id, status=STATUS_FAILED, completed_at=time.time(),
                error=message, error_code=code)
        # `retryable` is recorded implicitly by the code; kept here for the log.
        logger.info("Voices V2 preview failure retryable=%s job=%s", retryable, job_id)
        return
    except Exception as error:  # noqa: BLE001 - never leak the cause to the client
        logger.exception("Voices V2 preview failed: job=%s", job_id)
        _update(job_id, status=STATUS_FAILED, completed_at=time.time(),
                error="Preview generation failed. See the server log for details.",
                error_code="generation_failed")
        return

    audio_url = (result or {}).get("audio_url")
    if not audio_url:
        _update(job_id, status=STATUS_FAILED, completed_at=time.time(),
                error="Preview generation produced no audio.",
                error_code="generation_failed")
        return
    _update(job_id, status=STATUS_COMPLETED, completed_at=time.time(),
            audio_url=audio_url,
            cached=bool((result or {}).get("status") == "cached"))
    logger.info("Voices V2 preview completed: job=%s voice=%s url=%s",
                job_id, job["voice_id"], audio_url)


def _classify_http(error: HTTPException):
    """Map the primitive's HTTP errors onto codes a user can act on."""
    detail = str(error.detail or "")
    lowered = detail.lower()
    if "already running" in lowered or "currently running" in lowered:
        return ("busy",
                "Audiobook generation or another preview is using the GPU. "
                "Try again in a moment.", True)
    if "adapter files not found" in lowered or "not found" in lowered:
        return ("voice_unavailable",
                "Those voice files are no longer on disk.", True)
    if "auto-download failed" in lowered:
        return ("download_failed",
                "The built-in voice could not be downloaded.", True)
    return ("generation_failed",
            "Preview generation failed. See the server log for details.", False)


# ── Recovery ─────────────────────────────────────────────────────────────────

def recover_jobs() -> int:
    """Reconcile persisted jobs with reality. Called once per process.

    A queued or running job cannot outlive its process, and the render it was
    describing is not resumable - the engine is gone. Those become `stale`, which
    the card presents as an offer to generate again. A completed job whose audio
    has since been deleted is treated the same way, so a cached "completed" never
    produces a play button with nothing behind it.
    """
    global _RECOVERY_DONE
    with _STORE_LOCK:
        if _RECOVERY_DONE:
            return 0
        _RECOVERY_DONE = True

    store = _read_store()
    changed = 0
    for job_id, job in list(store["jobs"].items()):
        status = job.get("status")
        if status in ACTIVE_STATUSES:
            _update(job_id, status=STATUS_STALE)
            changed += 1
            logger.info("Voices V2 preview marked stale after restart: job=%s", job_id)
        elif status == STATUS_COMPLETED and not _audio_present(job):
            _update(job_id, status=STATUS_STALE, audio_url=None,
                    error="The preview file was removed.",
                    error_code="file_missing")
            changed += 1
            logger.info("Voices V2 preview marked stale, file missing: job=%s", job_id)
    if changed:
        logger.info("Voices V2 preview recovery reconciled %d job(s)", changed)
    return changed


#: The static mounts a preview can live under, and the directory each resolves to
#: relative to the data directory. `builtin_lora` is the one the application
#: resolves against the repository root rather than the data directory.
PREVIEW_NAMESPACES = {
    "/lora_models/": "lora_models",
    "/clone_voices/": "clone_voices",
    "/designed_voices/": "designed_voices",
    "/builtin_lora/": "builtin_lora",
}


def _audio_present(job: Dict[str, Any]) -> bool:
    """Whether a completed job's audio is still on disk.

    The URL is a static path, so it is resolved back to a file - never a request,
    and never a path taken from the job's own text. The resolved file must land
    inside the namespace directory it claims to be in, so a job record that
    somehow carried a traversing path could not make this return True for a file
    elsewhere.
    """
    url = job.get("audio_url")
    if not isinstance(url, str) or not url:
        return False
    for prefix, directory in PREVIEW_NAMESPACES.items():
        if not url.startswith(prefix):
            continue
        relative = url[len(prefix):]
        if not relative or relative.startswith("/") or "\\" in relative:
            return False
        root = os.path.realpath(os.path.join(DATA_DIR, directory))
        candidate = os.path.realpath(os.path.join(root, relative))
        if os.path.commonpath([root, candidate]) != root:
            return False
        return os.path.isfile(candidate)
    return False


# ── Public shape ─────────────────────────────────────────────────────────────

#: Coarse and honest. A one-line render has no internal progress to report, so
#: the value reflects the phase rather than a percentage that would be a fiction.
PROGRESS_BY_STATUS = {
    STATUS_QUEUED: 0.0,
    STATUS_RUNNING: 0.5,
    STATUS_COMPLETED: 1.0,
    STATUS_FAILED: 1.0,
    STATUS_CANCELLED: 1.0,
    STATUS_STALE: 1.0,
}

#: Only what a browser may see. No native id, no path, no fingerprint internals.
PUBLIC_FIELDS = ("job_id", "voice_id", "name", "kind", "profile", "status",
                 "created_at", "started_at", "completed_at", "audio_url",
                 "error", "error_code", "cached")


def public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    out = {key: job.get(key) for key in PUBLIC_FIELDS}
    out["progress"] = PROGRESS_BY_STATUS.get(job.get("status"), 0.0)
    out["terminal"] = job.get("status") in TERMINAL_STATUSES
    out["preview_url"] = job.get("audio_url")
    # Coerced rather than passed through: a job record written by an older
    # version, or hand-edited, may not have the field at all, and a null where
    # the response promises a boolean is a failed request rather than a detail.
    out["cached"] = bool(job.get("cached"))
    return out


def describe_preview(record: Dict[str, Any], job: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The preview state of one catalogue record, for the library.

    `availability` is left alone: whether a voice can be *used* and whether it can
    be *auditioned* are different questions, and a voice whose files are present
    but whose preview has not been generated is perfectly assignable.
    """
    kind = record.get("kind")
    generatable = kind in GENERATED_KINDS
    state = "none"
    job_id = None
    if generatable:
        if job and job.get("status") in ACTIVE_STATUSES:
            state = "generating"
            job_id = job.get("job_id")
        elif job and job.get("status") == STATUS_FAILED:
            state = "failed"
            job_id = job.get("job_id")
        elif record.get("preview_capable"):
            state = "generated"
        elif job and job.get("status") in (STATUS_STALE, STATUS_CANCELLED):
            state = "none"
    elif record.get("preview_capable"):
        # A family V2 does not generate still has a preview of its own, and the
        # card should say what kind: a Voice Designer's preview was synthesised,
        # a clone's was recorded by whoever uploaded it.
        state = record.get("preview_kind") or PREVIEW_KIND_RECORDED
    return {
        "preview_state": state,
        "preview_generatable": generatable,
        "preview_job_id": job_id,
    }


def validate_cached_audio(path: str) -> bool:
    """Re-validate a cached preview before the library trusts it."""
    try:
        validate_generated_audio(path, "cached Voices V2 preview")
        return True
    except GeneratedAudioError:
        return False
