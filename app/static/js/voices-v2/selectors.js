/* Voices V2 — selectors: the pure layer between the store and the panels.
 *
 * Everything here is a pure function of its arguments. No DOM, no store writes,
 * no mutation of the arrays that come out of the projection. That is what makes
 * the browser cheap: one request produces the projection, and every view the user
 * can reach is a recomputation over that same array.
 *
 * Two exported groups:
 *
 *   adaptProjection(payload)  the one wire-shape -> store-shape conversion, made
 *                             total so a malformed row yields an empty field
 *                             instead of `undefined` reaching the UI.
 *   select*(state)            the derived reads the panels render from.
 *
 * Search is multi-term AND. Typing "mira teo" finds a character whose name is
 * MIRA and whose alias is TEO, which single-substring matching cannot do, and
 * which a user comparing a book against a fan wiki actually needs.
 */
(function (namespace) {
    'use strict';

    var store = namespace.state;

    function text(value) {
        return typeof value === 'string' ? value : '';
    }

    function boolOr(value, fallback) {
        return typeof value === 'boolean' ? value : !!fallback;
    }

    function arrayOf(value) {
        return Array.isArray(value) ? value : [];
    }

    function numberOrNull(value) {
        return typeof value === 'number' && isFinite(value) ? value : null;
    }

    /* ---------------------------------------------------------------- *
     * Wire shape -> store shape
     * ---------------------------------------------------------------- */

    function adaptVoice(voice) {
        var source = (voice && typeof voice === 'object') ? voice : {};
        return {
            category: text(source.category) || 'custom',
            /* The stored type verbatim, and which catalogue row it names when it
             * names one. Both are null-able on purpose: a configuration can hold
             * a voice the catalogue does not have, and the editor says so
             * instead of showing a selector that disagrees with storage. */
            type: typeof source.type === 'string' ? source.type : null,
            catalogueVoiceId: typeof source.catalogue_voice_id === 'string'
                ? source.catalogue_voice_id : null,
            label: text(source.label) || 'Unknown voice',
            assigned: boolOr(source.assigned, false),
            adapterId: typeof source.adapter_id === 'string' ? source.adapter_id : null,
            adapterAvailable: boolOr(source.adapter_available, null),
            hasRefAudio: boolOr(source.has_ref_audio, false),
            refAudioPresent: boolOr(source.ref_audio_present, null),
            hasDescription: boolOr(source.has_description, false),
            seed: (typeof source.seed === 'string' || typeof source.seed === 'number')
                ? source.seed : null,
            aliasOf: typeof source.alias_of === 'string' ? source.alias_of : null,
            ensembleMembers: numberOrNull(source.ensemble_members) || 0
        };
    }

    function adaptTraits(traits) {
        if (!traits || typeof traits !== 'object') { return null; }
        var current = (traits.current && typeof traits.current === 'object') ? traits.current : {};
        return {
            gender: text(traits.gender) || 'unknown',
            ageGroup: text(traits.age_group) || 'unknown',
            ageless: boolOr(traits.ageless, false),
            lines: numberOrNull(traits.lines) || 0,
            current: {
                gender: text(current.gender) || 'unknown',
                ageGroup: text(current.age_group) || 'unknown'
            },
            states: arrayOf(traits.states).map(function (state) {
                return {
                    gender: text(state && state.gender) || 'unknown',
                    ageGroup: text(state && state.age_group) || 'unknown'
                };
            })
        };
    }

    function adaptCharacter(raw) {
        var source = (raw && typeof raw === 'object') ? raw : {};
        var name = text(source.name);
        return {
            /* `key` is the selection identity. The backend derives it from the
             * stored name, never from a list position, so a re-sorted or
             * re-filtered list keeps the same selection. */
            key: text(source.key) || ('name:' + name),
            name: name,
            identityKey: text(source.identity_key),
            libraryKey: typeof source.library_key === 'string' ? source.library_key : null,
            presentInScript: boolOr(source.present_in_script, false),
            generic: boolOr(source.generic, false),
            lineCount: numberOrNull(source.line_count) || 0,
            priority: typeof source.priority === 'string' ? source.priority : null,
            knownAs: arrayOf(source.known_as).filter(function (label) {
                return typeof label === 'string' && label.trim();
            }),
            aliases: arrayOf(source.aliases).filter(function (label) {
                return typeof label === 'string' && label.trim();
            }),
            voice: adaptVoice(source.voice),
            voiceStatus: typeof source.voice_status === 'string' ? source.voice_status : null,
            personaStatus: typeof source.persona_status === 'string' ? source.persona_status : null,
            ready: boolOr(source.ready, false),
            personaRef: typeof source.persona_ref === 'string' ? source.persona_ref : null,
            personaRefResolves: boolOr(source.persona_ref_resolves, null),
            activeVersion: typeof source.active_version === 'string' ? source.active_version : null,
            versions: arrayOf(source.versions).map(function (version) {
                var entry = (version && typeof version === 'object') ? version : {};
                return {
                    versionId: text(entry.version_id),
                    ageGroup: typeof entry.age_group === 'string' ? entry.age_group : null,
                    category: text(entry.category) || 'custom',
                    label: text(entry.label) || 'Unknown voice',
                    adapterId: typeof entry.adapter_id === 'string' ? entry.adapter_id : null
                };
            }),
            versionTimeline: arrayOf(source.version_timeline).map(function (point) {
                var entry = (point && typeof point === 'object') ? point : {};
                return {
                    fromIndex: numberOrNull(entry.from_index),
                    versionId: typeof entry.version_id === 'string' ? entry.version_id : null
                };
            }),
            candidateCount: numberOrNull(source.candidate_count) || 0,
            traits: adaptTraits(source.traits),
            traitsAvailable: boolOr(source.traits_available, false),
            states: arrayOf(source.states).map(function (state) {
                var entry = (state && typeof state === 'object') ? state : {};
                return {
                    fromEntry: numberOrNull(entry.from_entry),
                    gender: text(entry.gender) || 'unknown',
                    ageGroup: text(entry.age_group) || 'unknown'
                };
            }),
            possibleDuplicateOf: arrayOf(source.possible_duplicate_of).filter(function (label) {
                return typeof label === 'string' && label.trim();
            }),
            problems: arrayOf(source.problems).filter(function (code) {
                return typeof code === 'string' && code.trim();
            })
        };
    }

    function adaptVocabularies(raw) {
        var source = (raw && typeof raw === 'object') ? raw : {};
        return {
            genders: arrayOf(source.genders).filter(function (value) {
                return typeof value === 'string';
            }),
            ageGroups: arrayOf(source.age_groups).map(function (group) {
                var entry = (group && typeof group === 'object') ? group : {};
                return { value: text(entry.value), label: text(entry.label) };
            }).filter(function (group) {
                return group.value;
            }),
            problemCodes: arrayOf(source.problem_codes).filter(function (code) {
                return typeof code === 'string';
            })
        };
    }

    function adaptProjection(payload) {
        var source = (payload && typeof payload === 'object') ? payload : {};
        var book = (source.book && typeof source.book === 'object') ? source.book : {};
        return {
            meta: {
                schemaVersion: numberOrNull(source.schema_version),
                /* The guarded save contract's first half. Held from the first read,
                 * because a save that cannot prove which snapshot it was based on
                 * can silently overwrite newer configuration. */
                revision: typeof source.revision === 'string' ? source.revision : null,
                book: {
                    bookId: typeof book.book_id === 'string' ? book.book_id : null,
                    token: typeof book.token === 'string' ? book.token : null,
                    scriptSha256: typeof book.script_sha256 === 'string' ? book.script_sha256 : null,
                    scriptPresent: boolOr(book.script_present, false)
                },
                /* Book-level, so the toolbar can disable the trait filters and say
                 * why, instead of offering a filter that silently matches nobody. */
                traitsAvailable: boolOr(source.traits_available, false),
                traitsRequested: boolOr(source.traits_requested, null),
                aliasesRegistered: boolOr(source.aliases_registered, false),
                majorLineThreshold: numberOrNull(source.major_line_threshold),
                vocabularies: adaptVocabularies(source.vocabularies)
            },
            characters: arrayOf(source.characters).map(adaptCharacter),
            orphans: arrayOf(source.orphans).map(adaptCharacter)
        };
    }

    /* One catalogue row, adapted from the wire shape to the shape the library
     * filters and sorts on.
     *
     * The whole VoiceRecord is mapped, not just the fields Phase 2 needed. A
     * partial map would silently drop `gender_source`, `preview_url` and the
     * rest, and the library would then filter and render against `undefined`
     * while looking like it was working - which is exactly the failure the
     * provenance fields exist to prevent.
     */
    function adaptCatalogueVoice(raw) {
        var entry = (raw && typeof raw === 'object') ? raw : {};
        return {
            voiceId: text(entry.voice_id),
            nativeId: text(entry.native_id),
            kind: text(entry.kind),
            name: text(entry.name),
            label: text(entry.label) || text(entry.name) || 'Unnamed voice',
            source: text(entry.source) || text(entry.kind),
            realisation: text(entry.realisation),
            description: typeof entry.description === 'string' ? entry.description : null,
            sampleText: typeof entry.sample_text === 'string' ? entry.sample_text : null,
            // Value plus provenance, both kept. A guess that reads as a fact is
            // the failure this pairing prevents.
            gender: text(entry.gender) || 'unknown',
            genderSource: text(entry.gender_source) || 'unknown',
            ageGroup: text(entry.age_group) || 'unknown',
            ageGroupSource: text(entry.age_group_source) || 'unknown',
            ageless: boolOr(entry.ageless, false),
            addedAt: numberOrNull(entry.added_at),
            availability: text(entry.availability)
                || (entry.available ? 'available' : 'unavailable'),
            available: boolOr(entry.available, false),
            unavailableReason: text(entry.unavailable_reason) || '',
            downloaded: boolOr(entry.downloaded, true),
            favorite: boolOr(entry.favorite, false),
            favoriteSupported: boolOr(entry.favorite_supported, false),
            adapterId: typeof entry.adapter_id === 'string' ? entry.adapter_id : null,
            adapterPath: typeof entry.adapter_path === 'string' ? entry.adapter_path : null,
            refAudio: typeof entry.ref_audio === 'string' ? entry.ref_audio : null,
            refText: typeof entry.ref_text === 'string' ? entry.ref_text : null,
            previewCapable: boolOr(entry.preview_capable, false),
            previewUrl: typeof entry.preview_url === 'string' ? entry.preview_url : null,
            previewKind: typeof entry.preview_kind === 'string' ? entry.preview_kind : null,
            // Generated-preview state, kept apart from `available`: a voice with
            // no preview yet is still perfectly assignable.
            previewState: text(entry.preview_state) || 'none',
            previewGeneratable: boolOr(entry.preview_generatable, false),
            previewJobId: typeof entry.preview_job_id === 'string'
                ? entry.preview_job_id : null,
            tags: arrayOf(entry.tags).filter(function (tag) {
                return typeof tag === 'string' && tag.trim();
            }),
            metadata: (entry.metadata && typeof entry.metadata === 'object'
                && !Array.isArray(entry.metadata)) ? entry.metadata : {}
        };
    }

    function adaptCatalogue(raw) {
        var source = (raw && typeof raw === 'object') ? raw : {};
        var counts = (source.counts && typeof source.counts === 'object') ? source.counts : {};
        var unsupported = (source.unsupported_kinds && typeof source.unsupported_kinds === 'object')
            ? source.unsupported_kinds : {};
        return {
            voices: arrayOf(source.voices).map(adaptCatalogueVoice),
            counts: {
                total: numberOrNull(counts.total) || 0,
                available: numberOrNull(counts.available) || 0,
                unavailable: numberOrNull(counts.unavailable) || 0
            },
            kinds: arrayOf(source.kinds).filter(function (kind) {
                return typeof kind === 'string';
            }),
            favoriteKinds: arrayOf(source.favorite_kinds).filter(function (kind) {
                return typeof kind === 'string';
            }),
            warnings: arrayOf(source.warnings).filter(function (warning) {
                return typeof warning === 'string' && warning.trim();
            }),
            unsupportedKinds: unsupported,
            schemaVersion: numberOrNull(source.schema_version)
        };
    }

    /* ---------------------------------------------------------------- *
     * Derived reads
     * ---------------------------------------------------------------- */

    function searchTerms(query) {
        return text(query).toLowerCase().split(/\s+/).filter(function (term) {
            return term.length > 0;
        });
    }

    /* Everything a user might reasonably search a character by. Voice label and
     * adapter id are included on purpose: "find everyone using the same LoRA"
     * is a real question, and the detail view then shows who they are. */
    function searchHaystack(character) {
        return [
            character.name,
            character.identityKey,
            character.libraryKey,
            character.voice.label,
            character.voice.adapterId,
            character.voice.aliasOf
        ].concat(character.knownAs, character.aliases)
            .filter(Boolean)
            .join(' ')
            .toLowerCase();
    }

    function matchesQuery(character, terms) {
        if (!terms.length) { return true; }
        var haystack = searchHaystack(character);
        return terms.every(function (term) {
            return haystack.indexOf(term) >= 0;
        });
    }

    /* Traits are unavailable for a book generated without per-line speaker
     * traits. Returning true here means a stale gender filter cannot hide every
     * character; the toolbar disables the control and explains why, which is the
     * honest presentation. */
    function matchesTraits(character, filters, traitsAvailable) {
        if (!traitsAvailable) { return true; }
        if (filters.gender !== 'all') {
            if (filters.gender === 'unavailable') {
                if (character.traits) { return false; }
            } else if (!character.traits || character.traits.gender !== filters.gender) {
                return false;
            }
        }
        if (filters.ageGroup !== 'all') {
            if (filters.ageGroup === 'unavailable') {
                if (character.traits) { return false; }
            } else if (!character.traits || character.traits.ageGroup !== filters.ageGroup) {
                return false;
            }
        }
        return true;
    }

    function matchesFilters(character, filters, traitsAvailable) {
        if (filters.assigned === 'yes' && !character.voice.assigned) { return false; }
        if (filters.assigned === 'no' && character.voice.assigned) { return false; }
        if (filters.ready === 'yes' && !character.ready) { return false; }
        if (filters.ready === 'no' && character.ready) { return false; }

        if (filters.priority === 'none') {
            if (character.priority !== null) { return false; }
        } else if (filters.priority !== 'all' && character.priority !== filters.priority) {
            return false;
        }

        if (filters.personaStatus !== 'all') {
            var persona = character.personaStatus || 'none';
            if (persona !== filters.personaStatus) { return false; }
        }

        if (filters.problems === 'flagged' && !character.problems.length) { return false; }
        if (filters.problems === 'clean' && character.problems.length) { return false; }

        return matchesTraits(character, filters, traitsAvailable);
    }

    function scopeRecords(state) {
        var scope = (state.filters && state.filters.scope) || 'all';
        if (scope === 'characters') { return state.characters; }
        if (scope === 'orphans') { return state.orphans; }
        return state.characters.concat(state.orphans);
    }

    var TRAIT_ORDER = ['infant', 'toddler', 'young_child', 'child', 'teen', 'young_adult',
        'adult', 'middle_aged', 'elderly', 'unknown'];
    var PRIORITY_ORDER = ['major', 'minor', null];

    function rank(value, order) {
        var index = order.indexOf(value);
        return index < 0 ? order.length : index;
    }

    /* Comparators return a number and never touch the array they are handed, so
     * sorting a view cannot reorder the stored projection. */
    var COMPARATORS = {
        name: function (left, right) {
            return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
        },
        lineCount: function (left, right) {
            return (left.lineCount || 0) - (right.lineCount || 0);
        },
        priority: function (left, right) {
            return rank(left.priority, PRIORITY_ORDER) - rank(right.priority, PRIORITY_ORDER);
        },
        voiceStatus: function (left, right) {
            /* Unassigned first ascending: a character with no voice is the thing a
             * user opens this browser to find. */
            var a = left.voice.assigned ? 1 : 0;
            var b = right.voice.assigned ? 1 : 0;
            if (a !== b) { return a - b; }
            return left.voice.label.localeCompare(right.voice.label);
        },
        voice: function (left, right) {
            var a = left.voice.assigned ? 1 : 0;
            var b = right.voice.assigned ? 1 : 0;
            if (a !== b) { return a - b; }
            return left.voice.category.localeCompare(right.voice.category) ||
                left.voice.label.localeCompare(right.voice.label);
        },
        ready: function (left, right) {
            /* Ascending puts Ready first, matching `priority` (major first) and
             * giving each axis one predictable direction. */
            var a = left.ready ? 0 : 1;
            var b = right.ready ? 0 : 1;
            if (a !== b) { return a - b; }
            return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
        }
    };

    /* Trait order is used by the `traitOrder` sort rather than exposing the
     * vocabulary as a sort option, because "oldest to youngest" is the only
     * meaningful direction and the list already defines it. */
    function traitComparator(left, right) {
        var a = left.traits ? TRAIT_ORDER.indexOf(left.traits.ageGroup) : -1;
        var b = right.traits ? TRAIT_ORDER.indexOf(right.traits.ageGroup) : -1;
        if (a < 0) { a = TRAIT_ORDER.length; }
        if (b < 0) { b = TRAIT_ORDER.length; }
        if (a !== b) { return a - b; }
        return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
    }

    function sortRecords(records, sort) {
        var requested = sort ? sort.key : 'name';
        var comparator = COMPARATORS[requested] || traitComparator;
        /* slice() first: sort() mutates, and the argument may be a store array. */
        return records.slice().sort(function (left, right) {
            var result = comparator(left, right);
            if (result !== 0) {
                return sort && sort.direction === 'desc' ? -result : result;
            }
            return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
        });
    }

    /* Everything the toolbar needs to describe the current result set. */
    function selectSummary(state) {
        var scoped = scopeRecords(state);
        var terms = searchTerms(state.filters.query);
        var traitsAvailable = state.meta.traitsAvailable;
        var matched = scoped.filter(function (character) {
            return matchesQuery(character, terms) &&
                matchesFilters(character, state.filters, traitsAvailable);
        });
        var flagged = 0;
        matched.forEach(function (character) {
            if (character.problems.length) { flagged += 1; }
        });
        return {
            total: state.characters.length + state.orphans.length,
            characters: state.characters.length,
            orphans: state.orphans.length,
            scope: state.filters.scope,
            scoped: scoped.length,
            shown: matched.length,
            narrowed: matched.length !== scoped.length,
            flagged: flagged,
            traitsAvailable: traitsAvailable,
            aliasesRegistered: state.meta.aliasesRegistered
        };
    }

    function selectVisible(state) {
        var scoped = scopeRecords(state);
        var terms = searchTerms(state.filters.query);
        var traitsAvailable = state.meta.traitsAvailable;
        var matched = scoped.filter(function (character) {
            return matchesQuery(character, terms) &&
                matchesFilters(character, state.filters, traitsAvailable);
        });
        return sortRecords(matched, state.filters.sort);
    }

    function findByKey(state, key) {
        var all = state.characters.concat(state.orphans);
        for (var index = 0; index < all.length; index += 1) {
            if (all[index].key === key) { return all[index]; }
        }
        return null;
    }

    function selectSelected(state) {
        return state.selection.key ? findByKey(state, state.selection.key) : null;
    }

    /* Distinct persona statuses actually present, for the persona filter. The
     * list comes from the data rather than a constant, so a book with an unusual
     * status still offers it. */
    function selectPersonaStatuses(state) {
        var seen = {};
        state.characters.concat(state.orphans).forEach(function (character) {
            seen[character.personaStatus || 'none'] = true;
        });
        return Object.keys(seen).sort(function (left, right) {
            return left.localeCompare(right);
        });
    }

    function selectProblemCounts(state) {
        var counts = {};
        scopeRecords(state).forEach(function (character) {
            character.problems.forEach(function (code) {
                counts[code] = (counts[code] || 0) + 1;
            });
        });
        return counts;
    }

    /* `traitOrder` sorts by the age band the backend defines, youngest first,
     * which is the only meaningful direction for an age axis. */
    COMPARATORS.traitOrder = traitComparator;

    /* ── The voice editor ──────────────────────────────────────────────
     *
     * The draft is derived, not stored as a second copy of the character. A
     * character's own `catalogueVoiceId` IS the saved voice; the draft only
     * records what the user has chosen *instead*. That makes "unsaved changes"
     * a comparison rather than a flag that can drift from reality.
     */

    function currentVoiceId(character) {
        return character ? character.voice.catalogueVoiceId : null;
    }

    /* The draft in force for the selected character: the user's edit when there
     * is one, otherwise the character's saved voice. A draft left over from a
     * previous character is never returned for this one. */
    function selectDraft(state) {
        var selected = selectSelected(state);
        if (!selected) {
            return { characterKey: null, voiceId: null, cleared: false, dirty: false };
        }
        if (state.draft.characterKey === selected.key && state.draft.dirty) {
            return {
                characterKey: selected.key,
                voiceId: state.draft.voiceId,
                cleared: state.draft.cleared,
                dirty: true
            };
        }
        return {
            characterKey: selected.key,
            voiceId: currentVoiceId(selected),
            cleared: false,
            dirty: false
        };
    }

    /* What Save would write. Null `voiceId` with `cleared` is a clear. */
    function selectPendingCommand(state) {
        var draft = selectDraft(state);
        if (!draft.dirty) { return null; }
        return draft.cleared ? 'clear' : 'assign';
    }

    /* True only when a save is meaningful: a character is selected, the draft
     * differs from what is stored, and nothing is already in flight. */
    function selectCanSave(state) {
        var draft = selectDraft(state);
        if (!draft.characterKey || !draft.dirty) { return false; }
        if (state.save.state === 'saving') { return false; }
        var character = selectSelected(state);
        if (!character) { return false; }
        var savedId = currentVoiceId(character);
        if (draft.cleared) { return savedId !== null; }
        return draft.voiceId !== savedId;
    }

    /* The chosen voice, when the catalogue still holds it. A draft naming a voice
     * that has since disappeared is reported as unavailable rather than silently
     * treated as a valid selection. */
    function selectChosenVoice(state) {
        var draft = selectDraft(state);
        if (!draft.characterKey || draft.cleared || !draft.voiceId) { return null; }
        var found = null;
        state.catalogue.voices.forEach(function (voice) {
            if (voice.voiceId === draft.voiceId) { found = voice; }
        });
        return found;
    }

    function selectSaveState(state) {
        return state.save;
    }

    function selectCatalogue(state) {
        return state.catalogue;
    }

    /* ── Preview jobs ───────────────────────────────────────────────────
     * A job arrives in the same wire shape as everything else, so it is
     * converted here rather than by the module that fetched it. Keeping every
     * snake_case→camelCase conversion in this file is what stops a panel from
     * ever having to know which side of the boundary it is on.
     */
    function adaptPreviewJob(raw) {
        var source = (raw && typeof raw === 'object') ? raw : {};
        return {
            jobId: text(source.job_id),
            voiceId: typeof source.voice_id === 'string' ? source.voice_id : null,
            name: typeof source.name === 'string' ? source.name : null,
            kind: typeof source.kind === 'string' ? source.kind : null,
            profile: typeof source.profile === 'string' ? source.profile : null,
            status: text(source.status) || 'unknown',
            progress: numberOrNull(source.progress) || 0,
            terminal: boolOr(source.terminal, false),
            deduplicated: boolOr(source.deduplicated, false),
            createdAt: numberOrNull(source.created_at),
            startedAt: numberOrNull(source.started_at),
            completedAt: numberOrNull(source.completed_at),
            previewUrl: typeof source.preview_url === 'string' ? source.preview_url : null,
            error: typeof source.error === 'string' ? source.error : null,
            errorCode: typeof source.error_code === 'string' ? source.error_code : null,
            cached: boolOr(source.cached, false)
        };
    }

    namespace.selectors = {
        adaptProjection: adaptProjection,
        adaptCharacter: adaptCharacter,
        adaptCatalogue: adaptCatalogue,
        adaptPreviewJob: adaptPreviewJob,
        currentVoiceId: currentVoiceId,
        selectDraft: selectDraft,
        selectPendingCommand: selectPendingCommand,
        selectCanSave: selectCanSave,
        selectChosenVoice: selectChosenVoice,
        selectSaveState: selectSaveState,
        selectCatalogue: selectCatalogue,
        searchTerms: searchTerms,
        matchesQuery: matchesQuery,
        matchesFilters: matchesFilters,
        scopeRecords: scopeRecords,
        sortRecords: sortRecords,
        selectSummary: selectSummary,
        selectVisible: selectVisible,
        selectSelected: selectSelected,
        selectPersonaStatuses: selectPersonaStatuses,
        selectProblemCounts: selectProblemCounts,
        findByKey: findByKey,
        sortKeys: Object.keys(COMPARATORS),
        comparator: function (key) { return COMPARATORS[key] || null; },
        traitComparator: traitComparator
    };
    /* The store owns which keys a filter or sort may use; the selector owns which
     * of them it can actually compare. Asserting both directions at load time
     * means the two lists cannot drift apart without the namespace refusing to
     * load, rather than a sort silently doing nothing. */
    namespace.selectors.sortKeys.forEach(function (key) {
        if (store && store.schema && store.schema.sortKeys.indexOf(key) < 0) {
            throw new Error('Voices V2 selector sort key "' + key + '" is not in the store schema.');
        }
    });
    store.schema.sortKeys.forEach(function (key) {
        if (COMPARATORS[key] === undefined) {
            throw new Error('Voices V2 store sort key "' + key + '" has no selector comparator.');
        }
    });
}(window.VoicesV2 || (window.VoicesV2 = {})));