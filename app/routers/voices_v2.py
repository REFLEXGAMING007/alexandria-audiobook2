"""Voices V2 — a standalone voice-management feature domain beside Voices.

This router is the backend boundary for the Voices V2 workspace. Phase 1 serves
the read-only character projection that the Voices V2 browser consumes.

Boundaries this module keeps:

- It reads nothing and writes nothing. `build_character_projection()` performs no
  file writes, repairs, migrations or renames, and this module adds none.
- It registers only `/api/voices-v2/*` paths. No existing Voices route is added
  to, removed from, or shadowed, so `routers/voices.py`, the guarded save
  contract in `voice_config_store.py`, and the character roster stay as they
  were.
- It composes the existing helpers rather than reimplementing them; the list is
  documented in `app/voices_v2/__init__.py`. `docs/ARCHITECTURE_PATTERNS.md`
  requires a new resolver to be used rather than re-created, and CLAUDE.md Rule
  15 forbids parallel copies of a dispatch path.

A book with no script yet is NOT an error here. The Voices tab answers 422 in
that case; Voices V2 answers 200 with empty lists and `book.script_present:
false`, because a first-run user opening the browser should read "no active
script yet", not a failure banner. The frontend distinguishes the two.

Later phases add sibling routes or grow this one behind the same prefix. The
frontend boundary is `app/static/js/voices-v2/api.js`, whose `PATHS` table is the
single place a Voices V2 URL is written down and
`app/tests/test_voices_v2_isolation.py` enforces that.
"""
import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from voice_config_store import VoiceConfigConflict
from voices_v2 import SCHEMA_VERSION
from voices_v2.character_projection import build_character_projection
from voices_v2.preview_jobs import (GENERATED_KINDS, PREVIEW_PROFILES, PROFILE_STANDARD,
                                    PreviewError, cancel_job, describe_preview, get_job,
                                    latest_job_for_voice, public_job, recover_jobs,
                                    request_preview)
from voices_v2.voice_assignment import (VoiceCommandError, build_voice_catalogue,
                                        execute_voice_command, plan_voice_command,
                                        set_voice_favorite)


router = APIRouter()


class VoicesV2VoiceSummary(BaseModel):
    """What the browser needs to name a voice, and nothing it could write back."""

    category: str
    # The stored type verbatim: `category` collapses lora and builtin_lora for
    # synthesis, but they are different catalogue entries and the editor has to
    # tell them apart.
    type: Optional[str] = None
    # Which catalogue row this configuration names, when one does. Null is a real
    # answer, not a gap.
    catalogue_voice_id: Optional[str] = None
    label: str
    assigned: bool
    adapter_id: Optional[str] = None
    adapter_available: Optional[bool] = None
    has_ref_audio: bool
    ref_audio_present: Optional[bool] = None
    has_description: bool
    seed: Optional[Any] = None
    alias_of: Optional[str] = None
    ensemble_members: int = 0


class VoicesV2Version(BaseModel):
    """A voice version, projected. A stored version is a whole configuration,
    so the browser gets its category and label instead of the raw overlay."""

    version_id: str
    age_group: Optional[str] = None
    category: str
    label: str
    adapter_id: Optional[str] = None


class VoicesV2VersionPoint(BaseModel):
    from_index: Optional[Any] = None
    version_id: Optional[str] = None


class VoicesV2State(BaseModel):
    gender: str
    age_group: str


class VoicesV2Traits(BaseModel):
    """`speaker_traits.get_speaker_trait_summary` verbatim: the one definition of
    a character's settled gender/age, including its state list."""

    gender: str
    age_group: str
    ageless: bool
    lines: int
    current: Dict[str, str]
    states: List[Dict[str, str]] = Field(default_factory=list)


class VoicesV2Character(BaseModel):
    """One character. `key` is the stable selection identifier: derived from the
    stored name, never from a position in any list."""

    key: str
    name: str
    identity_key: str
    library_key: Optional[str] = None
    present_in_script: bool
    generic: bool = False
    line_count: int = 0
    priority: Optional[str] = None
    known_as: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    voice: VoicesV2VoiceSummary
    voice_status: Optional[str] = None
    persona_status: Optional[str] = None
    ready: bool = False
    persona_ref: Optional[str] = None
    persona_ref_resolves: Optional[bool] = None
    active_version: Optional[str] = None
    versions: List[VoicesV2Version] = Field(default_factory=list)
    version_timeline: List[VoicesV2VersionPoint] = Field(default_factory=list)
    candidate_count: int = 0
    traits: Optional[VoicesV2Traits] = None
    traits_available: bool = False
    states: List[Dict[str, Any]] = Field(default_factory=list)
    possible_duplicate_of: List[str] = Field(default_factory=list)
    problems: List[str] = Field(default_factory=list)


class VoicesV2Book(BaseModel):
    book_id: Optional[str] = None
    token: Optional[str] = None
    script_sha256: Optional[str] = None
    script_present: bool = False


class VoicesV2AgeGroup(BaseModel):
    value: str
    label: str


class VoicesV2Vocabularies(BaseModel):
    """Enumerations come from `speaker_traits`, so the filter lists cannot drift
    away from the values the backend actually produces."""

    genders: List[str] = Field(default_factory=list)
    age_groups: List[VoicesV2AgeGroup] = Field(default_factory=list)
    problem_codes: List[str] = Field(default_factory=list)


class VoicesV2Counts(BaseModel):
    characters: int = 0
    orphans: int = 0


class VoicesV2VoiceOption(BaseModel):
    """One voice in the unified catalogue.

    A shape over the manifests the application already owns, not a catalogue of
    its own: the adapter rows come from the same files `/api/lora/models` reads
    and the clone and design rows from the same files `/api/clone_voices/list`
    and `/api/voice_design/list` read.

    `gender` / `age_group` carry the best value available and
    `gender_source` / `age_group_source` say whether it was `declared`,
    `inferred` or `unknown`. Keeping the provenance next to the value is what
    lets a later automatic-metadata phase fill in the gaps and a manual
    correction phase override them, without either having to guess what the other
    would have meant.
    """

    voice_id: str
    native_id: str
    kind: str
    name: str
    label: str
    source: str
    realisation: str
    description: Optional[str] = None
    sample_text: Optional[str] = None
    gender: str = "unknown"
    gender_source: str = "unknown"
    age_group: str = "unknown"
    age_group_source: str = "unknown"
    availability: str = "unavailable"
    available: bool = False
    unavailable_reason: str = ""
    downloaded: bool = True
    favorite: bool = False
    favorite_supported: bool = False
    adapter_id: Optional[str] = None
    adapter_path: Optional[str] = None
    ref_audio: Optional[str] = None
    ref_text: Optional[str] = None
    preview_capable: bool = False
    preview_url: Optional[str] = None
    preview_kind: Optional[str] = None
    # Generated-preview state, distinct from `availability`: a voice can be
    # perfectly assignable and still have no preview rendered yet.
    preview_state: str = "none"
    preview_generatable: bool = False
    preview_job_id: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoicesV2FavoriteRequest(BaseModel):
    """Explicit set/clear rather than a toggle, so a repeated request cannot
    silently undo itself and the caller always knows the state it asked for."""

    voice_id: str = Field(min_length=1)
    favorite: bool


class VoicesV2FavoriteResponse(BaseModel):
    voice_id: str
    favorite: bool
    favorites: List[str] = Field(default_factory=list)


class VoicesV2VoiceCounts(BaseModel):
    total: int = 0
    available: int = 0
    unavailable: int = 0


class VoicesV2VoiceCatalogue(BaseModel):
    """The whole library in one document.

    One request, no paging and no per-voice calls: the catalogue is small enough
    that the browser filters and sorts it locally, which is what keeps typing
    responsive. If it ever grows past that, this endpoint is the only thing that
    has to gain a paging contract - the client-side selectors already operate on
    a normalised array and would not change.
    """

    schema_version: int = SCHEMA_VERSION
    voices: List[VoicesV2VoiceOption] = Field(default_factory=list)
    counts: VoicesV2VoiceCounts = Field(default_factory=VoicesV2VoiceCounts)
    kinds: List[str] = Field(default_factory=list)
    favorite_kinds: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    unsupported_kinds: Dict[str, str] = Field(default_factory=dict)
    # Preview generation vocabulary, so the browser never hard-codes a profile or
    # a family that can be generated.
    preview_profiles: List[str] = Field(default_factory=list)
    generated_kinds: List[str] = Field(default_factory=list)


class VoicesV2PreviewRequest(BaseModel):
    """A request to render one preview.

    Deliberately small: a voice and a profile. No TTS configuration, no output
    path, no text - the browser states an intention and the backend resolves
    everything else from the catalogue.
    """

    voice_id: str = Field(min_length=1)
    profile: str = PROFILE_STANDARD


class VoicesV2PreviewJob(BaseModel):
    """A preview job, as the browser may see it.

    No native id, no filesystem path, no fingerprint internals: a client cannot
    learn anything here that it did not already get from the catalogue.
    """

    job_id: str
    voice_id: str
    name: Optional[str] = None
    kind: Optional[str] = None
    profile: Optional[str] = None
    status: str
    progress: float = 0.0
    terminal: bool = False
    deduplicated: bool = False
    created_at: Optional[float] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    preview_url: Optional[str] = None
    audio_url: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    cached: bool = False


class VoicesV2CommandRequest(BaseModel):
    """A single-character write, described as an intention rather than a file.

    The client names a character and a catalogue voice and nothing else. It
    cannot describe a configuration: the stored entry is read, merged and
    revalidated on the server, so a client can neither drop a field it does not
    understand nor write a path the engine could not resolve.
    """

    command: str
    character: str
    voice_id: Optional[str] = None
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    book_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class VoicesV2CommandResponse(BaseModel):
    status: str
    character: str
    voice_id: Optional[str] = None
    revision: Optional[str] = None
    book_token: Optional[str] = None


class VoicesV2ErrorResponse(BaseModel):
    """A refusal carries a stable code so the UI can branch without parsing prose."""

    code: str
    message: str


class VoicesV2CharactersResponse(BaseModel):
    """The Phase 1 character projection for the active book."""

    schema_version: int = SCHEMA_VERSION
    book: VoicesV2Book = Field(default_factory=VoicesV2Book)
    # The voice-config revision the guarded save contract requires. Held from the
    # moment the browser reads, because a save that cannot prove which snapshot
    # it was based on can silently overwrite someone else's work.
    revision: Optional[str] = None
    # Book-level, so the UI can say "this book has no per-line traits" instead of
    # presenting an empty gender filter that silently matches nobody.
    traits_available: bool = False
    traits_requested: Optional[bool] = None
    aliases_registered: bool = False
    major_line_threshold: int
    vocabularies: VoicesV2Vocabularies = Field(default_factory=VoicesV2Vocabularies)
    characters: List[VoicesV2Character] = Field(default_factory=list)
    orphans: List[VoicesV2Character] = Field(default_factory=list)
    counts: VoicesV2Counts = Field(default_factory=VoicesV2Counts)


@router.get("/api/voices-v2/characters", response_model=VoicesV2CharactersResponse)
async def list_characters():
    """Return the Voices V2 character projection for the active book.

    Read-only. Characters come from the active script; `orphans` are voice
    configuration entries with no script line, which the Voices tab cannot show
    because its roster is script-derived. Voice assignment, bulk actions and the
    Voice Library are later phases and are deliberately absent.
    """
    return await asyncio.to_thread(build_character_projection)


@router.get("/api/voices-v2/voices", response_model=VoicesV2VoiceCatalogue)
async def list_assignable_voices():
    """Every voice in the unified Voices V2 library, with its availability.

    A voice whose files are absent is still listed, with a reason, because a
    character may already point at it and the user needs to see that rather than
    be offered a selector that silently omits their current voice.
    """
    try:
        return await asyncio.to_thread(_catalogue_with_previews)
    except VoiceCommandError as error:
        raise HTTPException(status_code=error.status,
                            detail={"code": error.code, "message": error.message}) from error


def _catalogue_with_previews():
    """The catalogue plus generated-preview state.

    Enrichment lives here rather than inside `build_voice_catalogue` so the job
    store and the catalogue do not import each other. Preview state is joined per
    voice after the catalogue is built, which keeps one lock over the job store
    for the whole read instead of one per record.
    """
    recover_jobs()
    catalogue = build_voice_catalogue()
    for row in catalogue["voices"]:
        row.update(describe_preview(row, latest_job_for_voice(row["voice_id"])))
    catalogue["preview_profiles"] = sorted(PREVIEW_PROFILES)
    catalogue["generated_kinds"] = list(GENERATED_KINDS)
    return catalogue


@router.post("/api/voices-v2/previews", response_model=VoicesV2PreviewJob)
async def create_preview(request: VoicesV2PreviewRequest):
    """Queue one generated preview and return immediately.

    Three rapid clicks produce one render: an identical queued or running job is
    returned instead of a second, and a completed job whose audio is still on
    disk is returned as a cache hit. The request never blocks on synthesis.
    """
    try:
        return await asyncio.to_thread(request_preview, request.voice_id, request.profile)
    except PreviewError as error:
        raise HTTPException(status_code=error.status,
                            detail={"code": error.code, "message": error.message}) from error


@router.get("/api/voices-v2/previews/{job_id}", response_model=VoicesV2PreviewJob)
async def read_preview(job_id: str):
    """The status of one preview job."""
    recover_jobs()
    job = await asyncio.to_thread(get_job, job_id)
    if job is None:
        raise HTTPException(status_code=404,
                            detail={"code": "unknown_job",
                                    "message": "No preview job with that id."})
    return public_job(job)


@router.post("/api/voices-v2/previews/{job_id}/cancel", response_model=VoicesV2PreviewJob)
async def cancel_preview(job_id: str):
    """Cancel a queued preview.

    A running synthesis is not cancellable. The primitive owns the GPU claim and
    the engine call, and stopping it mid-render would release a claim its worker
    still holds; the caller is told so instead.
    """
    try:
        return await asyncio.to_thread(cancel_job, job_id)
    except PreviewError as error:
        raise HTTPException(status_code=error.status,
                            detail={"code": error.code, "message": error.message}) from error


@router.post("/api/voices-v2/favorite", response_model=VoicesV2FavoriteResponse)
async def set_favorite(request: VoicesV2FavoriteRequest):
    """Mark or unmark one voice as a favourite.

    Favourites belong to voices, not characters, and are stored where the
    application already keeps them - `voice_library.json` - through the same
    locked mutator the Voices tab's own favourite toggle uses. A voice starred in
    either place is starred in both.

    Not every family can be favourited: the store is a list of adapter ids, so a
    clone or a designed voice has nowhere to be recorded. Those are refused with a
    reason rather than accepted and silently forgotten.
    """
    try:
        return await asyncio.to_thread(set_voice_favorite, request.voice_id, request.favorite)
    except VoiceCommandError as error:
        raise HTTPException(status_code=error.status,
                            detail={"code": error.code, "message": error.message}) from error
    except TimeoutError as error:
        raise HTTPException(status_code=503,
                            detail={"code": "busy",
                                    "message": "The voice library is busy; try again."}) from error


@router.post("/api/voices-v2/command", response_model=VoicesV2CommandResponse)
async def run_voice_command(request: VoicesV2CommandRequest):
    """Assign or clear one character's voice, through the existing save path.

    The request carries an intention, not a configuration: the stored entry is
    read, only the voice-owning fields are replaced, the result is revalidated
    through `VoiceConfigItem`, and `_apply_voice_save` performs the write with
    the same lock, revision check and book-token check the Voices tab uses. A
    stale client is refused with 409 rather than allowed to overwrite.
    """
    try:
        return await asyncio.to_thread(
            _run_command, request.command, request.character, request.voice_id,
            request.revision, request.book_token)
    except VoiceCommandError as error:
        raise HTTPException(status_code=error.status,
                            detail={"code": error.code, "message": error.message}) from error
    except VoiceConfigConflict as error:
        raise HTTPException(status_code=409,
                            detail={"code": "stale_snapshot", "message": str(error)}) from error
    except TimeoutError as error:
        raise HTTPException(status_code=503,
                            detail={"code": "busy",
                                    "message": "Voice configuration is busy; try again."}) from error


def _run_command(command, character, voice_id, revision, book_token):
    """Plan then write, so a refusal never reaches the disk."""
    plan = plan_voice_command(command, character, voice_id)
    return execute_voice_command(plan, revision, book_token)