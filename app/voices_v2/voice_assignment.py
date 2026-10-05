"""Voices V2 — single-character voice assignment.

Phase 1 made Voices V2 able to *see* every character. This module lets it change
exactly one character's voice, safely, by delegating to the save path the Voices
tab already uses.

The save contract, and why this module exists
----------------------------------------------

`_apply_voice_save` merges each posted entry as::

    updated[name] = {**existing_metadata, **posted.model_dump()}

`posted` is a `VoiceConfigItem`, so `model_dump()` emits **all 25 declared
fields**, filling in defaults for anything the client omitted. Two consequences
decide the whole design:

1. Fields the model does not declare (`persona_ref`, `persona_voice_audit`,
   `gender`, `state_assignments`) survive, because they come back through
   `existing_metadata`.
2. Declared fields the client omits are **reset to their default** — posting
   just `{type, voice}` would silently wipe `versions`, `candidates`,
   `version_timeline`, `style_timeline`, `ref_audio`, `description` and the
   rest.

The Voices tab avoids (2) because `collectVoiceConfig()` scrapes the whole card
and posts a complete entry. Voices V2 must not do that: it deliberately does not
expose the raw configuration, so it cannot rebuild one. Therefore **the merge
happens here, on the server, where the stored entry is already in hand.** The
frontend sends a character key, a catalogue id, and the two concurrency fields;
this module reads the stored entry, changes only the voice-owned fields, and
hands a complete `VoiceConfigItem` to the existing save function.

The result is the correctness target for Phase 2: the same logical voice change
produces the same persisted entry as the equivalent Voices tab operation, and
every field neither change touches is left exactly as it was.

Character identity
------------------

A write must never be routed by display text. Voices V2 identifies a character by
the `key` its own projection produced, and this module re-derives the stored
`voice_config` speaker name from a freshly built projection rather than trusting
the request. Two spellings that differ only by spacing (`PROFESSOR FERNANDO` and
`PROFESSOR_FERNANDO`) are different stored keys and stay different; they are
reported as possible duplicates in the projection and neither is silently merged.

A write is refused outright when the key does not resolve to exactly one stored
entry, or when the character has vanished from both the script and the
configuration.
"""
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from core import _load_manifest, _load_voice_library, _require_safe_filename
from hf_utils import is_adapter_downloaded
from core import BUILTIN_LORA_DIR, CLONE_VOICES_DIR, DATA_DIR, DESIGNED_VOICES_DIR
from core import LORA_MODELS_DIR, LORA_MODELS_MANIFEST, VOICE_CONFIG_PATH
from utils import safe_load_json
from voice_manifest import get_adapter_manifest_rows, get_resolved_adapter_ids

from voices_v2.character_projection import build_character_projection


logger = logging.getLogger("AlexandriaUI")
from voices_v2.voice_identity import (ASSIGNABLE_KINDS, KIND_BUILTIN_LORA, KIND_CLONE,
                                   KIND_DESIGN, KIND_LORA, split_voice_id, voice_id)


# The voice kinds themselves live in `voices_v2.voice_identity`, which the
# projection also imports: both halves of the domain must agree on what a voice
# id means. `ensemble` is deliberately not assignable - it speaks for several
# characters at once, and Phase 2 is single-character by design - and neither is
# `custom`, which is only a working assignment once it carries a persona that
# Voices V2 does not create.
COMMAND_ASSIGN = "assign"
COMMAND_CLEAR = "clear"
COMMANDS = (COMMAND_ASSIGN, COMMAND_CLEAR)

BUILTIN_LORA_MANIFEST = os.path.join(BUILTIN_LORA_DIR, "manifest.json")
DESIGNED_VOICES_MANIFEST = os.path.join(DESIGNED_VOICES_DIR, "manifest.json")
CLONE_VOICES_MANIFEST = os.path.join(CLONE_VOICES_DIR, "manifest.json")

# `tts._resolve_asset_path` resolves `builtin_lora/...` against the repository
# root and everything else against the runtime data directory, and refuses
# absolute paths or `..`. These are therefore the only two forms a stored
# adapter_path may take.
BUILTIN_NAMESPACE = "builtin_lora"
USER_NAMESPACE = "lora_models"


class VoiceCommandError(Exception):
    """A refused command, carrying the status and a code the UI can branch on.

    A refusal is a normal outcome, not a crash: an unknown character, a stale
    snapshot or a voice whose files are gone are all things a user can see and
    act on. The `code` is stable so the frontend can choose wording without
    parsing English.
    """

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _text(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None



# ── Catalogue ────────────────────────────────────────────────────────────────
# Built from the sources the application already owns. Nothing here is a second
# source of truth: the adapter rows come from the same manifests
# `/api/lora/models` reads, the clone and design rows from the same files
# `/api/clone_voices/list` and `/api/voice_design/list` read. This is a shape
# adapter, not a catalogue.

def _adapter_available(adapter_id: str, is_builtin: bool) -> Tuple[bool, str]:
    """Whether an adapter bundle is actually on disk, and why not if it is not.

    A downloaded flag can disagree with the filesystem, and an assignment that
    cannot be synthesised is worse than one that was refused: the Voices tab
    happily writes an `adapter_path` that does not resolve.
    """
    namespace = BUILTIN_NAMESPACE if is_builtin else USER_NAMESPACE
    relative = f"{namespace}/{adapter_id}"
    # `_require_safe_filename` is the same guard the upload and delete paths
    # use; an id containing a separator must never reach a filesystem path.
    if adapter_id != _require_safe_filename(adapter_id, "Invalid adapter id"):
        return False, "This adapter id is not a valid name."
    if not os.path.isdir(os.path.join(DATA_DIR, relative)):
        return False, "The adapter files are not on disk."
    return True, ""


def _builtin_lora_rows() -> List[Dict[str, Any]]:
    """Built-in adapters, read from the manifest on disk.

    Deliberately not `_load_builtin_lora_manifest`, which fetches from Hugging
    Face with a local fallback. Voices V2 opens this catalogue every time the tab
    is opened, and an assignment can only ever use an adapter that is already
    installed - so a browser-facing read has no business making a network call,
    and the `downloaded` flag it reports comes from the same
    `is_adapter_downloaded` check either way.
    """
    rows: List[Dict[str, Any]] = []
    for entry in _load_manifest(BUILTIN_LORA_MANIFEST):
        if not isinstance(entry, dict):
            continue
        native = _text(entry.get("id"))
        if not native:
            continue
        adapter_id = native if native.startswith("builtin_") else f"builtin_{native}"
        downloaded = is_adapter_downloaded(adapter_id, BUILTIN_LORA_DIR)
        available, reason = _adapter_available(adapter_id, True)
        if not downloaded:
            available, reason = False, "This built-in voice has not been downloaded."
        rows.append({
            "voice_id": voice_id(KIND_BUILTIN_LORA, adapter_id),
            "kind": KIND_BUILTIN_LORA,
            "name": _text(entry.get("name")) or adapter_id,
            "description": _text(entry.get("description")),
            "gender": _text(entry.get("gender")),
            "favorite": False,
            "downloaded": downloaded,
            "adapter_id": adapter_id,
            "adapter_path": f"{BUILTIN_NAMESPACE}/{adapter_id}",
            "available": available,
            "unavailable_reason": reason,
            "ref_audio": None,
            "ref_text": None,
        })
    return rows


def _lora_rows() -> Tuple[List[Dict[str, Any]], List[str]]:
    """User-trained adapter rows, plus any warning the manifests produced.

    `get_adapter_manifest_rows` validates adapter ids and raises on a malformed
    one. Letting that escape would take down voice *assignment* for the clone and
    design voices too, because they share this one catalogue read - a single
    hand-edited manifest row would break a part of the feature it has nothing to
    do with. So the adapters are reported as unreadable and the other families
    still work.
    """
    warnings: List[str] = []
    unreadable = ("The LoRA voice list could not be read, so LoRA voices cannot be "
                  "assigned. Clone and designed voices are unaffected.")
    try:
        favorites = set(get_resolved_adapter_ids(
            LORA_MODELS_DIR, _load_voice_library().get("favorites") or []))
        entries = [entry for entry in get_adapter_manifest_rows(
            LORA_MODELS_DIR, LORA_MODELS_MANIFEST, _load_manifest)
            if isinstance(entry, dict) and _text(entry.get("id"))]
    except (ValueError, OSError) as error:
        logger.warning("Voices V2 could not read the adapter manifests: %s", error)
        return [], [unreadable]

    rows: List[Dict[str, Any]] = []
    for entry in entries:
        adapter_id = str(entry["id"])
        available, reason = _adapter_available(adapter_id, False)
        rows.append({
            "voice_id": voice_id(KIND_LORA, adapter_id),
            "kind": KIND_LORA,
            "name": _text(entry.get("name")) or adapter_id,
            "description": _text(entry.get("description")),
            "gender": _text(entry.get("gender")),
            "favorite": adapter_id in favorites,
            "downloaded": True,
            "adapter_id": adapter_id,
            "adapter_path": f"{USER_NAMESPACE}/{adapter_id}",
            "available": available,
            "unavailable_reason": reason,
            "ref_audio": None,
            "ref_text": None,
        })
    return rows, warnings


def _clone_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in _load_manifest(CLONE_VOICES_MANIFEST):
        if not isinstance(entry, dict):
            continue
        native_id = _text(entry.get("id"))
        filename = _text(entry.get("filename"))
        if not native_id or not filename:
            continue
        relative = f"clone_voices/{filename}"
        present = os.path.isfile(os.path.join(DATA_DIR, relative))
        rows.append({
            "voice_id": voice_id(KIND_CLONE, native_id),
            "kind": KIND_CLONE,
            "name": _text(entry.get("name")) or native_id,
            # An uploaded clip is required to carry its exact transcript, so a
            # row without one cannot be assigned and must not be offered as if
            # it could.
            "description": _text(entry.get("ref_text")),
            "gender": None,
            "favorite": False,
            "downloaded": True,
            "adapter_id": None,
            "adapter_path": None,
            "available": present and bool(_text(entry.get("ref_text"))),
            "unavailable_reason": "" if present and _text(entry.get("ref_text"))
                                   else ("The reference recording is missing." if not present
                                         else "The reference recording has no transcript."),
            "ref_audio": relative,
            "ref_text": _text(entry.get("ref_text")),
        })
    return rows


def _design_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in _load_manifest(DESIGNED_VOICES_MANIFEST):
        if not isinstance(entry, dict):
            continue
        native_id = _text(entry.get("id"))
        if not native_id:
            continue
        description = _text(entry.get("description"))
        filename = _text(entry.get("filename"))
        relative = f"designed_voices/{filename}" if filename else None
        rows.append({
            "voice_id": voice_id(KIND_DESIGN, native_id),
            "kind": KIND_DESIGN,
            "name": _text(entry.get("name")) or native_id,
            # The description IS the voice: VoiceDesign synthesises from prose,
            # which is why this is the whole payload.
            "description": description,
            "gender": None,
            "favorite": False,
            "downloaded": True,
            "adapter_id": None,
            "adapter_path": None,
            "available": bool(description),
            "unavailable_reason": "" if description else "This designed voice has no description.",
            "ref_audio": relative,
            "ref_text": _text(entry.get("sample_text")),
        })
    return rows


def build_voice_catalogue() -> Dict[str, Any]:
    """Every voice Voices V2 can offer, from the application's own sources."""
    lora_rows, warnings = _lora_rows()
    rows = lora_rows + _builtin_lora_rows() + _clone_rows() + _design_rows()
    seen: Dict[str, int] = {}
    for row in rows:
        seen[row["voice_id"]] = seen.get(row["voice_id"], 0) + 1
    duplicated = sorted(vid for vid, count in seen.items() if count > 1)
    if duplicated:
        # Two manifest rows claiming one id would make a selection ambiguous, so
        # they are refused rather than resolved by insertion order.
        raise VoiceCommandError("duplicate_voice_ids",
                                "The voice catalogue contains duplicate ids.", status=409)
    rows.sort(key=lambda row: (row["kind"] != KIND_LORA, row["kind"] != KIND_BUILTIN_LORA,
                               (row["name"] or "").lower()))
    return {
        "voices": rows,
        "counts": {
            "total": len(rows),
            "available": sum(1 for row in rows if row["available"]),
            "unavailable": sum(1 for row in rows if not row["available"]),
        },
        "kinds": list(ASSIGNABLE_KINDS),
        "warnings": warnings,
        "unsupported_kinds": {
            "ensemble": "An ensemble voice speaks for several characters at once, "
                        "so it cannot be assigned to a single character.",
            "custom": "A custom voice is only a working assignment once it carries a "
                      "persona, which Voices V2 does not create. Assign a LoRA, a clone "
                      "or a designed voice instead.",
        },
    }


def find_catalogue_voice(voice_id: str) -> Dict[str, Any]:
    """The catalogue row for an id, re-validated against the filesystem.

    The catalogue is rebuilt rather than trusted: between reading it and saving,
    an adapter can be deleted or a clone manifest rewritten, and a save that
    wrote a path which no longer resolves would be indistinguishable from a
    working assignment.
    """
    kind, native = split_voice_id(voice_id)
    if kind is None:
        # A malformed id is a different mistake from a well-formed id that names
        # nothing, and the UI says something different about each.
        raise VoiceCommandError("invalid_voice", "That voice id is not recognised.")
    for row in build_voice_catalogue()["voices"]:
        if row["voice_id"] == voice_id:
            if not row["available"]:
                raise VoiceCommandError("voice_unavailable",
                                        f"{row['name']} cannot be assigned: "
                                        f"{row['unavailable_reason'] or 'it is unavailable.'}",
                                        status=409)
            return row
    raise VoiceCommandError("unknown_voice", f"No voice is registered as '{native}'.", status=404)


# ── Character identity ───────────────────────────────────────────────────────

def resolve_writable_character(character_key: str) -> Tuple[str, Dict[str, Any]]:
    """Map a Voices V2 character key to the exact stored speaker name.

    The projection is rebuilt here and the name is taken from it, so the
    authoritative `voice_config` key always comes from the server's own
    resolution rather than from anything the request asserted.

    Returns `(speaker_name, record)`.
    """
    key = _text(character_key)
    if not key:
        raise VoiceCommandError("unknown_character", "No character was selected.")

    projection = build_character_projection()
    records = projection["characters"] + projection["orphans"]
    matches = [record for record in records if record.get("key") == key]

    if not matches:
        raise VoiceCommandError(
            "unknown_character",
            "That character is not in this book. Refresh the Voices V2 projection.",
            status=404)
    if len(matches) > 1:
        # Two records sharing one key means a selection cannot be resolved to a
        # single stored entry. Refusing is the only safe answer: writing either
        # would be a guess.
        raise VoiceCommandError(
            "ambiguous_character",
            "That selection matches more than one character, so nothing was changed. "
            "Refresh and pick a different character.",
            status=409)

    record = matches[0]
    name = record["name"]
    present = record["present_in_script"]
    if not present and not record["library_key"]:
        # An orphan still owns a stored entry, so it is writable; a character
        # that has left both the script and the library index cannot be.
        raise VoiceCommandError(
            "character_no_longer_present",
            f"'{name}' is no longer part of this book, so nothing was changed.",
            status=409)
    return name, record


# ── The write ────────────────────────────────────────────────────────────────

def _voice_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """The configuration fields that describe *which* voice a character speaks.

    Only these are replaced. `character_style`, `default_style`, `seed`,
    `ready`, `alias_of`, `versions`, `candidates`, `version_timeline`,
    `style_timeline`, `persona_status`, `voice_status`, `active_version` and
    every undeclared field are left exactly as stored: changing the voice is not
    a review decision, a style edit, or an approval.
    """
    kind = row["kind"]
    if kind in (KIND_LORA, KIND_BUILTIN_LORA):
        return {
            "type": kind,
            "voice": None,
            "adapter_id": row["adapter_id"],
            "adapter_path": row["adapter_path"],
            "ref_audio": None,
            "ref_text": None,
            "description": None,
            "members": None,
            "alias_of": None,
        }
    if kind == KIND_CLONE:
        return {
            "type": "clone",
            "voice": row["name"],
            "adapter_id": None,
            "adapter_path": None,
            "ref_audio": row["ref_audio"],
            "ref_text": row["ref_text"],
            "description": None,
            "members": None,
            "alias_of": None,
        }
    # design: VoiceDesign synthesises from prose, so the description is the voice.
    # `ref_audio` carries the designed voice's own preview path purely as an
    # identity anchor. tts.py ignores it for this family, and without it the
    # stored configuration could not be mapped back to a catalogue row - so after
    # assigning a designed voice the editor would no longer know what it had just
    # assigned. This is the same use the persona pipeline already makes of the
    # field.
    return {
        "type": "design",
        "voice": row["name"],
        "adapter_id": None,
        "adapter_path": None,
        "ref_audio": row["ref_audio"],
        "ref_text": None,
        "description": row["description"],
        "members": None,
        "alias_of": None,
    }


def _cleared_fields(existing: Dict[str, Any]) -> Dict[str, Any]:
    """The same field set as an assignment, with nothing assigned.

    `voice_is_set` reports a bare `custom` entry with no persona as "no voice",
    so clearing has to remove the persona hooks too, or a "cleared" character
    would still read as having a voice. Style, seed, review flags and history
    are untouched.
    """
    return {
        "type": "custom",
        "voice": None,
        "adapter_id": None,
        "adapter_path": None,
        "ref_audio": None,
        "ref_text": None,
        "description": None,
        "members": None,
        "alias_of": None,
    }


def merged_entry(speaker_name: str, stored: Dict[str, Any],
                 voice_fields: Dict[str, Any]) -> Dict[str, Any]:
    """The complete entry to post: everything stored, with the voice replaced.

    Two details are deliberate rather than incidental:

    `seed` is normalised to a string. `VoiceConfigItem.seed` is `Optional[str]`
    with a `"-1"` default, and real configurations hold integers — the Voices tab
    hits this too and sends `String(metadata.seed)`. Passing an integer straight
    through would make Pydantic reject the save and lock assignment for exactly
    the characters that already have a working voice, so V2 does the same
    normalisation and therefore reaches the same stored result.

    Fields absent from the stored entry stay absent, and `VoiceConfigItem`
    supplies its declared defaults for them exactly as it does for any caller.
    """
    merged = dict(stored)
    merged.update(voice_fields)
    merged["voice"] = merged.get("voice") or None
    seed = merged.get("seed")
    merged["seed"] = "-1" if seed is None else str(seed)
    return merged


def plan_voice_command(command: str, character_key: str, voice_id: Optional[str]):
    """Validate a command and produce everything the save needs, writing nothing.

    Separated from the save so every refusal can be exercised without touching
    disk, and so the merge that will be written is inspectable.
    """
    if command not in COMMANDS:
        raise VoiceCommandError("unknown_command", f"'{command}' is not a Voices V2 command.")

    speaker_name, record = resolve_writable_character(character_key)

    if command == COMMAND_CLEAR:
        stored = _stored_entry(speaker_name)
        if not stored:
            raise VoiceCommandError("nothing_to_clear",
                                    f"'{speaker_name}' has no voice configuration to clear.",
                                    status=409)
        return {
            "command": COMMAND_CLEAR,
            "speaker_name": speaker_name,
            "record": record,
            "entry": merged_entry(speaker_name, stored, _cleared_fields(stored)),
            "voice_id": None,
        }

    row = find_catalogue_voice(voice_id)
    stored = _stored_entry(speaker_name)
    return {
        "command": COMMAND_ASSIGN,
        "speaker_name": speaker_name,
        "record": record,
        "entry": merged_entry(speaker_name, stored, _voice_fields(row)),
        "voice_id": row["voice_id"],
    }


def _stored_entry(speaker_name: str) -> Dict[str, Any]:
    """The stored configuration for one speaker, or {} when there is none.

    Read here, outside the save's own lock, and merged into the entry that will be
    posted. That is safe because both windows it opens are covered by the same
    guard: `revision` is checked inside `_apply_voice_save` against the
    configuration as read at that moment, so anything that changed after the
    client read - or after this read - is refused with a conflict rather than
    written over.
    """
    raw = safe_load_json(VOICE_CONFIG_PATH, default={})
    entry = raw.get(speaker_name) if isinstance(raw, dict) else None
    return dict(entry) if isinstance(entry, dict) else {}


def execute_voice_command(plan: Dict[str, Any], revision: str, book_token: str) -> Dict[str, Any]:
    """Write a planned command through the save path the Voices tab uses.

    `_apply_voice_save` is imported lazily because `routers.voices` and
    `routers.voices_v2` both live under the same package and this module is
    reachable from either. Delegating means the lock, the revision check, the
    book-token check, the merge, the backup-free atomic write and the conflict
    exception are all the existing ones — Voices V2 adds no second save path and
    no second concurrency strategy.
    """
    from routers.voices import VoiceConfigItem, _apply_voice_save

    try:
        item = VoiceConfigItem(**plan["entry"])
    except ValidationError as error:
        # Refuse rather than write. A stored entry that cannot be validated is
        # pre-existing damage; dropping the offending field to make the save fit
        # would be silent data loss, and posting a partial entry would reset
        # every other declared field to its default. Naming the field is what
        # makes the refusal actionable rather than merely safe.
        fields = sorted({".".join(str(part) for part in item.get("loc", ())) or "entry"
                         for item in error.errors()})
        raise VoiceCommandError(
            "invalid_configuration",
            f"'{plan['speaker_name']}' has a stored voice configuration that cannot be "
            f"validated ({', '.join(fields)}). Nothing was changed.",
            status=409) from error

    result = _apply_voice_save({plan["speaker_name"]: item}, revision, book_token)
    result = dict(result or {})
    result.setdefault("status", "saved")
    result["character"] = plan["speaker_name"]
    result["voice_id"] = plan["voice_id"]
    return result