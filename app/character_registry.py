"""Character State Processor / Character Registry.

Derives a structured, persisted character/state index from a completed
annotated script. The registry is deterministic, does not call an LLM,
and consumes the final annotated entries plus existing cast information.
"""

import hashlib
import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from core import (
    CHARACTER_ALIASES_PATH,
    DATA_DIR,
    get_active_book_id,
    is_generic_speaker,
    safe_load_json,
)
from utils import atomic_json_write


# Registry file path (next to annotated_script.json)
CHARACTER_REGISTRY_PATH = os.path.join(DATA_DIR, "character_registry.json")

# Default cast file path (if not overridden)
DEFAULT_CAST_PATH = os.path.join(DATA_DIR, "cast.json")

# Valid gender values (from Pass 2 schema)
VALID_GENDERS = frozenset({"MALE", "FEMALE", "UNSPECIFIED"})

# Valid age_group values (from Pass 2 schema)
VALID_AGE_GROUPS = frozenset({
    "CHILD", "TEEN", "YOUNG_ADULT", "ADULT",
    "MIDDLE_AGED", "ELDERLY", "AGELESS", "UNSPECIFIED"
})

# Character type enum
CHARACTER_TYPES = frozenset({"NAMED", "BACKGROUND", "GROUP", "UNKNOWN", "NARRATOR"})

# Group speaker patterns (from existing conventions)
_GROUP_PATTERNS = (
    "_GROUP",
    " GROUP",
    " GROUP_",
)


def _norm_name(name: str) -> str:
    """Normalize a character name for matching."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _compute_script_fingerprint(entries: List[Dict[str, Any]]) -> str:
    """Compute a fingerprint of the annotated script for invalidation."""
    # Use a stable serialization of just the semantic content
    content = []
    for entry in entries:
        if isinstance(entry, dict):
            # Include speaker, gender, age_group, text (not instruct which can vary)
            content.append({
                "speaker": entry.get("speaker"),
                "gender": entry.get("gender"),
                "age_group": entry.get("age_group"),
                "text": entry.get("text"),
            })
    encoded = json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_cast_names(cast_path: Optional[str] = None) -> Set[str]:
    """Load the canonical named character roster from the active cast, if any."""
    path = cast_path or DEFAULT_CAST_PATH
    if not os.path.exists(path):
        return set()

    try:
        raw = open(path, "rb").read()
        data = json.loads(raw.decode("utf-8"))
        if isinstance(data, dict):
            data = data.get("cast")
        if not isinstance(data, list) or not data:
            return set()
        names = set()
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"].strip().upper())
        return names
    except Exception:
        return set()


def _load_character_aliases() -> Dict[str, str]:
    """Load the global character aliases mapping."""
    aliases = safe_load_json(CHARACTER_ALIASES_PATH, default={})
    return aliases if isinstance(aliases, dict) else {}


def _is_group_speaker(speaker: str) -> bool:
    """Determine if a speaker is a group identity based on project conventions."""
    if not speaker:
        return False
    upper = speaker.upper()
    for pattern in _GROUP_PATTERNS:
        if pattern in upper:
            return True
    return False


def _classify_character(
    speaker: str,
    cast_names: Set[str],
    aliases: Dict[str, str]
) -> str:
    """Classify a speaker into one character type."""
    if not speaker:
        return "UNKNOWN"

    upper = speaker.upper()

    if upper == "NARRATOR":
        return "NARRATOR"
    if upper == "UNKNOWN":
        return "UNKNOWN"
    if _is_group_speaker(speaker):
        return "GROUP"
    if upper in cast_names:
        return "NAMED"
    # Check if it's an alias of a named character
    for alias, canonical in aliases.items():
        if _norm_name(alias) == _norm_name(speaker):
            if canonical.upper() in cast_names:
                return "NAMED"
    # Background characters (generic or numeric)
    if is_generic_speaker(speaker):
        return "BACKGROUND"
    # Default to BACKGROUND for any other non-named speaker
    return "BACKGROUND"


def _normalize_gender(gender: Optional[str]) -> str:
    """Normalize gender to valid value."""
    if not gender:
        return "UNSPECIFIED"
    upper = str(gender).strip().upper()
    return upper if upper in VALID_GENDERS else "UNSPECIFIED"


def _normalize_age_group(age_group: Optional[str]) -> str:
    """Normalize age_group to valid value."""
    if not age_group:
        return "UNSPECIFIED"
    upper = str(age_group).strip().upper()
    return upper if upper in VALID_AGE_GROUPS else "UNSPECIFIED"


def _compute_display_name(speaker: str, character_type: str) -> str:
    """Compute a human-readable display name for the character."""
    if character_type == "NARRATOR":
        return "Narrator"
    if character_type == "UNKNOWN":
        return "Unknown"
    # Convert UPPER_SNAKE_CASE to Title Case
    words = speaker.replace("_", " ").split()
    return " ".join(w.capitalize() for w in words)


def build_character_registry(
    annotated_entries: List[Dict[str, Any]],
    book_id: Optional[str] = None,
    cast_names: Optional[Set[str]] = None,
    aliases: Optional[Dict[str, str]] = None,
    cast_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the Character Registry from a completed annotated script.

    Args:
        annotated_entries: The final annotated script entries from run_three_pass.
        book_id: Optional book identifier.
        cast_names: Optional set of canonical named character names (uppercase).
        aliases: Optional character aliases mapping.
        cast_path: Optional path to a cast file. If not provided, uses default location.

    Returns:
        The complete registry dictionary ready for persistence.
    """
    if book_id is None:
        book_id = get_active_book_id() or "unknown"

    if cast_names is None:
        cast_names = _load_cast_names(cast_path)

    if aliases is None:
        aliases = _load_character_aliases()

    script_fingerprint = _compute_script_fingerprint(annotated_entries)

    # Aggregate state occurrences per speaker
    speaker_states: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for idx, entry in enumerate(annotated_entries):
        if not isinstance(entry, dict):
            continue

        speaker = (entry.get("speaker") or "").strip()
        if not speaker:
            continue

        # NARRATOR does not have gender/age_group states - skip state aggregation
        if speaker.upper() == "NARRATOR":
            continue

        gender = _normalize_gender(entry.get("gender"))
        age_group = _normalize_age_group(entry.get("age_group"))
        state_key = f"{gender}|{age_group}"

        if speaker not in speaker_states:
            speaker_states[speaker] = {}

        if state_key not in speaker_states[speaker]:
            speaker_states[speaker][state_key] = {
                "gender": gender,
                "age_group": age_group,
                "line_indices": [],
                "line_count": 0,
                "first_line": idx,
                "last_line": idx,
            }

        state = speaker_states[speaker][state_key]
        state["line_indices"].append(idx)
        state["line_count"] += 1
        state["last_line"] = idx

    # Ensure NARRATOR is included in characters even without states
    has_narrator = any(
        isinstance(e, dict) and (e.get("speaker") or "").strip().upper() == "NARRATOR"
        for e in annotated_entries
    )

    # Build character records
    characters = {}
    for speaker, states in speaker_states.items():
        character_type = _classify_character(speaker, cast_names, aliases)
        display_name = _compute_display_name(speaker, character_type)

        character_record = {
            "display_name": display_name,
            "character_type": character_type,
            "states": states,
        }

        # UNKNOWN gets special non-assignable flag
        if character_type == "UNKNOWN":
            character_record["assignable"] = False

        characters[speaker] = character_record

    # Add NARRATOR if present in script
    if has_narrator:
        characters["NARRATOR"] = {
            "display_name": "Narrator",
            "character_type": "NARRATOR",
            "states": {},
        }

    registry = {
        "version": 1,
        "book_id": book_id,
        "script_fingerprint": script_fingerprint,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "characters": characters,
    }

    return registry


def save_character_registry(registry: Dict[str, Any], path: Optional[str] = None) -> None:
    """Save the character registry to disk."""
    if path is None:
        path = CHARACTER_REGISTRY_PATH
    atomic_json_write(registry, path)


def load_character_registry(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Load the character registry from disk."""
    if path is None:
        path = CHARACTER_REGISTRY_PATH
    return safe_load_json(path, default=None)


def is_character_registry_current(
    registry: Optional[Dict[str, Any]],
    annotated_entries: List[Dict[str, Any]],
) -> bool:
    """Check if the loaded registry matches the current annotated script."""
    if registry is None:
        return False
    if not isinstance(registry, dict):
        return False
    current_fingerprint = _compute_script_fingerprint(annotated_entries)
    return registry.get("script_fingerprint") == current_fingerprint


def ensure_character_registry(
    annotated_entries: List[Dict[str, Any]],
    book_id: Optional[str] = None,
    force_rebuild: bool = False,
    cast_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure a current character registry exists, building/rebuilding if needed.

    This is the primary integration point - call after loading or generating a script.

    Args:
        annotated_entries: The current annotated script entries.
        book_id: Optional book identifier.
        force_rebuild: If True, rebuild even if registry exists and matches.
        cast_path: Optional path to a cast file.

    Returns:
        The current character registry.
    """
    if not force_rebuild:
        existing = load_character_registry()
        if is_character_registry_current(existing, annotated_entries):
            return existing

    registry = build_character_registry(annotated_entries, book_id=book_id, cast_path=cast_path)
    save_character_registry(registry)
    return registry