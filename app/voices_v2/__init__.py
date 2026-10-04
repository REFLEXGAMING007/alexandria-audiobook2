"""Voices V2 — the standalone voice-management feature domain beside Voices.

Phase 0 registered the boundary. Phase 1 adds the first real read: a character
projection that joins the active script, `voice_config.json`, the voice library
and the character alias graph into one document for the Voices V2 browser.

The modules here compose helpers that already exist and are authoritative:

  routers/voices.py::get_voice_rows      roster, config and per-character traits
  core::_script_line_counts              per-speaker spoken-line counts
  speaker_traits.py                      GENDERS / AGE_GROUPS / trait summaries
  tts.py::voice_category, voice_is_set   voice type and "does this have a voice"
  core::get_cast_member_key              the cross-book identity key
  core::get_member_labels                every label a library member answers to
  character_evidence.py::aliases_for     the registered alias graph
  speaker_identity.py::_identity_key     the fold used for identity comparison
  book_state_transaction.py              book identity, script digest, token

Nothing here writes, repairs, migrates or normalises stored data. Every helper
above is read-only and is called under `ensure_book_state`, and the two JSON
documents are read with `safe_load_json` so malformed input degrades into an
honest "unavailable" rather than an exception.
"""

SCHEMA_VERSION = 1