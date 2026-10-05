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
            /* The assignable voice catalogue, also a server projection. */
            catalogue: createInitialCatalogue(),
            library: {},
            /* Session state. Lost on reload, never sent to the server. */
            selection: createInitialSelection(),
            filters: createInitialFilters(),
            /* The Voice Library's own state, kept apart from the character
             * browser's so neither can read the other's narrowing by accident. */
            library: createInitialLibrary(),
            librarySearch: '',
            libraryFilters: createInitialLibraryFilters(),
            librarySort: { key: 'name', direction: 'asc' },
            /* Which character the library is currently reasoning about. Null when
             * it is open as a plain browser. */
            libraryContext: { key: null, name: null, gender: null, ageGroup: null,
                              ageless: false },
            /* The navigation cursor: which card Previous/Next/Dice act on. This is
             * deliberately NOT the draft. The draft is the choice that would be
             * saved; the cursor is only where the user is looking, so moving
             * through voices never looks like an edit. */
            librarySelection: { cursor: null },
            /* One preview at a time, owned by library/audio.js. */
            preview: { voiceId: null, state: 'idle', error: null },
            /* The one unsaved voice edit. Phase 2 is single-character, so there is
             * deliberately one draft and not a map of them; `dirty` is the only
             * thing that makes it worth protecting. */
            draft: createInitialDraft(),
            save: createInitialSave(),
            ui: {
                mounted: false,
                loading: false,
                error: null,
                loadedAt: null
            }
        };
    }

    /* The two fields the guarded save contract needs, plus the catalogue
     * enumerations and the book-level facts the toolbar and editor read. */
    function createInitialMeta() {
        return {
            schemaVersion: null,
            /* `revision` changes when any voice configuration changes;
             * `book.token` changes when the active book changes. A save must
             * present both, and a refusal means the client's copy is stale. */
            revision: null,
            book: { bookId: null, token: null, scriptSha256: null, scriptPresent: false },
            traitsAvailable: false,
            traitsRequested: null,
            aliasesRegistered: false,
            majorLineThreshold: null,
            vocabularies: { genders: [], ageGroups: [], problemCodes: [] }
        };
    }

    function createInitialCatalogue() {
        return {
            voices: [],
            counts: { total: 0, available: 0, unavailable: 0 },
            kinds: [],
            favoriteKinds: [],
            warnings: [],
            unsupportedKinds: {},
            schemaVersion: null,
            loaded: false,
            error: null
        };
    }

    /* The library is open over the whole catalogue until a character gives it a
     * subject. */
    function createInitialLibrary() {
        return { open: false };
    }

    /* `context: 'suggested'` narrows by the selected character's traits. It is a
     * suggestion the user can switch off, never a restriction: a voice with
     * unknown metadata is never excluded for it. */
    function createInitialLibraryFilters() {
        return {
            gender: 'all',
            ageGroup: 'all',
            kind: 'all',
            availability: 'all',
            favorite: false,
            context: 'off'
        };
    }

    /* `pending` is a selection the guard refused, and `blocked` says so. The
     * detail view offers a choice instead of discarding the draft. */
    function createInitialSelection() {
        return { key: null, pending: null, blocked: false };
    }

    /* `voiceId: null` with `cleared: true` is the draft "remove this voice".
     * `characterKey` records whose draft this is, so a draft left over from a
     * previous character is never mistaken for this one's. */
    function createInitialDraft() {
        return { characterKey: null, voiceId: null, cleared: false, dirty: false };
    }

    /* One state at a time, and always with a message: the UI must never show a
     * colour without saying what happened. */
    var SAVE_STATES = ['idle', 'saving', 'saved', 'error', 'conflict'];

    function createInitialSave() {
        return { state: 'idle', message: null, code: null, savedAt: null };
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

    /* Two sort vocabularies, because they belong to two different panels: the
     * character browser ranks characters, the library ranks voices. Sharing one
     * list would force a meaningless option into one of them. */
    var SORT_KEYS = ['name', 'lineCount', 'priority', 'voiceStatus', 'voice', 'ready',
                     'traitOrder'];

    var LIBRARY_SORT_KEYS = ['name', 'favorite', 'availability', 'kind', 'gender', 'age',
                             'recent'];

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
            case 'catalogue/set':
                if (!command.catalogue || typeof command.catalogue !== 'object' ||
                        Array.isArray(command.catalogue)) {
                    throw new TypeError('VoicesV2 command "catalogue/set" needs an object "catalogue".');
                }
                state.catalogue = {
                    voices: Array.isArray(command.catalogue.voices) ? command.catalogue.voices : [],
                    counts: command.catalogue.counts || { total: 0, available: 0, unavailable: 0 },
                    kinds: Array.isArray(command.catalogue.kinds) ? command.catalogue.kinds : [],
                    favoriteKinds: Array.isArray(command.catalogue.favorite_kinds)
                        ? command.catalogue.favorite_kinds
                        : (command.catalogue.favoriteKinds || []),
                    warnings: Array.isArray(command.catalogue.warnings)
                        ? command.catalogue.warnings : [],
                    unsupportedKinds: command.catalogue.unsupported_kinds ||
                        command.catalogue.unsupportedKinds || {},
                    schemaVersion: typeof command.catalogue.schema_version === 'number'
                        ? command.catalogue.schema_version : null,
                    loaded: true,
                    error: null
                };
                return 'catalogue';
            case 'catalogue/voices':
                if (!Array.isArray(command.voices)) {
                    throw new TypeError('VoicesV2 command "catalogue/voices" needs an array "voices".');
                }
                state.catalogue.voices = command.voices;
                return 'catalogue';
            case 'catalogue/error':
                state.catalogue = Object.assign({}, state.catalogue, {
                    loaded: true, error: String(command.error)
                });
                return 'catalogue';
            case 'selection/set':
                return reduceSelection(command);
            case 'selection/acceptPending':
                /* The user chose to switch and lose the draft. Only reachable
                 * when a switch is actually blocked, so this cannot silently
                 * discard an edit. */
                if (!state.selection.blocked || !state.selection.pending) { return 'selection'; }
                state.selection.key = state.selection.pending;
                state.selection.pending = null;
                state.selection.blocked = false;
                state.draft = createInitialDraft();
                state.save = createInitialSave();
                return 'selection';
            case 'selection/cancelPending':
                state.selection.pending = null;
                state.selection.blocked = false;
                state.save = createInitialSave();
                return 'selection';
            case 'draft/choose':
                return reduceDraftChoice(command.voiceId);
            case 'draft/clearVoice':
                return reduceDraftChoice(null, true);
            case 'draft/discard':
                state.draft = createInitialDraft();
                state.save = createInitialSave();
                return 'draft';
            case 'draft/reset':
                state.draft = createInitialDraft();
                return 'draft';
            case 'save/start':
                state.save = { state: 'saving', message: null, code: null, savedAt: null };
                return 'save';
            case 'save/succeeded':
                state.save = { state: 'saved', message: null, code: null, savedAt: Date.now() };
                return 'save';
            case 'save/failed':
                state.save = {
                    state: 'error',
                    message: String(command.message),
                    code: command.code === undefined || command.code === null ? null : String(command.code),
                    savedAt: null
                };
                return 'save';
            case 'save/conflict':
                /* A stale snapshot. The draft is deliberately left in place: the
                 * user chose a voice, and throwing that away for them would lose
                 * work they can still reapply once they have seen the latest
                 * state. */
                state.save = {
                    state: 'conflict',
                    message: String(command.message),
                    code: command.code === undefined || command.code === null
                        ? 'stale_snapshot' : String(command.code),
                    savedAt: null
                };
                return 'save';
            case 'save/reset':
                state.save = createInitialSave();
                return 'save';
            case 'filters/patch':
                return reduceFilterPatch(command);
            case 'library/open':
                return reduceLibraryOpen(command);
            case 'library/close':
                state.library.open = false;
                /* The context is dropped with the panel: leaving it behind would
                 * silently narrow the next time the library is opened. */
                state.libraryContext = createInitialLibraryContext();
                state.librarySelection.cursor = null;
                return 'library';
            case 'library/search':
                state.librarySearch = command.query === null || command.query === undefined
                    ? '' : String(command.query);
                return 'librarySearch';
            case 'library/filters':
                return reduceLibraryFilterPatch(command.patch);
            case 'library/sort':
                if (LIBRARY_SORT_KEYS.indexOf(String(command.key)) < 0) {
                    throw new Error('Voices V2 cannot sort the library by "' + command.key + '".');
                }
                if (['asc', 'desc'].indexOf(String(command.direction)) < 0) {
                    throw new Error('Voices V2 sort direction must be asc or desc.');
                }
                state.librarySort = { key: String(command.key), direction: String(command.direction) };
                return 'librarySort';
            case 'library/resetFilters':
                state.libraryFilters = createInitialLibraryFilters();
                state.librarySearch = '';
                return 'libraryFilters';
            case 'library/cursor':
                state.librarySelection.cursor = (command.voiceId === undefined)
                    ? null : command.voiceId;
                return 'librarySelection';
            case 'preview/start':
                state.preview = { voiceId: command.voiceId, state: 'loading', error: null };
                return 'preview';
            case 'preview/playing':
                state.preview = { voiceId: command.voiceId, state: 'playing', error: null };
                return 'preview';
            case 'preview/failed':
                state.preview = { voiceId: command.voiceId, state: 'error',
                                 error: String(command.error) };
                return 'preview';
            case 'preview/stop':
                state.preview = { voiceId: null, state: 'idle', error: null };
                return 'preview';
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

    /* Switching characters is the one navigation that can lose work, so the guard
     * lives in the reducer rather than in a panel: dispatch is the only writer,
     * so a guard anywhere else could be bypassed by the next panel that forgets
     * it. A dirty draft for another character blocks the switch and records it as
     * pending; the detail view then offers stay / discard / save. */
    function reduceSelection(command) {
        if (command.key !== null && typeof command.key !== 'string') {
            throw new TypeError('VoicesV2 command "selection/set" needs a string key or null.');
        }
        var draft = state.draft;
        var belongsElsewhere = draft.dirty && draft.characterKey && command.key !== draft.characterKey;
        if (belongsElsewhere) {
            state.selection.pending = command.key;
            state.selection.blocked = true;
            /* A blocked switch is not a save error, so `save` keeps its own state
             * and only the explanation is cleared. */
            state.save = Object.assign({}, state.save, { message: null });
            return 'selection';
        }
        state.selection.key = command.key;
        state.selection.pending = null;
        state.selection.blocked = false;
        if (!draft.dirty || draft.characterKey === command.key) {
            /* A clean draft is not work; forgetting it is not a loss. */
            state.draft = createInitialDraft();
            state.save = createInitialSave();
        }
        return 'selection';
    }

    /* The first edit of a character's draft adopts that character; later edits
     * keep it. Nothing here writes anywhere - a draft is local state until Save
     * is pressed. */
    function reduceDraftChoice(voiceId, cleared) {
        var key = state.selection.key;
        if (!key) {
            throw new Error('VoicesV2 cannot draft a voice with no character selected.');
        }
        if (typeof voiceId !== 'string' && voiceId !== null) {
            throw new TypeError('VoicesV2 draft needs a voice id string or null.');
        }
        state.draft = {
            characterKey: key,
            voiceId: voiceId === undefined ? null : voiceId,
            cleared: cleared === true,
            dirty: true
        };
        /* Choosing again supersedes whatever the last attempt reported. */
        state.save = createInitialSave();
        return 'draft';
    }

    /* Opening the library always names its subject explicitly. With a character it
     * prefills the context so the filters have something to suggest; without one
     * it is a plain browser. Either way the open action records what it decided,
     * so the panel never has to re-derive it from the selection. */
    function reduceLibraryOpen(command) {
        var context = createInitialLibraryContext();
        if (command.key) {
            var character = findCharacter(command.key);
            if (!character) {
                throw new Error('Voices V2 cannot open the library for "' + command.key + '".');
            }
            context = {
                key: character.key,
                name: character.name,
                gender: (character.traits && character.traits.gender) || 'unknown',
                ageGroup: (character.traits && character.traits.ageGroup) || 'unknown',
                ageless: !!(character.traits && character.traits.ageless)
            };
        }
        state.libraryContext = context;
        state.library.open = true;
        state.librarySelection.cursor = null;
        return 'library';
    }

    function findCharacter(key) {
        var all = state.characters.concat(state.orphans);
        for (var index = 0; index < all.length; index += 1) {
            if (all[index].key === key) { return all[index]; }
        }
        return null;
    }

    function createInitialLibraryContext() {
        return { key: null, name: null, gender: null, ageGroup: null, ageless: false };
    }

    /* Only the six filters exist, and only these values are accepted, so the
     * chips the panel renders can never describe a filter that is not applied. */
    var LIBRARY_FILTER_KEYS = ['gender', 'ageGroup', 'kind', 'availability', 'favorite',
                                'context'];
    var AVAILABILITY_MODES = ['all', 'available', 'unavailable'];
    var CONTEXT_MODES = ['off', 'suggested'];

    function reduceLibraryFilterPatch(patch) {
        if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
            throw new TypeError('VoicesV2 command "library/filters" needs an object "patch".');
        }
        var keys = Object.keys(patch);
        if (!keys.length) { return 'libraryFilters'; }
        keys.forEach(function (key) {
            if (LIBRARY_FILTER_KEYS.indexOf(key) < 0) {
                throw new Error('Voices V2 has no library filter named "' + key + '".');
            }
            if (key === 'favorite' && typeof patch[key] !== 'boolean') {
                throw new TypeError('VoicesV2 library filter "favorite" needs a boolean.');
            }
            var vocabulary = key === 'availability' ? AVAILABILITY_MODES
                : key === 'context' ? CONTEXT_MODES : null;
            if (vocabulary && vocabulary.indexOf(String(patch[key])) < 0) {
                throw new Error('Voices V2 library filter "' + key + '" does not accept "'
                    + patch[key] + '".');
            }
        });
        keys.forEach(function (key) {
            state.libraryFilters[key] = key === 'favorite'
                ? patch[key] : String(patch[key]);
        });
        return 'libraryFilters';
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
            problemModes: PROBLEM_MODES.slice(),
            saveStates: SAVE_STATES.slice(),
            libraryFilterKeys: LIBRARY_FILTER_KEYS.slice(),
            librarySortKeys: LIBRARY_SORT_KEYS.slice(),
            availabilityModes: AVAILABILITY_MODES.slice(),
            contextModes: CONTEXT_MODES.slice(),
            previewStates: ['idle', 'loading', 'playing', 'error']
        }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));