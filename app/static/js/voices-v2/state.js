/* Voices V2 — the store: state, subscribe, emit, dispatch, select.
 *
 * The store partitions state the way every later phase needs:
 *
 *   characters, orphans, catalogue, library  server projections. Owned by the
 *                                             backend, replaced wholesale by a
 *                                             read, never assembled in the DOM.
 *   selection, filters                         V2 session state. Lost on reload,
 *                                             never sent to the server.
 *   ui                                         lifecycle state owned by
 *                                             lifecycle.js.
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
 * `getState()` hands back the live object for cheap reads, the way a plain
 * JavaScript store does. Treat it as read-only; `select()` is the safer read
 * for anything that will be stored past the current tick.
 */
(function (namespace) {
    'use strict';

    function createInitialState() {
        return {
            characters: [],
            orphans: [],
            catalogue: [],
            library: {},
            selection: {},
            filters: {},
            ui: {
                mounted: false,
                loading: false,
                error: null,
                loadedAt: null
            }
        };
    }

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
            case 'characters/set':
                state.characters = requireArray(command, 'characters');
                return 'characters';
            case 'orphans/set':
                state.orphans = requireArray(command, 'orphans');
                return 'orphans';
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
        resolve: resolve
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));