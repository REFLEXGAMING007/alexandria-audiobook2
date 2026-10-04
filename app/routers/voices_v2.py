"""Voices V2 — a standalone voice-management feature domain beside Voices.

Phase 0 registers the boundary only: one read-only projection endpoint with a
stable response envelope, so the Voices V2 frontend can be built and tested
against a real contract before any projection logic exists.

Boundaries this module keeps from the start:

- It reads nothing and writes nothing. Phase 0 has no persistence and invents
  no data shape; `characters` and `orphans` are empty by construction.
- It registers only `/api/voices-v2/*` paths. No existing Voices route is
  added to, removed from, or shadowed, so `routers/voices.py`, the guarded
  save contract in `voice_config_store.py`, and the character roster stay
  exactly as they were.
- Later phases compose the existing helpers in `core`, `tts`, `speaker_traits`,
  `voice_manifest`, `book_state_transaction` and `voice_config_store` instead
  of reimplementing them. `docs/ARCHITECTURE_PATTERNS.md` requires a new
  resolver to be used rather than re-created, and CLAUDE.md Rule 15 forbids
  parallel copies of a dispatch path.

The frontend boundary is `app/static/js/voices-v2/api.js`; its `PATHS` table
is the single place a Voices V2 URL is written down, and
`app/tests/test_voices_v2_isolation.py` enforces that.
"""
from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field


router = APIRouter()


class VoicesV2CharactersResponse(BaseModel):
    """The Phase 0 envelope.

    Phase 1 fills both lists from the book projection (script roster joined to
    `voice_config.json`, plus `voice_config` keys that have no script line).
    The names and shapes are declared here now so the OpenAPI contract and the
    frontend binding are locked before any of that logic exists. Each row is
    intentionally untyped in Phase 0: a row schema would be a guess about data
    that does not exist yet, and a wrong guess in a published contract is
    harder to change than a missing one.
    """

    characters: List[Dict[str, Any]] = Field(default_factory=list)
    orphans: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/api/voices-v2/characters", response_model=VoicesV2CharactersResponse)
async def list_characters():
    """Return the Voices V2 character projection for the active book.

    Phase 0: an empty, valid projection. Character browsing, filtering,
    sorting and voice assignment are Phase 1+ and are deliberately absent.
    """
    return VoicesV2CharactersResponse()