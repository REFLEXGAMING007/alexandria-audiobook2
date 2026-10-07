/* Voices V3 — pure derivations and the save payload builder.
 *
 * Nothing in this file touches the DOM or performs I/O. That is what lets the
 * payload builder be a pure function of the store, which in turn is what makes a
 * save reproducible no matter how many times the roster has been re-rendered.
 *
 * The payload builder is the most important function here. It reproduces the
 * original Voices tab's save contract exactly — same merge order, same seed
 * ownership, same `ready`/`alias_of` omission behaviour — while reading from
 * state instead of scraping markup.
 */
(function (namespace) {
    'use strict';

    var FORM_OWNED_KEYS = [
        'type', 'voice', 'character_style', 'ref_audio', 'ref_text',
        'adapter_id', 'adapter_path', 'description', 'members', 'alias_of', 'ready'
    ];

    function clone(value) { return JSON.parse(JSON.stringify(value)); }

    /* ------------------------------------------------------------------ */
    /* adapters                                                            */
    /* ------------------------------------------------------------------ */

    function text(value) { return typeof value === 'string' ? value : ''; }

    function arrayOf(value) { return Array.isArray(value) ? value : []; }

    function rosterOf(state) {
        var roster = state.roster || {};
        return { names: arrayOf(roster.names), byName: roster.byName || {} };
    }

    function storedConfig(state, name) {
        var entry = rosterOf(state).byName[name];
        return entry && entry.config && typeof entry.config === 'object' ? entry.config : {};
    }

    function workingOf(state, name) {
        var working = state.working && state.working[name];
        return working && typeof working === 'object' ? working : {};
    }

    /* ------------------------------------------------------------------ */
    /* row identity                                                         */
    /* ------------------------------------------------------------------ */
    /* A roster row's KEY is its `row_key`, which for a state row is
     * "MARO#adult". Two identities travel with every row and mixing them up is
     * the failure this whole design exists to prevent:
     *
     *   key ("MARO#adult")   identifies the row. The store, the DOM attribute and
     *                        the save map are keyed by this. Three states of one
     *                        character are three distinct keys.
     *   speaker ("MARO")     identifies the character in voice_config.json and in
     *                        every speaker-scoped API path. A state row must never
     *                        reach an API under its key, or it would address a
     *                        character that does not exist.
     *
     * `name` stays the character's own name for display, so nothing that matches
     * on the visible name changes.
     */

    function rowOf(state, key) {
        return rosterOf(state).byName[key] || null;
    }

    function speakerOf(state, key) {
        var row = rowOf(state, key);
        if (!row) { return typeof key === 'string' ? key.split('#')[0] : ''; }
        return row.speaker || row.name || '';
    }

    /* Is this row one settled state of a character, rather than the character? */
    function isStateRow(state, key) {
        var row = rowOf(state, key);
        if (!row) { return false; }
        return key !== (row.speaker || row.name);
    }

    /* The age band a state row is stored under, or null for a plain row. */
    function stateAgeGroup(state, key) {
        var row = rowOf(state, key);
        if (!row || !isStateRow(state, key)) { return null; }
        var band = text(row.age_group);
        return band && band !== 'unknown' ? band : null;
    }

    function loraById(state) {
        var index = {};
        arrayOf(state.catalogues && state.catalogues.lora).forEach(function (model) {
            if (model && model.id) { index[model.id] = model; }
        });
        return index;
    }

    /* ------------------------------------------------------------------ */
    /* THE PAYLOAD BUILDER                                                 */
    /* ------------------------------------------------------------------ */

    function buildTypeFields(state, type, working) {
        var models = loraById(state);
        if (type === 'ensemble') {
            return { type: 'ensemble', members: arrayOf(working.members).slice(), seed: '-1' };
        }
        /* `description` is the persona text generate_personas.py writes, and
         * `character_style` mirrors it for the Voice Design path. Both are in
         * FORM_OWNED_KEYS, so `preservedMetadata` strips them from the stored
         * entry and every type branch must re-emit the ones that apply to it -
         * otherwise a save from this tab silently deletes the persona that was
         * just generated. `design` already carries both; `custom` and `clone`
         * did not, and a persona voice is stored as `clone`. */
        var persona = {
            description: text(working.description),
            character_style: text(working.character_style)
        };
        if (type === 'custom') {
            return { type: 'custom', voice: text(working.voice),
                character_style: persona.character_style, description: persona.description, seed: '-1' };
        }
        if (type === 'clone') {
            return { type: 'clone', ref_text: text(working.ref_text), ref_audio: text(working.ref_audio),
                description: persona.description, character_style: persona.character_style, seed: '-1' };
        }
        if (type === 'builtin_lora') {
            var builtinId = text(working.adapter_id);
            var builtinEntry = models[builtinId];
            return {
                type: 'builtin_lora',
                adapter_id: builtinId,
                adapter_path: (builtinEntry && (builtinEntry.adapter_path || builtinEntry.path)) || '',
                character_style: text(working.character_style),
                seed: '-1'
            };
        }
        if (type === 'lora') {
            var loraId = text(working.adapter_id);
            var loraEntry = models[loraId];
            return {
                type: 'lora',
                adapter_id: loraId,
                adapter_path: (loraEntry && loraEntry.adapter_path) || (loraId ? 'lora_models/' + loraId : ''),
                character_style: text(working.character_style),
                seed: '-1'
            };
        }
        return { type: 'design', description: text(working.description), seed: '-1' };
    }

    /* The stored entry minus every field the form owns. */
    function preservedMetadata(stored) {
        var preserved = Object.assign({}, stored);
        for (var index = 0; index < FORM_OWNED_KEYS.length; index += 1) {
            delete preserved[FORM_OWNED_KEYS[index]];
        }
        return preserved;
    }

    function buildEntry(state, name) {
        var stored = storedConfig(state, name);
        var working = workingOf(state, name);
        var type = text(working.type) || text(stored.type) || 'custom';

        var merged = preservedMetadata(stored);
        var formFields = buildTypeFields(state, type, working);
        Object.assign(merged, formFields);

        // The form only ever sets these when they carry a value, matching the
        // original tab: an unchecked "Ready" leaves the field absent rather than
        // writing false.
        if (working.alias_of) { merged.alias_of = working.alias_of; }
        if (working.ready) { merged.ready = true; }

        // The seed is server-owned. The form never exposes it, so a stored seed
        // always wins; only an entry that never had one falls back to the
        // placeholder the type branch produced.
        merged.seed = String(stored.seed !== undefined && stored.seed !== null ? stored.seed : formFields.seed);
        return merged;
    }

    /* Does this entry represent an actual voice, or is it an empty row?
     *
     * Mirrors `voice_is_set` in tts.py, so the roster agrees with the server
     * about who is assigned. Any non-custom type counts: a LoRA adapter id or a
     * reference audio is a voice whatever else is missing. A custom entry only
     * counts once it names a voice or carries a persona, because the bare
     * `{type:'custom', voice:''}` the form produces for an untouched row is not
     * one. */
    function isAssignedEntry(entry) {
        if (!entry || typeof entry !== 'object') { return false; }
        var type = text(entry.type) || 'custom';
        if (type !== 'custom') { return true; }
        return Boolean(text(entry.voice) || text(entry.description)
            || text(entry.ref_audio) || text(entry.character_style));
    }

    /* The save map, keyed by CHARACTER, not by row.
     *
     * State rows do not become top-level entries. Their fields are written into
     * the character's `versions` under their age band, which is exactly where
     * generate_personas.py already puts a state persona, so the two agree.
     *
     * `_apply_voice_save` merges each character with a SHALLOW dict update:
     *
     *     updated[name] = {**existing, **config}
     *
     * and VoiceConfigItem.versions is a plain dict. A payload carrying `versions`
     * therefore REPLACES the whole versions dict rather than merging into it, so
     * a state save that emitted only the edited version would silently destroy
     * its siblings. Every version is therefore rebuilt here: the stored ones,
     * with this row's fields layered over its own band.
     *
     * A band with no voice contributes NOTHING. An unassigned state row is
     * rendered empty rather than falling back to the character's base config
     * (which is usually the `Aiden` placeholder), so emitting
     * `{type:'custom', voice:'', seed:'-1'}` for it would put a fabricated
     * version on disk: `has_version` would flip to true in the projection and
     * the row would then render as assigned with no voice at all. */
    function buildVoiceDocument(state) {
        var roster = rosterOf(state);
        var document_ = {};
        var versions = {};
        var seeded = {};

        roster.names.forEach(function (key) {
            var speaker = speakerOf(state, key);
            if (!speaker) { return; }
            var band = stateAgeGroup(state, key);

            if (!band) {
                document_[speaker] = buildEntry(state, key);
                return;
            }
            if (!versions[speaker]) { versions[speaker] = {}; }
            /* Seed from the server's versions ONCE per character, before any row
             * writes. Doing it per row would let a later row's copy of the stale
             * stored values overwrite an EARLIER row's edit - two state rows saved
             * together would silently lose the first one. */
            if (!seeded[speaker]) {
                seeded[speaker] = true;
                var base = baseConfigOf(state, key);
                var existing = base && typeof base.versions === 'object' ? base.versions : {};
                Object.keys(existing).forEach(function (versionId) {
                    versions[speaker][versionId] = existing[versionId];
                });
            }
            var entry = buildEntry(state, key);
            if (isAssignedEntry(entry)) {
                versions[speaker][band] = entry;
            } else {
                /* No voice on this band. Dropping it also covers the user
                 * deliberately clearing one that existed, rather than leaving a
                 * version that claims a voice it does not have. */
                delete versions[speaker][band];
            }
        });

        Object.keys(versions).forEach(function (speaker) {
            if (!document_[speaker]) {
                document_[speaker] = Object.assign({}, baseConfigOfFirstRow(state, speaker));
            }
            document_[speaker].versions = versions[speaker];
        });
        return document_;
    }

    /* The character's own entry, which the projection attaches to a state row
     * because state rows replace that row and nothing else would carry it. */
    function baseConfigOf(state, key) {
        var row = rowOf(state, key);
        var base = row && row.base_config;
        return base && typeof base === 'object' ? base : {};
    }

    function baseConfigOfFirstRow(state, speaker) {
        var byName = rosterOf(state).byName;
        var keys = Object.keys(byName);
        for (var index = 0; index < keys.length; index += 1) {
            var row = byName[keys[index]];
            if ((row.speaker || row.name) !== speaker) { continue; }
            if (row.base_config && typeof row.base_config === 'object') {
                return row.base_config;
            }
            if (row.config && typeof row.config === 'object') { return row.config; }
        }
        return {};
    }

    /* ------------------------------------------------------------------ */
    /* roster derivations                                                  */
    /* ------------------------------------------------------------------ */

    /* Per-book spoken-line counts arrive on the voice library's
     * `current_characters`, not on the roster row. They are the "N lines" badge
     * on every card and the priority signal behind it. */
    function lineCounts(state) {
        var counts = {};
        var library = (state.cast && state.cast.library) || {};
        arrayOf(library.current_characters).forEach(function (character) {
            if (character && character.name) { counts[character.name] = character.line_count; }
        });
        return counts;
    }

    /* One view-model row per roster row, carrying BOTH identities so no consumer
     * has to guess which one it needs:
       key      "MARO#adult"  identity in the store, the DOM and the save map
       speaker  "MARO"        identity in voice_config.json and in every API path
       name     "MARO"        what the card displays, and what the line count and
                              the trait badge are looked up by
     *
     * `ageGroup` and `isState` are what make a state row render differently, and
     * `lineCount` deliberately keys off `name`, so three MARO rows each show the
     * character's full line count rather than a third of it. */
    function selectRosterRows(state) {
        var roster = rosterOf(state);
        var counts = lineCounts(state);
        return roster.names.map(function (key) {
            var entry = roster.byName[key] || {};
            var displayName = entry.name || entry.speaker || key;
            var isState = key !== (entry.speaker || displayName);
            return {
                key: key,
                speaker: entry.speaker || displayName,
                name: displayName,
                isState: isState,
                ageGroup: isState ? (text(entry.age_group) || '') : '',
                hasVersion: !!entry.has_version,
                fromEntry: entry.from_entry != null ? entry.from_entry : null,
                toEntry: entry.to_entry != null ? entry.to_entry : null,
                config: entry.config || {},
                traits: entry.traits || null,
                personaPending: !!entry.persona_pending,
                lineCount: counts[displayName] != null ? counts[displayName] : null
            };
        });
    }

    /* The original tab's only filter is "hide ready", applied as a display rule
     * rather than removing rows. Ready count therefore reports over the whole
     * roster, matching `#voices-ready-count`. */
    function selectVisibleRows(state) {
        var rows = selectRosterRows(state);
        if (!state.view.hideReady) { return rows; }
        return rows.filter(function (row) { return !row.config.ready; });
    }

    function selectReadySummary(state) {
        var rows = selectRosterRows(state);
        var ready = rows.filter(function (row) { return !!row.config.ready; }).length;
        return { ready: ready, total: rows.length, label: rows.length ? ready + ' / ' + rows.length + ' ready' : '' };
    }

    /* Scope: `pending` = no persona yet, `have` = a persona exists. Mirrors the
     * original `_voicesScopeState`. */
    function selectScopeSummary(state) {
        var rows = selectRosterRows(state);
        var pending = rows.filter(function (row) { return row.personaPending; }).map(function (row) { return row.name; });
        var have = rows.filter(function (row) { return !row.personaPending; }).map(function (row) { return row.name; });
        return { pending: pending, have: have };
    }

    function selectScopeIsNew(state) {
        return state.view.scope === 'new';
    }

    function selectScopeOptions(state) {
        var summary = selectScopeSummary(state);
        return {
            pending: 'Only characters without a voice yet (' + summary.pending.length + ')',
            all: 'All characters (regenerate ' + (summary.have.length + summary.pending.length) + ')',
            showKeepCheckbox: selectScopeIsNew(state) === false && summary.have.length > 0,
            keepLabel: 'cast: ' + (state.cast.selected || state.meta.bookId || 'current book')
        };
    }

    /* The original only auto-choses a scope when both groups are non-empty and
     * the user has not chosen. `scopeUserSet` carries that decision. */
    function resolveScope(state) {
        if (state.view.scopeUserSet) { return state.view.scope; }
        var summary = selectScopeSummary(state);
        return (summary.pending.length >= 1 && summary.have.length >= 1) ? 'new' : 'all';
    }

    /* ------------------------------------------------------------------ */
    /* per-character derivations                                           */
    /* ------------------------------------------------------------------ */

    /* Look a row up by its KEY, not its display name: three MARO rows share a name. */
    function selectRow(state, key) {
        var rows = selectRosterRows(state);
        for (var index = 0; index < rows.length; index += 1) {
            if (rows[index].key === key) { return rows[index]; }
        }
        return null;
    }

    function selectType(state, name) {
        var working = workingOf(state, name);
        return text(working.type) || text(storedConfig(state, name).type) || 'custom';
    }

    function selectAliasOptions(state, name) {
        return rosterOf(state).names.filter(function (candidate) { return candidate !== name; });
    }

    function selectVersions(state, name) {
        var versions = storedConfig(state, name).versions;
        var active = storedConfig(state, name).active_version;
        if (!versions || typeof versions !== 'object') { return { options: [], active: null }; }
        var options = Object.keys(versions).map(function (id) {
            var version = versions[id] || {};
            return { id: id, ageGroup: version.age_group || '', active: id === active };
        });
        return { options: options, active: active || null };
    }

    function selectCandidates(state, name) {
        return arrayOf(storedConfig(state, name).candidates).filter(function (candidate) {
            return candidate && typeof candidate === 'object';
        });
    }

    function selectStylePoints(state, name) {
        return arrayOf(storedConfig(state, name).style_timeline).filter(function (point) {
            return point && typeof point === 'object' && typeof point.from_index === 'number';
        });
    }

    function selectStatePanel(state, name) {
        return state.states && state.states[name]
            ? state.states[name]
            : { loading: false, loaded: false, rows: [], offerGenerate: false, saving: false, error: '', notice: '' };
    }

    function selectSuggestionsFor(state, name) {
        return arrayOf(state.suggestions && state.suggestions.byName && state.suggestions.byName[name]);
    }

    function selectSuggestionTotal(state) {
        var byName = (state.suggestions && state.suggestions.byName) || {};
        var total = 0;
        Object.keys(byName).forEach(function (name) { total += arrayOf(byName[name]).length; });
        return total;
    }

    /* `traits` come from the roster row. The badge is model-inferred text, so
     * every value is escaped at render time and never trusted as markup. */
    function selectTraitBadge(traits) {
        if (!traits) { return null; }
        function label(value) {
            return [value && value.gender, value && value.age_group]
                .filter(function (part) { return part && part !== 'unknown'; })
                .map(function (part) { return String(part).replace('_', ' '); })
                .join(' · ');
        }
        var states = arrayOf(traits.states).map(label).filter(function (part) { return !!part; });
        var summary = states.length ? states.join(' → ') : label(traits);
        if (!summary && !traits.ageless) { return null; }
        return {
            summary: [summary, traits.ageless ? 'ageless' : ''].filter(Boolean).join(' · '),
            lines: Number(traits.lines) || 0
        };
    }

    function selectTraitStateCount(traits) {
        return traits ? arrayOf(traits.states).length : 0;
    }

    /* ------------------------------------------------------------------ */
    /* catalogue derivations                                               */
    /* ------------------------------------------------------------------ */

    function selectLoraModels(state) {
        return arrayOf(state.catalogues && state.catalogues.lora);
    }

    function selectUserLoraModels(state) {
        return selectLoraModels(state).filter(function (model) { return !model.builtin; });
    }

    function selectBuiltinLoraGroups(state) {
        var builtin = selectLoraModels(state).filter(function (model) { return !!model.builtin; });
        return {
            male: builtin.filter(function (model) { return model.gender === 'male'; }),
            female: builtin.filter(function (model) { return model.gender === 'female'; })
        };
    }

    function selectCloneVoices(state) {
        return arrayOf(state.catalogues && state.catalogues.clone);
    }

    function selectDesignedVoices(state) {
        return arrayOf(state.catalogues && state.catalogues.designed);
    }

    /* Reverse-map a stored `ref_audio` path back to the catalogue row that owns
     * it. Matched on path rather than display name, because the configuration
     * stores a path and two designs can share a name. */
    function selectLibraryReference(state, refAudio) {
        var path = String(refAudio || '').replace(/\\/g, '/').replace(/^(?:\.\/)+/, '');
        if (!path) { return null; }
        var groups = [
            { type: 'clone', directory: 'clone_voices', voices: selectCloneVoices(state) },
            { type: 'design', directory: 'designed_voices', voices: selectDesignedVoices(state) }
        ];
        for (var index = 0; index < groups.length; index += 1) {
            var group = groups[index];
            for (var voiceIndex = 0; voiceIndex < group.voices.length; voiceIndex += 1) {
                var voice = group.voices[voiceIndex] || {};
                if (path === group.directory + '/' + voice.filename) {
                    return { type: group.type, id: voice.id || '', name: voice.name || '' };
                }
            }
        }
        return null;
    }

    function selectCustomVoiceOptions(state, name) {
        var available = arrayOf(namespace.labels && namespace.labels.AVAILABLE_VOICES) || [];
        var stored = text(storedConfig(state, name).voice);
        if (stored && available.indexOf(stored) < 0) {
            return [stored].concat(available);
        }
        return available;
    }

    /* Compound-name ensemble suggestion: keep the parts that are real characters.
     * Prefills only; it never overrides a saved choice. */
    function selectEnsembleSuggestions(state, name) {
        var known = rosterOf(state).names;
        var parts = String(name || '').split(/\s+and\s+|\s*\/\s*/);
        var found = [];
        parts.forEach(function (part) {
            var candidate = part.trim();
            if (!candidate || candidate === name) { return; }
            var match = known.find(function (knownName) {
                return knownName === candidate || knownName.replace(/\s+/g, '') === candidate.replace(/\s+/g, '');
            });
            if (match && found.indexOf(match) < 0) { found.push(match); }
        });
        return found;
    }

    /* ------------------------------------------------------------------ */
    /* narrator                                                            */
    /* ------------------------------------------------------------------ */

    function selectNarratorRow(state) {
        var rows = selectRosterRows(state);
        var narrator = rows.find(function (row) { return row.name === 'NARRATOR'; })
            || rows.find(function (row) { return row.name === 'Narrator'; });
        return narrator || null;
    }

    function selectNarratorStrategy(state) {
        var narrator = selectNarratorRow(state);
        return narrator ? text(narrator.config.narrator_strategy) || 'global' : 'global';
    }

    /* Preview focus and preview version exist to let a user check a selection
     * without changing anything. They never alter stored state. */
    function selectNarratorPreviewControls(state) {
        var narrator = selectNarratorRow(state);
        var config = narrator ? narrator.config : {};
        var focus = [];
        var version = [];

        var all = rosterOf(state).names.filter(function (name) { return name !== 'NARRATOR' && name !== 'Narrator'; });
        var traitBearing = all.filter(function (name) {
            var row = selectRow(state, name);
            return !!(row && row.traits && (row.traits.current || row.traits.gender || row.traits.age_group));
        });
        if (traitBearing.length) { focus.push({ value: '', label: 'Any character' }); }
        (traitBearing.length ? traitBearing : all).forEach(function (name) {
            focus.push({ value: name, label: name });
        });

        var versions = (config.versions && typeof config.versions === 'object') ? config.versions : {};
        version.push({ value: '', label: 'Main narrator voice' });
        Object.keys(versions).forEach(function (id) {
            version.push({ value: id, label: id + ((versions[id] && versions[id].age_group) ? ' · ' + versions[id].age_group : '') });
        });
        return { focus: focus, version: version };
    }

    /* ------------------------------------------------------------------ */
    /* cast                                                                */
    /* ------------------------------------------------------------------ */

    function selectCasts(state) {
        return arrayOf(state.cast && state.cast.library && state.cast.library.casts);
    }

    function selectSelectedCast(state) {
        var name = text(state.cast && state.cast.selected);
        if (!name) { return null; }
        return selectCasts(state).find(function (cast) { return cast && cast.name === name; }) || null;
    }

    function selectCastMembers(state) {
        var library = (state.cast && state.cast.library) || {};
        var name = text(state.cast && state.cast.selected);
        if (!name) { return arrayOf(library.shared).concat(arrayOf(library.current_characters)); }
        var cast = selectCasts(state).find(function (entry) { return entry && entry.name === name; });
        if (!cast) { return []; }
        var members = (cast.members && typeof cast.members === 'object') ? cast.members : cast;
        return Object.keys(members).map(function (key) {
            return Object.assign({ key: key }, members[key]);
        });
    }

    namespace.selectors = {
        FORM_OWNED_KEYS: FORM_OWNED_KEYS,
        clone: clone,
        text: text,
        arrayOf: arrayOf,
        storedConfig: storedConfig,
        workingOf: workingOf,
        rowOf: rowOf,
        speakerOf: speakerOf,
        isStateRow: isStateRow,
    isAssignedEntry: isAssignedEntry,
        stateAgeGroup: stateAgeGroup,
        loraById: loraById,
        buildTypeFields: buildTypeFields,
        preservedMetadata: preservedMetadata,
        buildEntry: buildEntry,
        buildVoiceDocument: buildVoiceDocument,
        lineCounts: lineCounts,
        selectRosterRows: selectRosterRows,
        selectVisibleRows: selectVisibleRows,
        selectReadySummary: selectReadySummary,
        selectScopeSummary: selectScopeSummary,
        selectScopeIsNew: selectScopeIsNew,
        selectScopeOptions: selectScopeOptions,
        resolveScope: resolveScope,
        selectRow: selectRow,
        selectType: selectType,
        selectAliasOptions: selectAliasOptions,
        selectVersions: selectVersions,
        selectCandidates: selectCandidates,
        selectStylePoints: selectStylePoints,
        selectStatePanel: selectStatePanel,
        selectSuggestionsFor: selectSuggestionsFor,
        selectSuggestionTotal: selectSuggestionTotal,
        selectTraitBadge: selectTraitBadge,
        selectTraitStateCount: selectTraitStateCount,
        selectLoraModels: selectLoraModels,
        selectUserLoraModels: selectUserLoraModels,
        selectBuiltinLoraGroups: selectBuiltinLoraGroups,
        selectCloneVoices: selectCloneVoices,
        selectDesignedVoices: selectDesignedVoices,
        selectLibraryReference: selectLibraryReference,
        selectCustomVoiceOptions: selectCustomVoiceOptions,
        selectEnsembleSuggestions: selectEnsembleSuggestions,
        selectNarratorRow: selectNarratorRow,
        selectNarratorStrategy: selectNarratorStrategy,
        selectNarratorPreviewControls: selectNarratorPreviewControls,
        selectCasts: selectCasts,
        selectSelectedCast: selectSelectedCast,
        selectCastMembers: selectCastMembers
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));
