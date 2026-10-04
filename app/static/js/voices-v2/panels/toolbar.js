/* Voices V2 — the browser toolbar: search, filters, sort and the result count.
 *
 * The controls are static markup in index.html and the <option> lists are filled
 * from the projection's own vocabularies, because those come from
 * `speaker_traits` and cannot be restated in HTML without drifting.
 *
 * Two rules keep search usable while typing:
 *
 *   - The input and the selects are NEVER rebuilt during a session. They are
 *     populated once per projection and then only have their `value` written
 *     when it differs from the store, so focus, selection and the caret survive.
 *   - Every control writes to the store and the store drives the value. The DOM
 *     is an output, never the source of truth.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var selectors = namespace.selectors;
    var labels = namespace.labels;

    var SCHEMA = state.schema;
    var bound = false;
    var populatedFor = null;

    function region(name) {
        return core.region(name);
    }

    function filterControl(key) {
        return core.region('filter-' + key);
    }

    /* Enum options for one control. `pairs` is [[value, label], ...]. */
    function optionMarkup(pairs) {
        return pairs.map(function (pair) {
            return '<option value="' + core.escape(pair[0]) + '">' + core.escape(pair[1]) + '</option>';
        }).join('');
    }

    function genderOptions(vocabularies) {
        var pairs = [['all', 'Any gender'], ['unavailable', 'No traits recorded']];
        (vocabularies.genders || []).forEach(function (value) {
            if (value === 'unknown') { pairs.push(['unknown', 'Unknown']); return; }
            pairs.push([value, labels.genderLabel(value)]);
        });
        return pairs;
    }

    function ageOptions(vocabularies) {
        var pairs = [['all', 'Any age'], ['unavailable', 'No traits recorded']];
        (vocabularies.ageGroups || []).forEach(function (group) {
            if (group.value === 'unknown') { pairs.push(['unknown', 'Unknown']); return; }
            pairs.push([group.value, labels.ageGroupLabel(group.value)]);
        });
        return pairs;
    }

    function scopeOptions() {
        return [['all', 'Characters and orphans'], ['characters', 'Characters only'],
            ['orphans', 'Orphans only']];
    }

    function problemsOptions() {
        return [['all', 'Any'], ['flagged', 'Has a warning'], ['clean', 'No warnings']];
    }

    function sortOptions() {
        return SCHEMA.sortKeys.map(function (key) {
            return [key, labels.sortKeyLabel(key)];
        });
    }

    /* Only the direction is a plain value in state; the sort key and the
     * direction travel together through one select so a half-updated pair is
     * impossible. */
    function sortValue(sort) {
        return sort.key + ':' + sort.direction;
    }

    function parseSortValue(value) {
        var parts = String(value || '').split(':');
        return { key: parts[0], direction: parts[1] === 'desc' ? 'desc' : 'asc' };
    }

    /* Called once per projection, and again only if the vocabularies change. */
    function populate(nextState) {
        var vocabularies = nextState.meta.vocabularies;
        var signature = JSON.stringify([vocabularies.genders, vocabularies.ageGroups,
            selectors.selectPersonaStatuses(nextState)]);
        if (populatedFor === signature) { return false; }
        populatedFor = signature;

        var persona = [['all', 'Any']]
            .concat(selectors.selectPersonaStatuses(nextState).map(function (value) {
                return [value, value === 'none' ? 'No persona' : labels.personaStatusLabel(value)];
            }));
        var tri = [['all', 'Any'], ['yes', 'Yes'], ['no', 'No']];

        var options = {
            scope: optionMarkup(scopeOptions()),
            gender: optionMarkup(genderOptions(vocabularies)),
            ageGroup: optionMarkup(ageOptions(vocabularies)),
            assigned: optionMarkup(tri.map(function (pair) {
                return [pair[0], pair[0] === 'all' ? 'Any' : (pair[0] === 'yes' ? 'Assigned' : 'Unassigned')];
            })),
            ready: optionMarkup(tri.map(function (pair) {
                return [pair[0], pair[0] === 'all' ? 'Any' : (pair[0] === 'yes' ? 'Ready' : 'Not ready')];
            })),
            personaStatus: optionMarkup(persona),
            priority: optionMarkup([['all', 'Any'], ['major', 'Major'], ['minor', 'Minor'],
                ['none', 'No lines']]),
            problems: optionMarkup(problemsOptions()),
            sort: optionMarkup(sortOptions().map(function (pair) {
                return [pair[0] + ':asc', pair[1] + ' (ascending)'];
            }).concat(sortOptions().map(function (pair) {
                return [pair[0] + ':desc', pair[1] + ' (descending)'];
            })))
        };

        Object.keys(options).forEach(function (key) {
            var control = filterControl(key);
            if (control) { control.innerHTML = options[key]; }
        });
        return true;
    }

    /* One delegated listener per control family, bound once. Re-binding on every
     * render is the bug that makes a browser unusable after a few minutes. */
    function bind() {
        if (bound) { return false; }
        var search = region('search');
        if (search) {
            search.addEventListener('input', function (event) {
                state.dispatch({ type: 'filters/patch', patch: { query: event.target.value } });
            });
        }
        /* The search input and the combined sort select are bound separately; every
         * other filter key maps to one `[data-voicesv2-region="filter-<key>"]`
         * control generated from the store schema. */
        SCHEMA.filterKeys.filter(function (key) {
            return key !== 'query';
        }).concat(['sort']).forEach(function (key) {
            var control = filterControl(key);
            if (!control) { return; }
            control.addEventListener('change', function (event) {
                if (key === 'sort') {
                    state.dispatch({ type: 'filters/patch', patch: { sort: parseSortValue(event.target.value) } });
                    return;
                }
                state.dispatch({ type: 'filters/patch', patch: (function () {
                    var patch = {};
                    patch[key] = event.target.value;
                    return patch;
                }()) });
            });
        });
        var reset = region('reset-filters');
        if (reset) {
            reset.addEventListener('click', function () {
                state.dispatch({ type: 'filters/reset' });
            });
        }
        bound = true;
        return true;
    }

    function unmount() {
        bound = false;
        populatedFor = null;
    }

    /* Writes the store into the controls, touching only what differs. */
    function sync(nextState) {
        var filters = nextState.filters;
        var search = region('search');
        if (search && search.value !== filters.query) { search.value = filters.query; }

        SCHEMA.filterKeys.forEach(function (key) {
            if (key === 'query') { return; }
            var control = filterControl(key);
            if (control && control.value !== filters[key]) { control.value = filters[key]; }
        });
        var sortControl = filterControl('sort');
        if (sortControl) {
            var value = sortValue(filters.sort);
            if (sortControl.value !== value) { sortControl.value = value; }
        }

        /* Trait filters are disabled, not hidden: the control stays visible so the
         * reason it is inert can be announced next to it. */
        var traitsAvailable = nextState.meta.traitsAvailable;
        ['gender', 'ageGroup'].forEach(function (key) {
            var control = filterControl(key);
            if (!control) { return; }
            control.disabled = !traitsAvailable;
            control.setAttribute('aria-disabled', traitsAvailable ? 'false' : 'true');
        });

        var counts = region('counts');
        if (counts) { counts.innerHTML = countMarkup(selectors.selectSummary(nextState)); }
    }

    /* "23 of 87 characters" plus the orphan distinction, and whether anything is
     * currently hiding results. */
    function countMarkup(summary) {
        var parts = [];
        if (summary.shown === summary.total) {
            parts.push(summary.total + (summary.total === 1 ? ' character' : ' characters'));
        } else {
            parts.push(summary.shown + ' of ' + summary.total
                + (summary.total === 1 ? ' character' : ' characters'));
        }
        if (summary.orphans) {
            parts.push(summary.orphans + (summary.orphans === 1 ? ' orphan' : ' orphans'));
        }
        if (summary.flagged) {
            parts.push(summary.flagged + ' with warnings');
        }
        var markup = '<span class="vv2-counts">' + core.escape(parts.join(' \u00b7 ')) + '</span>';
        if (summary.narrowed) {
            markup += ' <button type="button" class="btn btn-link btn-sm p-0 align-baseline vv2-clear" '
                + 'data-voicesv2-action="clear-filters">Clear filters</button>';
        }
        return markup;
    }

    function mount(nextState) {
        bind();
        populate(nextState);
    }

    namespace.toolbar = {
        mount: mount,
        sync: sync,
        unmount: unmount,
        countMarkup: countMarkup,
        parseSortValue: parseSortValue,
        sortValue: sortValue
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));