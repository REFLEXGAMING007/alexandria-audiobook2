/* Voices V2 — the Voice Library's pure layer.
 *
 * Everything here is a function of the catalogue and the library state. No DOM,
 * no store writes, no mutation of the arrays that come out of the projection.
 * That is what makes a 79-voice catalogue feel instant on a phone: one read, and
 * every view the user can reach is a recomputation over the same array.
 *
 * Search haystacks are built once per catalogue (`buildHaystacks`) and passed
 * in, so a keystroke does not re-join the same strings for every voice.
 */
(function (namespace) {
    'use strict';

    var AGE_ORDER = ['infant', 'toddler', 'young_child', 'child', 'teen', 'young_adult',
        'adult', 'middle_aged', 'elderly', 'unknown'];

    var GENDER_ORDER = ['female', 'male', 'genderless', 'unknown'];

    function text(value) {
        return typeof value === 'string' ? value : '';
    }

    /* Multi-term AND. "female warm" finds a voice whose searchable metadata holds
     * both terms even when they sit in different fields, which is what someone
     * comparing a character against a library actually types. */
    function searchTerms(query) {
        return text(query).toLowerCase().split(/[^a-z0-9+]+/).filter(function (term) {
            return term.length > 0;
        });
    }

    function buildHaystacks(voices) {
        var stacks = {};
        voices.forEach(function (voice) {
            var parts = [voice.name, voice.label, voice.description, voice.kind,
                voice.source, voice.realisation, voice.gender, voice.ageGroup,
                voice.nativeId];
            (voice.tags || []).forEach(function (tag) { parts.push(tag); });
            stacks[voice.voiceId] = parts.filter(function (part) {
                return typeof part === 'string' && part;
            }).join(' ').toLowerCase();
        });
        return stacks;
    }

    function matchesSearch(voice, terms, haystacks) {
        if (!terms.length) { return true; }
        var haystack = haystacks && haystacks[voice.voiceId];
        if (haystack === undefined) {
            haystack = buildHaystacks([voice])[voice.voiceId];
        }
        return terms.every(function (term) {
            return haystack.indexOf(term) >= 0;
        });
    }

    /* Context is a suggestion, never a restriction. A voice whose gender or age
     * is unknown is NOT excluded by it - that would hide exactly the voices a
     * user needs to discover - and only an explicit gender/age filter narrows by
     * those fields. */
    function matchesContext(voice, context) {
        if (!context || !context.key) { return true; }
        if (context.gender && context.gender !== 'unknown' &&
                voice.gender !== 'unknown' && voice.gender !== context.gender) {
            return false;
        }
        /* An ageless character constrains nothing by age; a known-age character
         * still matches a voice with unknown age, because unknown is not a
         * mismatch. */
        if (!context.ageless && context.ageGroup && context.ageGroup !== 'unknown' &&
                voice.ageGroup !== 'unknown' && voice.ageGroup !== context.ageGroup) {
            return false;
        }
        return true;
    }

    function matchesFilters(voice, filters) {
        if (filters.gender !== 'all' && voice.gender !== filters.gender) { return false; }
        if (filters.ageGroup !== 'all' && voice.ageGroup !== filters.ageGroup) { return false; }
        if (filters.kind !== 'all' && voice.kind !== filters.kind) { return false; }
        if (filters.availability === 'available' && !voice.available) { return false; }
        if (filters.availability === 'unavailable' && voice.available) { return false; }
        if (filters.favorite && !voice.favorite) { return false; }
        if (filters.context === 'suggested' && !matchesContext(voice, filters.__context)) {
            return false;
        }
        return true;
    }

    function rank(value, order) {
        var index = order.indexOf(value);
        return index < 0 ? order.length : index;
    }

    /* Voices without a stated date sort last in `recent` rather than being
     * treated as new: an absent date is not a recent one. */
    var COMPARATORS = {
        name: function (left, right) {
            return text(left.name).localeCompare(text(right.name), undefined,
                { sensitivity: 'base' });
        },
        favorite: function (left, right) {
            var a = left.favorite ? 0 : 1;
            var b = right.favorite ? 0 : 1;
            if (a !== b) { return a - b; }
            return COMPARATORS.name(left, right);
        },
        availability: function (left, right) {
            var a = left.available ? 0 : 1;
            var b = right.available ? 0 : 1;
            if (a !== b) { return a - b; }
            return COMPARATORS.favorite(left, right);
        },
        kind: function (left, right) {
            var a = text(left.source).localeCompare(text(right.source));
            if (a !== 0) { return a; }
            return COMPARATORS.name(left, right);
        },
        gender: function (left, right) {
            var a = rank(left.gender, GENDER_ORDER) - rank(right.gender, GENDER_ORDER);
            if (a !== 0) { return a; }
            return COMPARATORS.name(left, right);
        },
        age: function (left, right) {
            var a = rank(left.ageGroup, AGE_ORDER) - rank(right.ageGroup, AGE_ORDER);
            if (a !== 0) { return a; }
            return COMPARATORS.name(left, right);
        },
        recent: function (left, right) {
            var a = left.addedAt || null;
            var b = right.addedAt || null;
            if (a === null && b === null) { return COMPARATORS.name(left, right); }
            if (a === null) { return 1; }
            if (b === null) { return -1; }
            if (a !== b) { return a < b ? -1 : 1; }
            return COMPARATORS.name(left, right);
        }
    };

    /* Undated voices stay at the end whichever way the sort points, in a stable
     * alphabetical order.
     *
     * Sorting them with the comparator would put them first when reversed, which
     * reads as "these are the newest" for voices whose source states no date at
     * all. Fixing the order here rather than in the comparator is what makes that
     * independent of the sort direction.
     */
    function undatedLast(sorted, key) {
        if (key !== 'recent') { return sorted; }
        var dated = [];
        var undated = [];
        sorted.forEach(function (voice) {
            if (voice.addedAt === null || voice.addedAt === undefined) {
                undated.push(voice);
            } else {
                dated.push(voice);
            }
        });
        undated.sort(function (left, right) {
            return text(left.name).localeCompare(text(right.name), undefined,
                { sensitivity: 'base' });
        });
        return dated.concat(undated);
    }

    function sortVoices(voices, sort) {
        var requested = (sort && sort.key) || 'name';
        var comparator = COMPARATORS[requested] || COMPARATORS.name;
        var descending = !!sort && sort.direction === 'desc';
        /* slice() first: sort() mutates, and the argument may be a store array. */
        var sorted = voices.slice().sort(function (left, right) {
            var result = comparator(left, right);
            if (result !== 0) { return descending ? -result : result; }
            return text(left.name).localeCompare(text(right.name), undefined,
                { sensitivity: 'base' });
        });
        return undatedLast(sorted, requested);
    }

    /* The one place the library's result set is produced. */
    function selectFiltered(state, haystacks) {
        var filters = state.libraryFilters;
        var scoped = { gender: filters.gender, ageGroup: filters.ageGroup,
            kind: filters.kind, availability: filters.availability,
            favorite: filters.favorite, context: filters.context,
            __context: state.libraryContext };
        var terms = searchTerms(state.librarySearch);
        var matched = state.catalogue.voices.filter(function (voice) {
            return matchesSearch(voice, terms, haystacks) && matchesFilters(voice, scoped);
        });
        return sortVoices(matched, state.librarySort);
    }

    function selectAll(state) {
        return state.catalogue.voices;
    }

    /* What the header reports. Counts are computed over the whole catalogue so
     * "favourites: 3" does not change as the user types. */
    function selectSummary(state, haystacks) {
        var all = selectAll(state);
        var shown = selectFiltered(state, haystacks);
        var favorites = 0;
        var available = 0;
        var previewable = 0;
        all.forEach(function (voice) {
            if (voice.favorite) { favorites += 1; }
            if (voice.available) { available += 1; }
            if (voice.previewCapable) { previewable += 1; }
        });
        return {
            total: all.length,
            shown: shown.length,
            favorites: favorites,
            available: available,
            previewable: previewable,
            activeFilters: selectChips(state).length,
            filtered: shown.length !== all.length
        };
    }

    /* Family labels, mirrored from the backend's KIND_SOURCE_LABELS so a chip can
     * name a type without scanning the catalogue to look the label up. */
    var KIND_SOURCES = {
        lora: 'Trained LoRA', builtin_lora: 'Built-in LoRA',
        clone: 'Uploaded clone', design: 'Designed voice'
    };

    function ageLabel(state, value) {
        if (value === 'unknown') { return 'Unknown age'; }
        var groups = (state.meta && state.meta.vocabularies && state.meta.vocabularies.ageGroups)
            || [];
        for (var index = 0; index < groups.length; index += 1) {
            if (groups[index].value === value) {
                return groups[index].label
                    ? groups[index].label + ' (' + value.replace(/_/g, ' ') + ')'
                    : value.replace(/_/g, ' ');
            }
        }
        return text(value).replace(/_/g, ' ');
    }

    function filterLabel(key, value, state) {
        if (key === 'favorite') { return 'Favourites'; }
        if (key === 'context') {
            return 'For ' + (state.libraryContext.name || 'this character');
        }
        if (key === 'kind') { return KIND_SOURCES[value] || value; }
        if (key === 'ageGroup') { return ageLabel(state, value); }
        if (key === 'gender') {
            return value === 'unknown' ? 'Unknown gender'
                : value.charAt(0).toUpperCase() + value.slice(1);
        }
        if (key === 'availability') {
            return value === 'available' ? 'Available' : 'Unavailable';
        }
        return key + ': ' + value;
    }

    /* One removable chip per active filter, so undoing a single narrowing never
     * means reopening the filter panel. */
    function selectChips(state) {
        var filters = state.libraryFilters;
        var chips = [];
        Object.keys(filters).forEach(function (key) {
            if (key === '__context') { return; }
            var value = filters[key];
            var active = key === 'favorite' ? value === true : value !== 'all' &&
                !(key === 'context' && value === 'off');
            if (active) { chips.push({ key: key, value: value, label: filterLabel(key, value, state) }); }
        });
        return chips;
    }

    function selectSelectedVoice(state) {
        return selectSelectedDraftVoice(state);
    }

    function selectSelectedDraftVoice(state) {
        var character = namespace.selectors.selectSelected(state);
        if (!character) { return null; }
        var wanted = character.voice.catalogueVoiceId;
        if (!wanted) { return null; }
        var voices = state.catalogue.voices;
        for (var index = 0; index < voices.length; index += 1) {
            if (voices[index].voiceId === wanted) { return voices[index]; }
        }
        return null;
    }

    /* Previous/Next move inside the *current* result set only, so navigation can
     * never land on a voice the filters excluded. */
    function selectNeighbours(state, haystacks) {
        var results = selectFiltered(state, haystacks);
        if (!results.length) {
            return { position: 0, total: 0, previous: null, next: null, current: null };
        }
        var cursor = state.librarySelection.cursor;
        var index = -1;
        for (var scan = 0; scan < results.length; scan += 1) {
            if (results[scan].voiceId === cursor) { index = scan; break; }
        }
        if (index < 0) { index = 0; }
        return {
            position: index + 1,
            total: results.length,
            previous: index > 0 ? results[index - 1] : null,
            next: index < results.length - 1 ? results[index + 1] : null,
            current: results[index]
        };
    }

    /* Dice chooses from the filtered set. Choosing from the whole catalogue and
     * rejecting mismatches would make the button feel broken whenever a filter is
     * active, and would not be random with respect to what the user can see. */
    function selectRandomEligible(state, haystacks, randomFn) {
        var eligible = selectFiltered(state, haystacks);
        if (!eligible.length) { return null; }
        var pick = typeof randomFn === 'function' ? randomFn : Math.random;
        var index = Math.floor(pick() * eligible.length);
        if (!(index >= 0) || index >= eligible.length) { index = 0; }
        return eligible[index];
    }

    /* How many voices the character's traits would accept, and how many of those
     * are actually metadata-backed rather than merely unknown-typed. */
    function selectContextCompatible(state) {
        var context = state.libraryContext;
        var matching = 0;
        var inferred = 0;
        state.catalogue.voices.forEach(function (voice) {
            if (!matchesContext(voice, context)) { return; }
            matching += 1;
            if (context.gender && context.gender !== 'unknown' &&
                    voice.genderSource !== 'declared') { inferred += 1; }
        });
        return { total: matching, inferred: inferred, declared: matching - inferred };
    }

    function selectPreviewState(state) {
        return state.preview;
    }

    namespace.libraryFilters = {
        AGE_ORDER: AGE_ORDER.slice(),
        GENDER_ORDER: GENDER_ORDER.slice(),
        searchTerms: searchTerms,
        buildHaystacks: buildHaystacks,
        matchesSearch: matchesSearch,
        matchesFilters: matchesFilters,
        matchesContext: matchesContext,
        sortVoices: sortVoices,
        selectAll: selectAll,
        selectFiltered: selectFiltered,
        selectSummary: selectSummary,
        selectChips: selectChips,
        selectSelectedVoice: selectSelectedVoice,
        selectNeighbours: selectNeighbours,
        selectRandomEligible: selectRandomEligible,
        selectContextCompatible: selectContextCompatible,
        selectPreviewState: selectPreviewState,
        comparator: function (key) { return COMPARATORS[key] || null; },
        sortKeys: Object.keys(COMPARATORS)
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));