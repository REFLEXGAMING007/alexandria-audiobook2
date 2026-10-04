/* Voices V2 — the store: state, subscribe, emit, dispatch, select.
 *
 * The store partitions state the way every later phase needs:
 *
 *   meta                                       server metadata: book identity and
 *                                              the enumerations speaker_traits defines.
 *   characters, orphans, catalogue, library    server projections. Owned by the
 *                                              backend, replaced wholesale by a
 *                                              read, never assembled in the DOM.
 *   selection, filters                         V2 session state. Lost on reload,
 *                                              never sent to the server.
 *   ui                                         lifecycle state owned by
 *                                              lifecycle.js.
 *
 * Records are camelCase. The wire shape is snake_case, and the single place that
 * converts is selectors.adaptProjection, so no panel ever spells a server field
 * two different ways.
 *
 * Two rules make the isolation real rather than aspirational:
 *
 *   1. The store holds data only. A command that would put a DOM node in state
 *      is rejected, so no panel can smuggle a live element into application
 *      state and then read it back as if it were data.
 *   2. dispatch is the only writer. Rendering subscribes; it never writes. That
 *      is what replaces collectVoiceConfig()'s DOM scrape, where the card
 *      markup was simultaneously the view, the edit buffer and the save payload.
 *
 * Filter and sort values are validated against `schema` inside the reducer, so a
 * control and the store cannot disagree, and an unknown filter name throws
 * instead of being dropped. A silently ignored filter would present as missing
 * data, which is worse than a visible error.
 *
 * `getState()` hands back the live object for cheap reads, the way a plain
 * JavaScript store does. Treat it as read-only; `select()` is the safer read
 * for anything that will be stored past the current tick.
 */
(function (namespace) {
    'use strict';

    function createInitialState() {
        return {
            /* Server projections. Owned by the backend, replaced wholesale by a
             * read, never assembled in the DOM. Records are camelCase: the wire
             * shape is adapted once, in selectors.adaptProjection. */
            meta: createInitialMeta(),
            characters: [],
            orphans: [],
            catalogue: [],
            library: {},
            /* Session state. Lost on reload, never sent to the server. */
            selection: { key: null },
            filters: createInitialFilters(),
            ui: {
                mounted: false,
                loading: false,
                error: null,
                loadedAt: null
            }
        };
    }

    /* Book identity and the enumerations the backend derived from
     * speaker_traits. Carried here rather than in `ui` because it is server data,
     * not a view state, and because the filter controls are built from it. */
    function createInitialMeta() {
        return {
            schemaVersion: null,
            book: { bookId: null, token: null, scriptSha256: null, scriptPresent: false },
            traitsAvailable: false,
            traitsRequested: null,
            aliasesRegistered: false,
            majorLineThreshold: null,
            vocabularies: { genders: [], ageGroups: [], problemCodes: [] }
        };
    }

    /* Every narrowing and ordering choice the user can make, in one place, so
     * `filters/reset` has exactly one thing to restore and the toolbar has one
     * schema to bind to. `sort` lives here because sorting is a view preference
     * with the same lifetime as the filters. */
    function createInitialFilters() {
        return {
            query: '',
            scope: 'all',
            gender: 'all',
            ageGroup: 'all',
            assigned: 'all',
            ready: 'all',
            personaStatus: 'all',
            priority: 'all',
            problems: 'all',
            sort: { key: 'name', direction: 'asc' }
        };
    }

    var FILTER_KEYS = Object.keys(createInitialFilters()).filter(function (key) {
        return key !== 'sort';
    });

    var SORT_KEYS = ['name', 'lineCount', 'priority', 'voiceStatus', 'voice', 'ready', 'traitOrder'];

    var SCOPES = ['all', 'characters', 'orphans'];

    var TRISTATE = ['all', 'yes', 'no'];

    var PRIORITIES = ['all', 'major', 'minor', 'none'];

    var PROBLEM_MODES = ['all', 'flagged', 'clean'];

    var state = createInitialState();
    var listeners = [];

    function resolve(path) {
        return String(path).split('.').reduce(function (node, key) {
            return (node === null || node === undefined) ? undefined : node[key];
        }, state);
    }

    /* A subscription to a path also hears about that path's subtree, so
     * `subscribe('ui', ...)` sees `ui.error` and `subscribe('*', ...)` hears
     * about everything. */
    function matches(subscription, path) {
        if (subscription.path === '*') { return true; }
        if (subscription.path === path) { return true; }
        return path.indexOf(subscription.path + '.') === 0;
    }

    function emit(path) {
        listeners.slice().forEach(function (subscription) {
            if (matches(subscription, path)) {
                subscription.listener(state, path);
            }
        });
        return path;
    }

    function subscribe(path, listener) {
        var target = (path === undefined || path === null) ? '*' : String(path);
        var handler = (typeof path === 'function') ? path : listener;
        if (typeof handler !== 'function') {
            throw new TypeError('VoicesV2.subscribe needs a listener function.');
        }
        var subscription = { path: target, listener: handler };
        listeners.push(subscription);
        return function unsubscribe() {
            var index = listeners.indexOf(subscription);
            if (index >= 0) { listeners.splice(index, 1); }
        };
    }

    function requireArray(command, field) {
        var value = command[field];
        if (!Array.isArray(value)) {
            throw new TypeError('VoicesV2 command "' + command.type + '" needs an array "' + field + '".');
        }
        return value;
    }

    function requireBoolean(command, field) {
        var value = command[field];
        if (typeof value !== 'boolean') {
            throw new TypeError('VoicesV2 command "' + command.type + '" needs a boolean "' + field + '".');
        }
        return value;
    }

    /* Returns the changed path so dispatch can emit exactly one notification
     * per command, instead of one per field touched. */
    function reduce(command) {
        switch (command.type) {
            case 'meta/set':
                if (!command.meta || typeof command.meta !== 'object' || Array.isArray(command.meta)) {
                    throw new TypeError('VoicesV2 command "meta/set" needs an object "meta".');
                }
                state.meta = command.meta;
                return 'meta';
            case 'characters/set':
                state.characters = requireArray(command, 'characters');
                return 'characters';
            case 'orphans/set':
                state.orphans = requireArray(command, 'orphans');
                return 'orphans';
            case 'selection/set':
                if (command.key !== null && typeof command.key !== 'string') {
                    throw new TypeError('VoicesV2 command "selection/set" needs a string key or null.');
                }
                state.selection.key = command.key;
                return 'selection';
            case 'filters/patch':
                return reduceFilterPatch(command);
            case 'filters/reset':
                state.filters = createInitialFilters();
                return 'filters';
            case 'ui/loading':
                state.ui.loading = requireBoolean(command, 'loading');
                return 'ui.loading';
            case 'ui/error':
                state.ui.error = (command.error === undefined || command.error === null)
                    ? null
                    : String(command.error);
                return 'ui.error';
            case 'ui/loaded':
                state.ui.loadedAt = (command.loadedAt === undefined || command.loadedAt === null)
                    ? Date.now()
                    : command.loadedAt;
                return 'ui.loadedAt';
            case 'ui/mounted':
                state.ui.mounted = requireBoolean(command, 'mounted');
                return 'ui.mounted';
            default:
                throw new Error('Voices V2 does not implement the command "' + command.type + '".');
        }
    }

    /* Filter keys are validated against the allowed vocabulary here rather than
     * in the toolbar, so no caller can put the browser into a state where the
     * control and the store disagree. An unknown key is a programming error and
     * is thrown, not ignored: a silently dropped filter would look like the data
     * is missing. */
    function reduceFilterPatch(command) {
        var patch = command.patch;
        if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
            throw new TypeError('VoicesV2 command "filters/patch" needs an object "patch".');
        }
        var keys = Object.keys(patch);
        if (!keys.length) { return 'filters'; }

        var allowed = {
            query: null,
            scope: SCOPES,
            gender: null,
            ageGroup: null,
            assigned: TRISTATE,
            ready: TRISTATE,
            personaStatus: null,
            priority: PRIORITIES,
            problems: PROBLEM_MODES
        };

        keys.forEach(function (key) {
            if (key === 'sort') { return; }
            if (!Object.prototype.hasOwnProperty.call(allowed, key)) {
                throw new Error('Voices V2 has no filter named "' + key + '".');
            }
            var value = patch[key];
            var vocabulary = allowed[key];
            /* A null vocabulary means "any string": gender, age group and persona
             * status are derived from the book, so their values are not known
             * until the projection arrives. */
            if (vocabulary && vocabulary.indexOf(String(value)) < 0) {
                throw new Error('Voices V2 filter "' + key + '" does not accept "' + value + '".');
            }
        });

        keys.forEach(function (key) {
            if (key === 'sort') {
                var sort = patch.sort || {};
                if (SORT_KEYS.indexOf(String(sort.key)) < 0) {
                    throw new Error('Voices V2 cannot sort by "' + sort.key + '".');
                }
                if (['asc', 'desc'].indexOf(String(sort.direction)) < 0) {
                    throw new Error('Voices V2 sort direction "' + sort.direction + '" is not asc or desc.');
                }
                state.filters.sort = { key: String(sort.key), direction: String(sort.direction) };
                return;
            }
            state.filters[key] = key === 'query' ? String(patch[key]) : String(patch[key]);
        });
        return 'filters';
    }

    function dispatch(command) {
        if (!command || typeof command.type !== 'string') {
            throw new TypeError('VoicesV2 dispatch needs a command with a string type.');
        }
        return emit(reduce(command));
    }

    function select(selector) {
        if (typeof selector !== 'function') {
            throw new TypeError('VoicesV2 select needs a selector function.');
        }
        return selector(state);
    }

    function getState() {
        return state;
    }

    /* Test and future "discard everything" seam. Subscriptions survive, so a
     * reset cannot silently orphan a mounted panel. */
    function reset() {
        var mountedFlag = state.ui.mounted;
        state = createInitialState();
        state.ui.mounted = mountedFlag;
        return state;
    }

    namespace.state = {
        getState: getState,
        select: select,
        subscribe: subscribe,
        emit: emit,
        dispatch: dispatch,
        reset: reset,
        resolve: resolve,
        /* Published so the toolbar can render exactly the controls the store
         * accepts, and so a test can assert the two cannot drift apart. */
        schema: {
            filterKeys: FILTER_KEYS.slice(),
            sortKeys: SORT_KEYS.slice(),
            scopes: SCOPES.slice(),
            tristates: TRISTATE.slice(),
            priorities: PRIORITIES.slice(),
            problemModes: PROBLEM_MODES.slice()
        }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));