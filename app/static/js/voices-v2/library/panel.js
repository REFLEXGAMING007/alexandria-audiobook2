/* Voices V2 — the Voice Library panel.
 *
 * The controls are static markup in index.html and only the *outputs* are
 * rewritten: the context banner, the chips, the count, the list. That is the
 * Phase 1 toolbar pattern, and it is why typing in the library search box keeps
 * its caret and its selection - rebuilding the input would lose both.
 *
 * Mobile-first order, which is also the reading order: search, filters, sort,
 * result count, then cards. The two-column desktop arrangement is CSS only.
 *
 * The panel renders from the store and dispatches actions. It holds no
 * persistence logic and no sequencing: choosing a voice writes a *draft*, and
 * Phase 2's assignment panel owns the one save path.
 *
 * The searchable text for every voice is built once when the catalogue arrives,
 * not on each keystroke, so typing stays cheap even with a few hundred voices.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var selectors = namespace.selectors;
    var libraryFilters = namespace.libraryFilters;
    var cards = namespace.libraryCards;
    var labels = namespace.labels;
    var audio = namespace.libraryAudio;

    var bound = false;
    var haystacks = {};

    var SORT_LABELS = {
        name: 'Name', favorite: 'Favourites first', availability: 'Available first',
        kind: 'Type', gender: 'Gender', age: 'Age', recent: 'Recently added'
    };

    var FILTER_CONTROLS = ['gender', 'ageGroup', 'kind', 'availability', 'favorite'];

    function panel() {
        return core.region('library');
    }

    /* ── Control population, once per catalogue ───────────────────────── */

    function optionMarkup(pairs) {
        return pairs.map(function (pair) {
            return '<option value="' + core.escape(pair[0]) + '">' + core.escape(pair[1])
                + '</option>';
        }).join('');
    }

    function kindOptions(current) {
        var pairs = [['all', 'Any type']];
        (current.catalogue.kinds || []).forEach(function (kind) {
            /* One lookup, not a filter over the catalogue per kind. */
            var found = null;
            for (var index = 0; index < current.catalogue.voices.length; index += 1) {
                if (current.catalogue.voices[index].kind === kind) {
                    found = current.catalogue.voices[index];
                    break;
                }
            }
            pairs.push([kind, (found && found.source) || kind]);
        });
        return pairs;
    }

    function ageOptions(current) {
        var pairs = [['all', 'Any age'], ['unknown', 'Unknown age']];
        var groups = (current.meta && current.meta.vocabularies
            && current.meta.vocabularies.ageGroups) || [];
        groups.forEach(function (group) {
            pairs.push([group.value, labels.ageGroupLabel(group.value)]);
        });
        return pairs;
    }

    function sortOptions() {
        var pairs = [];
        Object.keys(SORT_LABELS).forEach(function (key) {
            pairs.push([key + ':asc', SORT_LABELS[key] + ' (ascending)']);
            pairs.push([key + ':desc', SORT_LABELS[key] + ' (descending)']);
        });
        return pairs;
    }

    var OPTION_SETS = {
        gender: function () {
            return [['all', 'Any gender'], ['male', 'Male'], ['female', 'Female'],
                ['genderless', 'Genderless'], ['unknown', 'Unknown gender']];
        },
        availability: function () {
            return [['all', 'Any'], ['available', 'Available'],
                ['unavailable', 'Not available']];
        },
        favorite: function () {
            return [['all', 'Any'], ['yes', 'Favourites only']];
        },
        sort: function () { return sortOptions(); }
    };

    /* Called whenever the catalogue changes. Not called on every render, so the
     * controls - and the user's caret - survive typing. */
    function populate(current) {
        var sets = {
            gender: OPTION_SETS.gender(),
            ageGroup: ageOptions(current),
            kind: kindOptions(current),
            availability: OPTION_SETS.availability(),
            favorite: OPTION_SETS.favorite(),
            sort: OPTION_SETS.sort()
        };
        Object.keys(sets).forEach(function (name) {
            var control = core.region('library-filter-' + name);
            if (control) { control.innerHTML = optionMarkup(sets[name]); }
        });
    }

    /* ── Sync, every render ──────────────────────────────────────────────
     * Only writes a control when it differs, so a re-render caused by something
     * else does not interrupt typing. */
    function syncControls(current) {
        var search = core.region('library-search');
        if (search && search.value !== current.librarySearch) {
            search.value = current.librarySearch;
        }
        FILTER_CONTROLS.forEach(function (name) {
            var control = core.region('library-filter-' + name);
            if (!control) { return; }
            var wanted = name === 'favorite'
                ? (current.libraryFilters.favorite ? 'yes' : 'all')
                : current.libraryFilters[name];
            if (control.value !== wanted) { control.value = wanted; }
        });
        var sort = core.region('library-filter-sort');
        if (sort) {
            var sortValue = current.librarySort.key + ':' + current.librarySort.direction;
            if (sort.value !== sortValue) { sort.value = sortValue; }
        }
    }

    /* ── Outputs ───────────────────────────────────────────────────────── */

    function positionText(info) {
        if (!info.total) { return 'No voices'; }
        return 'Voice ' + info.position + ' of ' + info.total;
    }

    function countText(summary) {
        if (summary.shown === summary.total) {
            return summary.total + (summary.total === 1 ? ' voice' : ' voices');
        }
        return summary.shown + ' of ' + summary.total + ' voices';
    }

    function contextMarkup(current) {
        var context = current.libraryContext;
        if (!context.key) { return ''; }
        var traits = labels.traitSentence({
            gender: context.gender, ageGroup: context.ageGroup, ageless: context.ageless
        }, true);
        var compatible = libraryFilters.selectContextCompatible(current);
        var narrowing = current.libraryFilters.context === 'suggested';
        return '<div class="vv2-library-context-text">'
            + 'Choosing a voice for:<br><strong>' + core.escape(context.name) + '</strong>'
            + ' \u00b7 ' + core.escape(traits === labels.NOT_AVAILABLE
                ? 'traits not recorded' : traits)
            + '<br>' + compatible.total + ' of ' + current.catalogue.voices.length
            + ' voices match'
            + (compatible.inferred
                ? ', ' + compatible.inferred + ' of them by inferred traits' : '')
            + '</div>'
            + '<div class="vv2-save-actions">'
            + '<button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-voicesv2-action="toggle-context-filter"'
            + ' aria-pressed="' + (narrowing ? 'true' : 'false') + '">'
            + (narrowing ? 'Stop narrowing by character' : 'Narrow by character traits')
            + '</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-voicesv2-action="close-library">Close library</button>'
            + '</div>';
    }

    function chipsMarkup(current) {
        var chips = libraryFilters.selectChips(current);
        if (!chips.length) { return ''; }
        return '<span class="small vv2-muted">Filters:</span>'
            + chips.map(function (chip) {
                return '<span class="vv2-chip">' + core.escape(chip.label)
                    + '<button type="button" class="vv2-chip-remove"'
                    + ' data-voicesv2-action="remove-filter"'
                    + ' data-voicesv2-filter="' + core.escape(chip.key) + '"'
                    + ' title="Remove this filter">'
                    + '<span aria-hidden="true">\u00d7</span>'
                    + '<span class="vv2-sr-only">Remove filter '
                    + core.escape(chip.label) + '</span></button></span>';
            }).join('')
            + '<button type="button" class="btn btn-link btn-sm vv2-chips-clear"'
            + ' data-voicesv2-action="clear-filters">Clear all</button>';
    }

    function listMarkup(current) {
        var catalogue = current.catalogue;
        if (catalogue.error) {
            return '<div class="alert alert-danger vv2-library-state" role="alert">'
                + '<strong>Unable to load the voice library.</strong><br>'
                + core.escape(catalogue.error)
                + '<div class="vv2-save-actions mt-2">'
                + '<button type="button" class="btn btn-sm btn-outline-danger"'
                + ' data-voicesv2-action="reload-catalogue">Retry</button>'
                + '</div></div>';
        }
        if (!catalogue.loaded) {
            return '<div class="alert alert-secondary vv2-library-state" role="status">'
                + 'Loading voices&hellip;</div>';
        }
        if (!catalogue.voices.length) {
            return '<div class="alert alert-info vv2-library-state" role="status">'
                + 'No voices are available in this workspace yet. Train a LoRA, upload a clone, '
                + 'or design a voice, then reload.'
                + '<div class="vv2-save-actions mt-2">'
                + '<button type="button" class="btn btn-sm btn-outline-primary"'
                + ' data-voicesv2-action="reload-catalogue">Reload voices</button>'
                + '</div></div>';
        }
        var visible = libraryFilters.selectFiltered(current, haystacks);
        if (!visible.length) {
            var narrowed = libraryFilters.selectChips(current).length > 0
                ? 'Narrowing is active: remove a filter chip above, or clear them all.'
                : 'Nothing in the catalogue matches that search.';
            return '<div class="alert alert-warning vv2-library-state" role="status">'
                + '<strong>No voices match the current search and filters.</strong> '
                + narrowed
                + '<div class="vv2-save-actions mt-2">'
                + '<button type="button" class="btn btn-sm btn-outline-secondary"'
                + ' data-voicesv2-action="clear-filters">Clear filters</button>'
                + '</div></div>';
        }
        var info = libraryFilters.selectNeighbours(current, haystacks);
        var selected = selectors.selectSelected(current);
        return cards.list(visible, {
            selectedVoiceId: selected ? selectors.currentVoiceId(selected) : null,
            cursorVoiceId: info.current ? info.current.voiceId : null
        });
    }

    function render() {
        var container = panel();
        if (!container) { return false; }
        var current = state.getState();
        var open = current.library.open;

        if (!open) {
            if (container.innerHTML !== '') { container.innerHTML = ''; }
            container.hidden = true;
            return true;
        }
        container.hidden = false;
        populate(current);
        syncControls(current);

        var summary = libraryFilters.selectSummary(current, haystacks);
        var info = libraryFilters.selectNeighbours(current, haystacks);

        var banner = core.region('library-context');
        if (banner) { banner.innerHTML = contextMarkup(current); }
        var chips = core.region('library-chips');
        if (chips) { chips.innerHTML = chipsMarkup(current); }
        var count = core.region('library-count');
        if (count) { count.textContent = countText(summary); }
        var position = core.region('library-position');
        if (position) { position.textContent = positionText(info); }
        var list = core.region('library-list');
        if (list) { list.innerHTML = listMarkup(current); }

        var previous = core.region('library-previous');
        if (previous) { previous.disabled = !info.previous; }
        var next = core.region('library-next');
        if (next) { next.disabled = !info.next; }
        var random = core.region('library-random');
        if (random) { random.disabled = !summary.shown; }
        return true;
    }

    /* ── Actions ─────────────────────────────────────────────────────────
     * Each is a single dispatch or a single library read. The panel never writes
     * a file and never calls the server directly. */

    var previews = namespace.libraryPreviews;

    /* ── Actions ─────────────────────────────────────────────────────────
     * Each is a single dispatch or a single library read. The panel never writes
     * a file and never calls the server directly.
     *
     * Preview actions go through library/previews.js rather than being written
     * here, so the generate/poll/cancel sequence exists once and is testable
     * without a DOM. */

    function open(characterKey) {
        state.dispatch({ type: 'library/open', key: characterKey || null });
    }

    function close() {
        /* Stop watching a job before the panel goes: a poll that outlives the
         * library would keep re-rendering a region nobody is looking at. */
        previews.stopPolling();
        audio.stop();
        state.dispatch({ type: 'library/close' });
    }

    function findVoice(voiceId) {
        var voices = state.getState().catalogue.voices;
        for (var index = 0; index < voices.length; index += 1) {
            if (voices[index].voiceId === voiceId) { return voices[index]; }
        }
        return null;
    }

    function choose(voiceId) {
        var voice = findVoice(voiceId);
        if (!voice || !voice.available) { return false; }
        /* The library writes a draft through Phase 2's command. It does not save. */
        state.dispatch({ type: 'draft/choose', voiceId: voiceId });
        state.dispatch({ type: 'library/cursor', voiceId: voiceId });
        return true;
    }

    function step(offset) {
        var info = libraryFilters.selectNeighbours(state.getState(), haystacks);
        var target = offset < 0 ? info.previous : info.next;
        if (!target) { return false; }
        state.dispatch({ type: 'library/cursor', voiceId: target.voiceId });
        return true;
    }

    function random(randomFn) {
        var voice = libraryFilters.selectRandomEligible(state.getState(), haystacks, randomFn);
        if (!voice) { return false; }
        state.dispatch({ type: 'library/cursor', voiceId: voice.voiceId });
        return true;
    }

    function removeFilter(key) {
        if (key === 'favorite') {
            state.dispatch({ type: 'library/filters', patch: { favorite: false } });
            return true;
        }
        if (key === 'context') {
            state.dispatch({ type: 'library/filters', patch: { context: 'off' } });
            return true;
        }
        var patch = {};
        patch[key] = 'all';
        state.dispatch({ type: 'library/filters', patch: patch });
        return true;
    }

    function clearFilters() {
        state.dispatch({ type: 'library/resetFilters' });
    }

    function toggleContextFilter() {
        var current = state.getState();
        state.dispatch({
            type: 'library/filters',
            patch: { context: current.libraryFilters.context === 'suggested' ? 'off' : 'suggested' }
        });
    }

    function setSearch(query) {
        state.dispatch({ type: 'library/search', query: query });
    }

    function setFilter(key, value) {
        if (key === 'favorite') {
            state.dispatch({ type: 'library/filters', patch: { favorite: value === 'yes' } });
            return true;
        }
        var patch = {};
        patch[key] = value;
        state.dispatch({ type: 'library/filters', patch: patch });
        return true;
    }

    function setSort(value) {
        var parts = String(value || '').split(':');
        state.dispatch({ type: 'library/sort', key: parts[0],
            direction: parts[1] === 'desc' ? 'desc' : 'asc' });
    }

    /* Not optimistic. The store is changed from the server's answer, so a
     * refused or failed write leaves the star exactly where it was - which is
     * the only safe behaviour when the write is a shared, persisted list. */
    function toggleFavorite(voiceId) {
        var voice = findVoice(voiceId);
        if (!voice || !voice.favoriteSupported) { return Promise.resolve(false); }
        return namespace.api.setFavorite(voiceId, !voice.favorite).then(function (result) {
            namespace.libraryIndex.applyFavorites(result.favorites);
            return true;
        }, function () {
            return false;
        });
    }

    /* Playback lives in library/previews.js now, so a recorded and a generated
     * preview reach the audio manager by the same path. */
    function preview(voiceId) {
        return previews.play(voiceId);
    }

    /* ── Wiring ───────────────────────────────────────────────────────── */

    function onChange(event) {
        var origin = event && event.target;
        if (!origin) { return false; }
        var region = origin.getAttribute('data-voicesv2-region');
        if (region === 'library-search') { setSearch(origin.value); return true; }
        if (region === 'library-filter-sort') { setSort(origin.value); return true; }
        if (region && region.indexOf('library-filter-') === 0) {
            setFilter(region.slice('library-filter-'.length), origin.value);
            return true;
        }
        return false;
    }

    function onClick(event) {
        var origin = event && event.target;
        var action = origin && origin.closest ? origin.closest('[data-voicesv2-action]') : null;
        if (!action || !core.contains(action)) { return false; }
        var name = action.getAttribute('data-voicesv2-action');
        var voiceId = action.getAttribute('data-voicesv2-voice');
        if (name === 'choose-voice') { choose(voiceId); return true; }
        if (name === 'generate-preview') { previews.generate(voiceId); return true; }
        if (name === 'play-preview') { previews.play(voiceId); return true; }
        if (name === 'cancel-preview') {
            previews.cancel(action.getAttribute('data-voicesv2-job') || voiceId);
            return true;
        }
        if (name === 'toggle-favorite') { toggleFavorite(voiceId); return true; }
        if (name === 'library-previous') { step(-1); return true; }
        if (name === 'library-next') { step(1); return true; }
        if (name === 'library-random') { random(); return true; }
        if (name === 'remove-filter') {
            removeFilter(action.getAttribute('data-voicesv2-filter'));
            return true;
        }
        if (name === 'clear-filters') { clearFilters(); return true; }
        if (name === 'toggle-context-filter') { toggleContextFilter(); return true; }
        if (name === 'close-library') { close(); return true; }
        if (name === 'reload-catalogue') { namespace.lifecycle.loadCatalogue(); return true; }
        return false;
    }

    function bind() {
        if (bound) { return false; }
        var container = panel();
        if (!container) { return false; }
        container.addEventListener('change', onChange);
        /* A search box needs `input`, not `change`: `change` only fires on blur or
         * Enter, so filtering per keystroke would not happen at all. */
        container.addEventListener('input', onChange);
        container.addEventListener('click', onClick);
        bound = true;
        return true;
    }

    function unmount() {
        /* Polling stops with the panel, so a job in flight is not watched by a
         * tab that is no longer showing it. The server's own stale recovery is
         * what resolves it if the browser goes away entirely. */
        previews.stopPolling();
        bound = false;
        haystacks = {};
    }
    function mount() {
        bind();
    }
    /* Called when a new catalogue arrives, so searchable text is built once per
     * load rather than once per keystroke. */
    function setCatalogue(voices) {
        haystacks = libraryFilters.buildHaystacks(voices || []);
    }

    namespace.libraryPanel = {
        mount: mount,
        render: render,
        unmount: unmount,
        bind: bind,
        open: open,
        close: close,
        choose: choose,
        findVoice: findVoice,
        step: step,
        random: random,
        removeFilter: removeFilter,
        clearFilters: clearFilters,
        toggleContextFilter: toggleContextFilter,
        setSearch: setSearch,
        setFilter: setFilter,
        setSort: setSort,
        toggleFavorite: toggleFavorite,
        preview: preview,
        populate: populate,
        setCatalogue: setCatalogue,
        haystacks: function () { return haystacks; }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));