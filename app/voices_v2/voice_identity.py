"""Voices V2 — the catalogue voice-id scheme, shared by both halves of the domain.

A catalogue id is `"<kind>:<native id>"`, where the kind is one of the four voice
families Voices V2 can assign. Keeping the scheme in its own module lets the
projection (which reports the voice a character already has) and the assignment
command (which changes it) agree on one identity without importing each other.

Two properties matter:

- **Stable.** The id is derived from the manifest's own id, so a voice keeps its
  identity across reloads and across catalogue rebuilds.
- **Honest.** `catalogue_voice_id_for` returns None when a stored configuration
  does not correspond to anything in the catalogue — a design persona preview, a
  hand-entered adapter, a deleted clone. The UI then shows the stored voice by
  its own label and marks it "not in the catalogue", rather than silently
  selecting a different voice.
"""
import os
from typing import Any, Dict, Optional

from core import CLONE_VOICES_DIR, DESIGNED_VOICES_DIR
from utils import safe_load_json


KIND_LORA = "lora"
KIND_BUILTIN_LORA = "builtin_lora"
KIND_CLONE = "clone"
KIND_DESIGN = "design"
ASSIGNABLE_KINDS = (KIND_LORA, KIND_BUILTIN_LORA, KIND_CLONE, KIND_DESIGN)

CLONE_VOICES_MANIFEST = os.path.join(CLONE_VOICES_DIR, "manifest.json")
DESIGNED_VOICES_MANIFEST = os.path.join(DESIGNED_VOICES_DIR, "manifest.json")


def voice_id(kind: str, native_id: str) -> str:
    return f"{kind}:{native_id}"


def split_voice_id(value) -> tuple:
    """Split a catalogue id into `(kind, native id)`.

    The prefix is the only part a client controls, so it is validated against the
    assignable set rather than parsed permissively: an id naming a family V2
    cannot write is refused before it reaches a path.
    """
    raw = value.strip() if isinstance(value, str) else ""
    kind, separator, native = raw.partition(":")
    if not separator or kind not in ASSIGNABLE_KINDS or not native.strip():
        return None, None
    return kind, native.strip()


def _normalise(path) -> str:
    return str(path or "").replace("\\", "/").lstrip("./")


def _manifest_by_ref_audio(manifest_path: str, namespace: str, ref_audio) -> Optional[str]:
    """The manifest id whose stored asset path matches a configuration reference.

    Matched on the path rather than the id, because that is what the
    configuration actually stores, and two designs can share a display name.
    """
    target = _normalise(ref_audio)
    if not target:
        return None
    raw = safe_load_json(manifest_path, default=[])
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        filename = entry.get("filename")
        if isinstance(filename, str) and f"{namespace}/{filename}".replace("\\", "/") == target:
            native = entry.get("id")
            return str(native) if isinstance(native, str) and native else None
    return None


def catalogue_voice_id_for(entry: Dict[str, Any]) -> Optional[str]:
    """The catalogue id of the voice a stored configuration describes, if any.

    Returns None rather than a guess. A configuration that names a
    `designed_voices/persona/...` preview has no catalogue row - it came from the
    persona pipeline, not the Designer - and reporting None is what lets the UI
    say so instead of offering a select control that quietly disagrees with what
    is stored.
    """
    if not isinstance(entry, dict):
        return None
    kind = entry.get("type")
    adapter_id = entry.get("adapter_id")
    if kind in (KIND_LORA, KIND_BUILTIN_LORA) and isinstance(adapter_id, str) and adapter_id.strip():
        return voice_id(kind, adapter_id.strip())
    if kind == "clone":
        native = _manifest_by_ref_audio(CLONE_VOICES_MANIFEST, "clone_voices", entry.get("ref_audio"))
        return voice_id(KIND_CLONE, native) if native else None
    if kind == "design":
        native = _manifest_by_ref_audio(DESIGNED_VOICES_MANIFEST, "designed_voices",
                                        entry.get("ref_audio"))
        return voice_id(KIND_DESIGN, native) if native else None
    return None