"""Voices V2 — the normalised VoiceRecord.

Every family the application owns is adapted into one shape here, so the library
has a single logical catalogue instead of four lists. The `kind:nativeId` id from
`voice_identity` is the identity; this module only decides what else a voice can
honestly be said to be.

The rule that shapes the schema: **absent is not the same as unknown, and
inferred is not the same as declared.**

- `gender` / `age_group` carry the best value available.
- `gender_source` / `age_group_source` say where it came from: `declared` (the
  source states it), `inferred` (a heuristic guessed it) or `unknown`.

The inference itself is not reimplemented. `routers.voices` already has
`_infer_lora_gender` and `_infer_lora_age`, which return the declared value when
one is present and only then fall back to a heuristic. The split is applied here
rather than inside those helpers because they answer a different question - "what
is the best value" - and Phase 1's suggestion path and the library need different
answers from the same manifest row.

Nothing here fabricates. A clone has no gender field, so its `gender` is `unknown`
and its `gender_source` is `unknown`; the library shows "Unknown" and the voice
stays selectable. That is the behaviour that lets a future automatic-metadata
phase fill these in without having to un-invent anything.
"""
import os
from typing import Any, Dict, List, Optional

from speaker_traits import AGE_GROUP_NAMES


SOURCE_DECLARED = "declared"
SOURCE_INFERRED = "inferred"
SOURCE_UNKNOWN = "unknown"

#: How a voice is realised, which is not the same question as which family it
#: belongs to. Two designs and two clones are both `design`/`clone` by family but
#: share nothing about how they are produced.
REALISATION_ADAPTER = "adapter"
REALISATION_CLONE_RECORDING = "clone_recording"
REALISATION_DESCRIPTION = "description"

GENDERS = ("male", "female", "genderless")

KIND_SOURCE_LABELS = {
    "lora": "Trained LoRA",
    "builtin_lora": "Built-in LoRA",
    "clone": "Uploaded clone",
    "design": "Designed voice",
}

KIND_REALISATIONS = {
    "lora": REALISATION_ADAPTER,
    "builtin_lora": REALISATION_ADAPTER,
    "clone": REALISATION_CLONE_RECORDING,
    "design": REALISATION_DESCRIPTION,
}

#: Favourites are persisted as adapter ids, so only adapter families have one.
#: Saying so is better than showing a star that silently does nothing.
FAVORITE_CAPABLE_KINDS = ("lora", "builtin_lora")

#: Phase 3 previews are recordings that already exist on disk and are served by
#: the static mounts the application already has. Generated previews (LoRA test,
#: Voice Designer) need a GPU claim and belong to a later phase.
PREVIEW_KIND_RECORDING = "recording"


def text(value) -> Optional[str]:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed or None


def declared_gender(entry: Dict[str, Any]) -> Optional[str]:
    """The gender the source states outright, or None."""
    value = text(entry.get("gender"))
    return value.lower() if value and value.lower() in GENDERS else None


def declared_age_group(entry: Dict[str, Any]) -> Optional[str]:
    """The age band the source states outright, or None.

    Read separately from `_infer_lora_age`, which collapses "stated" and "guessed"
    into one answer and would report a heuristic as a fact.

    Membership is tested against AGE_GROUP_NAMES, the tuple of band values.
    `AGE_GROUPS` is the tuple of (value, label) pairs, and a membership test
    against that never matches - which is why a band this function reports as
    declared is a band the manifest actually said, rather than an accident.
    """
    for key in ("age_group", "age"):
        value = text(entry.get(key))
        if value:
            normalised = value.lower().replace("-", "_").replace(" ", "_")
            if normalised in AGE_GROUP_NAMES:
                return normalised
    return None


def resolve_provenance(declared: Optional[str], inferred: Optional[str]):
    """Return `(value, source)` preferring a stated value over a guessed one.

    A heuristic is only consulted when the source is silent, and a heuristic that
    produces nothing stays `unknown` rather than being recorded as inferred.
    """
    if declared:
        return declared, SOURCE_DECLARED
    if inferred and inferred != SOURCE_UNKNOWN:
        return inferred, SOURCE_INFERRED
    return SOURCE_UNKNOWN, SOURCE_UNKNOWN


def _epoch(value) -> Optional[int]:
    """A stated creation time as an integer, or None.

    Only used for the library's "recently added" sort. A source that states no
    date yields None and the voice sorts last: an absent date is not a recent
    one, and treating it as 1970 would quietly invent an ordering.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        if text_value.isdigit():
            return int(text_value)
    return None


def stated_added_at(entry: Dict[str, Any], *keys: str) -> Optional[int]:
    """The first stated creation time among `keys`, preferring the earliest key."""
    for key in keys:
        found = _epoch(entry.get(key))
        if found is not None:
            return found
    return None


def voice_record(*, voice_id: str, native_id: str, kind: str, name: str,
                 description: Optional[str], sample_text: Optional[str],
                 gender_declared: Optional[str], gender_inferred: Optional[str],
                 age_declared: Optional[str], age_inferred: Optional[str],
                 available: bool, unavailable_reason: str, downloaded: bool,
                 favorite: bool, adapter_id: Optional[str], adapter_path: Optional[str],
                 ref_audio: Optional[str], ref_text: Optional[str],
                 preview_url: Optional[str], metadata: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Any]:
    """One catalogue row, in the shape the library consumes.

    `metadata` carries only what the source said and Voices V2 does not
    interpret. It exists so a future phase can surface training details without
    another schema change - and so nothing here has to guess at meaning.
    """
    gender, gender_source = resolve_provenance(gender_declared, gender_inferred)
    age_group, age_source = resolve_provenance(age_declared, age_inferred)
    return {
        # Identity. `voice_id` is the catalogue key; `native_id` is what the
        # owning system calls it, so a user can match it against the Designer or
        # the training manifest.
        "voice_id": voice_id,
        "native_id": native_id,
        "kind": kind,
        "name": name,
        # `label` is the display string; `name` stays the raw source name so a
        # stored configuration can be matched to it exactly.
        "label": name,
        "source": text(KIND_SOURCE_LABELS.get(kind)) or kind,
        "realisation": KIND_REALISATIONS.get(kind),
        "description": description,
        "sample_text": sample_text,
        # Gender and age, each with its provenance.
        "gender": gender,
        "gender_source": gender_source,
        "age_group": age_group,
        "age_group_source": age_source,
        # A stated creation time, or null. Null is what the "recent" sort reads
        # as "unknown", and such voices sort last rather than pretending to be new.
        "added_at": metadata.get("added_at") if isinstance(metadata, dict) else None,
        # Availability. `availability` is a word for the UI to display; `available`
        # is the boolean a filter tests.
        "availability": "available" if available else "unavailable",
        "available": available,
        "unavailable_reason": unavailable_reason,
        "downloaded": downloaded,
        # Favourites, and whether this family has anywhere to store one.
        "favorite": favorite,
        "favorite_supported": kind in FAVORITE_CAPABLE_KINDS,
        # Adapter families only.
        "adapter_id": adapter_id,
        "adapter_path": adapter_path,
        # Clone and design families only.
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        # Phase 3 plays recordings that already exist; nothing is generated here.
        "preview_capable": bool(preview_url),
        "preview_url": preview_url,
        "preview_kind": PREVIEW_KIND_RECORDING if preview_url else None,
        # Reserved for a later tagging phase. Empty is honest: no source here
        # publishes tags, and an inferred tag must not be presented as one.
        "tags": [],
        "metadata": metadata or {},
    }


def clone_and_design_preview_url(namespace: str, filename: Optional[str],
                                 root: str) -> Optional[str]:
    """A static URL for a recording the manifest already points at.

    `/clone_voices` and `/designed_voices` are mounted by `app.py` today, so this
    needs no new endpoint and no preview generation. The existence check is what
    keeps a dead path out of the selector - a play button that 404s is worse than
    no play button.
    """
    if not filename:
        return None
    path = os.path.join(root, filename)
    if not os.path.isfile(path):
        return None
    return f"/{namespace}/{filename}"


def searchable_text(record: Dict[str, Any]) -> str:
    """Everything a multi-term search is allowed to match, lower-cased once.

    Built per record and cached by the caller, so a keystroke does not re-join
    the same strings for every voice. Gender and age are included because a user
    typing "female" should find female voices without opening a filter.
    """
    parts: List[str] = [
        record.get("name"), record.get("label"), record.get("description"),
        record.get("kind"), record.get("source"), record.get("gender"),
        record.get("age_group"), record.get("native_id"),
    ]
    parts.extend(record.get("tags") or [])
    return " ".join(part for part in parts if isinstance(part, str)).lower()