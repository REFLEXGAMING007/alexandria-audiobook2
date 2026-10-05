"""Voices V2 — the read-only character projection the browser consumes.

Design rules, in priority order:

1. **One coherent document, assembled once per request.** The browser issues a
   single read and derives every view from it, so there is no per-character
   request, no server paging, and no partial-loading waterfall. The payload is
   deliberately small per record: the browser needs to rank, filter and label
   characters, not to reimplement `tts.py`.

2. **Reuse, never reimplement.** The roster, the per-character trait summary and
   the line counts come from the same helpers the legacy Voices read uses, so V2
   and the Voices tab can never disagree about who a character is. See
   `app/voices_v2/__init__.py` for the full list.

3. **Read-only and tolerant.** This module never writes, repairs, migrates or
   renames anything. Malformed JSON, a missing alias file, a dangling persona
   reference and a voice configuration for a character who left the script all
   produce an honest record with a `problems` code, never an exception and never
   a silent fix.

4. **Absence is stated, never implied.** A book generated without
   `config.generation.three_pass_speaker_traits` has no per-line gender or age.
   Reporting that as `traits_available: false` with a `null` summary keeps
   "we do not know" distinct from "the character is unknown", which is the whole
   point of `speaker_traits.py` putting `unknown` in its value list.
"""
import logging
import os
import re
from typing import Any, Dict, List, Optional

from book_state_transaction import (ensure_book_state, get_book_snapshot,
                                     get_book_snapshot_token)
from character_evidence import aliases_for
from config_settings import load_app_config
from core import (CAST_MAJOR_LINE_THRESHOLD, CHARACTER_ALIASES_PATH, CONFIG_PATH,
                  DATA_DIR, SCRIPT_PATH, VOICE_CONFIG_PATH, _load_voice_library,
                  _script_line_counts, get_active_book_id, get_cast_member_key,
                  get_member_labels)
from routers.voices import get_script_speaker, get_voice_rows
from speaker_identity import _identity_key, get_validated_alias_graph
from speaker_traits import AGE_GROUPS, GENDERS, get_state_timeline
from tts import voice_category, voice_is_set
from utils import file_lock, is_generic_speaker, safe_load_json
from voice_config_store import get_voice_config_revision

from voices_v2 import SCHEMA_VERSION
from voices_v2.voice_identity import catalogue_voice_id_for


logger = logging.getLogger(__name__)

# Stable problem codes. The frontend owns the wording; the codes are the contract,
# so a filter can match on them and a rename can never silently change meaning.
PROBLEM_NO_SCRIPT_LINE = "config_without_script_line"
PROBLEM_NO_SPOKEN_LINES = "no_spoken_lines"
PROBLEM_UNKNOWN_SPEAKER = "unknown_speaker_label"
PROBLEM_VOICE_UNASSIGNED = "voice_unassigned"
PROBLEM_VOICE_UNAVAILABLE = "voice_unavailable"
PROBLEM_PERSONA_REF_MISSING = "persona_ref_missing"
PROBLEM_ALIAS_OF_MISSING = "alias_of_missing"
PROBLEM_STATUS_CONFLICT = "voice_status_conflict"
PROBLEM_DUPLICATE_AGE_VERSIONS = "multiple_versions_per_age"
PROBLEM_POSSIBLE_DUPLICATE = "possible_duplicate_identity"
PROBLEM_MALFORMED_CONFIG = "malformed_configuration"

PROBLEM_CODES = (
    PROBLEM_NO_SCRIPT_LINE, PROBLEM_NO_SPOKEN_LINES, PROBLEM_UNKNOWN_SPEAKER,
    PROBLEM_VOICE_UNASSIGNED, PROBLEM_VOICE_UNAVAILABLE, PROBLEM_PERSONA_REF_MISSING,
    PROBLEM_ALIAS_OF_MISSING, PROBLEM_STATUS_CONFLICT,
    PROBLEM_DUPLICATE_AGE_VERSIONS, PROBLEM_POSSIBLE_DUPLICATE,
    PROBLEM_MALFORMED_CONFIG,
)

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _text(value) -> Optional[str]:
    """A trimmed string, or None. Keeps '' and None out of the payload."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def _bool(value) -> bool:
    return bool(value)


def _load_alias_graph() -> Dict[str, str]:
    """The registered alias graph, or {} when the file is absent or invalid.

    `character_aliases.json` is optional user data: an earlier book may never
    have run nickname discovery. A missing file is normal, not an error, so the
    browser reports "no aliases registered" instead of failing the read.
    """
    raw = safe_load_json(CHARACTER_ALIASES_PATH, default={})
    if not isinstance(raw, dict) or not raw:
        return {}
    try:
        return get_validated_alias_graph(raw)
    except (ValueError, TypeError):
        logger.warning("Ignoring an invalid character alias graph at %s", CHARACTER_ALIASES_PATH)
        return {}


def _load_traits_requested() -> Optional[bool]:
    """Whether the active book asked pass 2 for per-line traits.

    Diagnostic only. Whether traits actually exist is decided from the script,
    because a run can have been produced before the switch was turned on, or
    with a model that returned none of the optional fields.
    """
    try:
        config = load_app_config(CONFIG_PATH)
    except (OSError, ValueError):
        return None
    generation = config.get("generation") if isinstance(config, dict) else None
    if not isinstance(generation, dict):
        return None
    requested = generation.get("three_pass_speaker_traits")
    return requested if isinstance(requested, bool) else None


def _book_identity() -> Dict[str, Any]:
    """Book id, script digest and the read-only save-contract token.

    `get_book_snapshot` parses strictly, which is right for the write path and
    wrong here: a malformed document should still yield a browsable page. So the
    snapshot is attempted first and any failure degrades to a projection that
    simply carries no token.
    """
    identity: Dict[str, Any] = {
        "book_id": get_active_book_id(),
        "token": None,
        "script_sha256": None,
        "script_present": os.path.isfile(SCRIPT_PATH),
    }
    try:
        snapshot = get_book_snapshot(DATA_DIR, allow_missing_script=True)
    except (OSError, ValueError, TypeError) as error:
        logger.warning("Voices V2 could not read a book snapshot: %s", error)
        return identity
    identity["book_id"] = snapshot.get("book_id") or identity["book_id"]
    identity["script_sha256"] = snapshot.get("script_sha256")
    identity["token"] = get_book_snapshot_token(snapshot)
    return identity


def _library_labels_by_key() -> Dict[str, List[str]]:
    """Every label each series-cast member answers to, keyed by member key.

    `get_member_labels` is the single place that decides what a library member
    is "known as", including its `known_as` history and any registered alias of
    those. The browser searches those labels, so a character saved from an older
    book is still findable under the name it was saved as.
    """
    library = _load_voice_library()
    collected: Dict[str, List[str]] = {}

    def absorb(key: Optional[str], entry: Dict[str, Any]) -> None:
        if not key or not isinstance(entry, dict):
            return
        bucket = collected.setdefault(key, [])
        for label in get_member_labels(entry, _load_alias_graph()):
            if label not in bucket:
                bucket.append(label)

    aliases = _load_alias_graph()
    for key, entry in (library.get("shared") or {}).items():
        if isinstance(entry, dict):
            absorb(key, {**entry, **{"known_as": get_member_labels(entry, aliases)}})
    for cast in (library.get("casts") or {}).values():
        if not isinstance(cast, dict):
            continue
        for key, entry in (cast.get("members") or {}).items():
            if isinstance(entry, dict):
                absorb(key, {**entry, **{"known_as": get_member_labels(entry, aliases)}})
    return collected


def _voice_summary(config: Dict[str, Any], name: str, book_id: Optional[str]) -> Dict[str, Any]:
    """A small, display-ready summary of one voice configuration.

    Deliberately not the raw config: the browser needs a label, a category and
    whether the voice can actually be synthesised, and it must not be able to
    write any of it back by accident. `voice_category` and `voice_is_set` are the
    two authoritative answers and are imported, not reimplemented.
    """
    category = voice_category(config)
    assigned = voice_is_set(config)
    adapter_id = _text(config.get("adapter_id"))
    adapter_path = _text(config.get("adapter_path"))
    ref_audio = _text(config.get("ref_audio"))

    adapter_available: Optional[bool] = None
    if adapter_path:
        adapter_available = os.path.isdir(adapter_path)

    ref_audio_present: Optional[bool] = None
    if ref_audio:
        # persona/clone references are stored relative to the data directory.
        ref_audio_present = os.path.isfile(
            ref_audio if os.path.isabs(ref_audio) else os.path.join(DATA_DIR, ref_audio))

    members = config.get("members")
    member_count = len(members) if isinstance(members, list) else 0

    if category == "lora":
        label = adapter_id or "LoRA voice"
    elif category == "ensemble":
        label = f"Ensemble of {member_count}" if member_count else "Ensemble"
    elif category == "design":
        # The design's own name, so several designed voices are distinguishable.
        # `voice` is what a design assignment stores.
        label = _text(config.get("voice")) or "Designed voice"
    elif category == "clone":
        label = _text(config.get("voice")) or "Cloned voice"
    else:
        label = _text(config.get("voice")) or "Default voice"

    return {
        "category": category,
        # The stored `type` verbatim. `category` collapses lora and builtin_lora
        # because synthesis treats them alike, but they are different catalogue
        # entries and the assignment editor has to tell them apart.
        "type": _text(config.get("type")),
        "label": label,
        "assigned": assigned,
        # Which catalogue row this configuration names, when one does. Null is a
        # real answer, not a gap: a design-persona preview or a deleted clone is
        # a voice the catalogue does not hold, and the editor has to say so
        # rather than show a selector disagreeing with what is stored.
        "catalogue_voice_id": catalogue_voice_id_for(config),
        "adapter_id": adapter_id,
        "adapter_available": adapter_available,
        "has_ref_audio": bool(ref_audio),
        "ref_audio_present": ref_audio_present,
        "has_description": bool((_text(config.get("description")))),
        "seed": config.get("seed") if isinstance(config.get("seed"), (str, int)) else None,
        "alias_of": _text(config.get("alias_of")),
        "ensemble_members": member_count,
    }


def _version_rows(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Versions as {version_id, age_group, category, label} — no overlays.

    A version entry is a whole voice configuration; exposing it raw would give
    the browser megabytes of `character_style` prose and a write surface it must
    not have. `voice_category` is used per version so the browser can say which
    kind of voice a version would speak with.
    """
    versions = config.get("versions")
    if not isinstance(versions, dict):
        return []
    rows = []
    for version_id, version in versions.items():
        if not isinstance(version, dict):
            continue
        category = voice_category(version)
        adapter_id = _text(version.get("adapter_id"))
        voice_name = _text(version.get("voice"))
        if category == "lora":
            label = adapter_id or "LoRA voice"
        elif category == "ensemble":
            label = "Ensemble"
        elif category == "design":
            label = "Designed voice"
        elif category == "clone":
            label = voice_name or "Cloned voice"
        else:
            label = voice_name or "Default voice"
        rows.append({
            "version_id": str(version_id),
            "age_group": _text(version.get("age_group")),
            "category": category,
            "label": label,
            "adapter_id": adapter_id,
        })
    return rows


def _duplicate_fold(name: str) -> str:
    """Alphanumerics-only fold, used ONLY to raise a possible-duplicate hint.

    No existing normaliser merges `PROFESSOR FERNANDO` with
    `PROFESSOR_FERNANDO`: `_identity_key` keeps `_` because it is a word
    character, and `_norm_name` keeps punctuation. That is correct — merging them
    is a judgement call, not a rule — so V2 must not decide it either. Instead
    two records that fold alike are reported side by side and the user chooses.
    This function never affects identity, grouping or storage.
    """
    return _NON_ALNUM.sub("", (name or "").casefold())


def _problems(record_context: Dict[str, Any]) -> List[str]:
    """Stable problem codes for one record, in a fixed order.

    A record is assembled before this runs, so every signal needed is already on
    it. Codes describe what is true; they never suggest a fix, because repairing
    any of these is a later phase and a separate decision.
    """
    codes: List[str] = []
    if record_context["malformed_config"]:
        codes.append(PROBLEM_MALFORMED_CONFIG)
    if not record_context["present_in_script"]:
        codes.append(PROBLEM_NO_SCRIPT_LINE)
    elif record_context["line_count"] == 0:
        codes.append(PROBLEM_NO_SPOKEN_LINES)
    if record_context["name_upper"] == "UNKNOWN":
        codes.append(PROBLEM_UNKNOWN_SPEAKER)
    if not record_context["voice"]["assigned"]:
        codes.append(PROBLEM_VOICE_UNASSIGNED)
    if record_context["voice"]["adapter_available"] is False or \
            record_context["voice"]["ref_audio_present"] is False:
        codes.append(PROBLEM_VOICE_UNAVAILABLE)
    if record_context["persona_ref"] and not record_context["persona_ref_resolves"]:
        codes.append(PROBLEM_PERSONA_REF_MISSING)
    if record_context["voice"]["alias_of"] and not record_context["alias_of_exists"]:
        codes.append(PROBLEM_ALIAS_OF_MISSING)
    # The stored `voice_status` says unassigned while a voice IS configured. The
    # reverse (a stale "assigned" over nothing) is already reported as
    # voice_unassigned, which is the more useful half of the same inconsistency.
    if record_context["voice_status"] == "unassigned" and record_context["voice"]["assigned"]:
        codes.append(PROBLEM_STATUS_CONFLICT)
    ages = [version["age_group"] for version in record_context["versions"]
            if version["age_group"]]
    if len(ages) != len(set(ages)):
        codes.append(PROBLEM_DUPLICATE_AGE_VERSIONS)
    if record_context["possible_duplicate_of"]:
        codes.append(PROBLEM_POSSIBLE_DUPLICATE)
    return codes


def _character_record(name: str, *, present_in_script: bool, config: Dict[str, Any],
                      malformed_config: bool, row: Optional[Dict[str, Any]],
                      line_count: int,
                      timeline: Optional[List[Dict[str, Any]]], library_labels,
                      aliases: List[str], book_id: Optional[str],
                      config_keys, possible_duplicates: List[str]) -> Dict[str, Any]:
    """One character record. Every field is JSON-native and null-safe."""
    persona_ref = _text(config.get("persona_ref"))
    if persona_ref:
        persona_resolved = os.path.isfile(
            persona_ref if os.path.isabs(persona_ref) else os.path.join(DATA_DIR, persona_ref))
    else:
        persona_resolved = None

    library_key: Optional[str] = None
    try:
        library_key = get_cast_member_key(name, book_id)
    except (ValueError, TypeError):
        # A generic label without a resolvable book id cannot be keyed. That is
        # reported as a missing key rather than a synthetic one.
        library_key = None

    traits = row.get("traits") if isinstance(row, dict) else None

    record = {
        # `key` is the stable selection identifier for the whole lifetime of a
        # projection: it is derived from the stored name, never from a position.
        "key": library_key or f"name:{name}",
        "name": name,
        "identity_key": _identity_key(name),
        "library_key": library_key,
        "present_in_script": present_in_script,
        "generic": is_generic_speaker(name),
        "line_count": line_count,
        "priority": ("major" if line_count >= CAST_MAJOR_LINE_THRESHOLD else "minor")
        if line_count else None,
        "known_as": list(library_labels),
        "aliases": aliases,
        "voice": _voice_summary(config, name, book_id),
        "voice_status": _text(config.get("voice_status")),
        "persona_status": _text(config.get("persona_status")),
        "ready": _bool(config.get("ready")),
        "persona_ref": persona_ref,
        "persona_ref_resolves": persona_resolved,
        "active_version": _text(config.get("active_version")),
        "versions": _version_rows(config),
        "version_timeline": [
            {"from_index": point.get("from_index"), "version_id": _text(point.get("version_id"))}
            for point in (config.get("version_timeline") or [])
            if isinstance(point, dict)
        ],
        "candidate_count": len(config.get("candidates") or []) if isinstance(
            config.get("candidates"), list) else 0,
        "traits": traits,
        "traits_available": traits is not None,
        "states": timeline or [],
        "possible_duplicate_of": possible_duplicates,
        "problems": [],
    }

    record["problems"] = _problems({
        "malformed_config": malformed_config,
        "present_in_script": present_in_script,
        "line_count": line_count,
        "name_upper": (name or "").strip().upper(),
        "voice": record["voice"],
        "persona_ref": persona_ref,
        "persona_ref_resolves": persona_resolved,
        "alias_of_exists": bool(record["voice"]["alias_of"]
                                and record["voice"]["alias_of"] in config_keys),
        "ready": record["ready"],
        "voice_status": record["voice_status"],
        "versions": record["versions"],
        "possible_duplicate_of": possible_duplicates,
    })
    return record


def _script_entries() -> List[Dict[str, Any]]:
    """The active script as a list of entries, tolerating anything unusable."""
    raw = safe_load_json(SCRIPT_PATH, default=[])
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def _voice_config_map() -> Dict[str, Any]:
    raw = safe_load_json(VOICE_CONFIG_PATH, default={})
    return raw if isinstance(raw, dict) else {}


def build_character_projection() -> Dict[str, Any]:
    """Assemble the whole Voices V2 character projection for the active book.

    Read-only. Holds `ensure_book_state` for the book-operation lock and
    `file_lock` on both JSON documents, so a book switch or a save cannot be
    observed half-applied. Runs in a worker thread via the router.
    """
    with ensure_book_state(DATA_DIR):
        with file_lock(VOICE_CONFIG_PATH):
            voice_config = _voice_config_map()
            script_entries = _script_entries()
            line_counts = _script_line_counts(SCRIPT_PATH)
            alias_graph = _load_alias_graph()
            library_labels = _library_labels_by_key()

            book = _book_identity()
            book_id = book.get("book_id")

            # The roster, the per-character config and the trait summary all come
            # from the one helper the legacy read uses, so the two UIs cannot
            # disagree about who a character is.
            #
            # Entries that are not objects are excluded before that call:
            # `get_voice_rows` -> `voice_is_set` -> `voice_category` calls `.get`
            # on the entry, so one hand-edited `voice_config.json` value would
            # otherwise 500 the whole browser. The key is still enumerated below,
            # and the affected record carries `malformed_configuration`, so the
            # bad value is reported rather than hidden or repaired.
            usable_config = {name: value for name, value in voice_config.items()
                             if isinstance(value, dict)}
            rows = {row["name"]: row
                    for row in get_voice_rows(script_entries, usable_config)
                    if isinstance(row, dict) and row.get("name")}
            timelines = {str(key).upper(): value
                         for key, value in get_state_timeline(script_entries).items()}

            traits_available = any("speaker_gender" in entry for entry in script_entries)
            config_keys = set(voice_config)

            roster_names = sorted(rows)
            orphans = sorted(name for name in config_keys if name not in rows)

            # Possible-duplicate hints are computed across characters AND
            # orphans together, because the live data has one of each split by
            # an underscore, and reporting only half the pair would hide it.
            folds: Dict[str, List[str]] = {}
            for name in roster_names + orphans:
                folds.setdefault(_duplicate_fold(name), []).append(name)

            def build(name: str, present_in_script: bool) -> Dict[str, Any]:
                raw = voice_config.get(name)
                config = raw if isinstance(raw, dict) else {}
                try:
                    library_key = get_cast_member_key(name, book_id)
                except (ValueError, TypeError):
                    library_key = None
                duplicates = [other for other in folds.get(_duplicate_fold(name), [])
                              if other != name]
                return _character_record(
                    name,
                    present_in_script=present_in_script,
                    config=config,
                    malformed_config=raw is not None and not isinstance(raw, dict),
                    row=rows.get(name),
                    line_count=line_counts.get(name, 0),
                    timeline=timelines.get(name.strip().upper()),
                    library_labels=library_labels.get(library_key or "", []),
                    aliases=sorted(aliases_for(name, alias_graph)),
                    book_id=book_id,
                    config_keys=config_keys,
                    possible_duplicates=duplicates,
                )

            characters = [build(name, True) for name in roster_names]
            orphan_records = [build(name, False) for name in orphans]

    return {
        "schema_version": SCHEMA_VERSION,
        "book": book,
        # The two fields the guarded save contract requires. The browser has to
        # hold them from the moment it reads, because a save that cannot prove
        # which snapshot it was based on is a save that can silently overwrite
        # someone else's work. `book.token` changes when the book changes;
        # `revision` changes when any voice configuration changes.
        "revision": get_voice_config_revision(voice_config),
        "traits_available": traits_available,
        "traits_requested": _load_traits_requested(),
        "aliases_registered": bool(alias_graph),
        "major_line_threshold": CAST_MAJOR_LINE_THRESHOLD,
        "vocabularies": {
            "genders": list(GENDERS),
            "age_groups": [{"value": value, "label": label} for value, label in AGE_GROUPS],
            "problem_codes": list(PROBLEM_CODES),
        },
        "characters": characters,
        "orphans": orphan_records,
        "counts": {"characters": len(characters), "orphans": len(orphan_records)},
    }