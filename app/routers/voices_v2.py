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

from fastapi import APIRouter
from pydantic import BaseModel, Field

from voices_v2 import SCHEMA_VERSION
from voices_v2.character_projection import build_character_projection


router = APIRouter()


class VoicesV2VoiceSummary(BaseModel):
    """What the browser needs to name a voice, and nothing it could write back."""

    category: str
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


class VoicesV2CharactersResponse(BaseModel):
    """The Phase 1 character projection for the active book."""

    schema_version: int = SCHEMA_VERSION
    book: VoicesV2Book = Field(default_factory=VoicesV2Book)
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