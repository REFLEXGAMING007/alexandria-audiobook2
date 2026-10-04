/* Voices V2 — tab lifecycle: mount / refresh / unmount, and isolated rendering.
 *
 * Nothing runs at load time. The Voices V2 workspace initialises the first
 * time activateTab('voicesv2') asks for it, which is the same trigger the
 * Voices tab uses for loadVoices() and which keeps Phase 0 free of any page
 * load cost.
 *
 * Three properties this file is responsible for:
 *
 *   Idempotent mount. A nav link fires activateTab() on every click, so mount()
 *     is called repeatedly for as long as the user stays on the tab. It binds
 *     exactly one click listener and issues at most one in-flight read; a
 *     second call while mounted re-reads rather than re-binding.
 *
 *   Scoped DOM. Every element touched is either the #voicesv2-tab root or a
 *     `[data-voicesv2-region]` descendant of it. The Voices tab's markup, ids,
 *     classes and globals are never read or written.
 *
 *   Cleanup that is safe when interrupted. unmount() flips `mounted` first and
 *     detaches the listener, so a read that was already in flight discards its
 *     result instead of painting into a torn-down tab.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var api = namespace.api;

    var ACTION_SELECTOR = '[data-voicesv2-action]';
    var listening = false;
    var inFlight = null;

    function isMounted() {
        return state.select(function (current) { return current.ui.mounted; });
    }

    function region(name) {
        var root = core.getRoot();
        return root ? root.querySelector('[data-voicesv2-region="' + name + '"]') : null;
    }

    function projectionCounts() {
        return state.select(function (current) {
            return { characters: current.characters.length, orphans: current.orphans.length };
        });
    }

    function statusMarkup() {
        var ui = state.select(function (current) { return current.ui; });
        if (ui.error) {
            return '<div class="alert alert-danger mb-0" role="alert">' + core.escape(ui.error) + '</div>';
        }
        if (ui.loading) {
            return '<div class="alert alert-secondary mb-0" role="status">Reading the Voices V2 projection...</div>';
        }
        var counts = projectionCounts();
        return '<div class="alert alert-info mb-0" role="status">'
            + 'Voices V2 &mdash; Phase 0 scaffold is ready. No voice features are enabled yet.'
            + '</div>'
            + '<p class="small text-muted mb-0 mt-2" data-voicesv2-part="counts">'
            + counts.characters + ' characters and ' + counts.orphans
            + ' orphan voice entries reported.</p>';
    }

    function liveText() {
        return state.select(function (current) {
            if (current.ui.loading) { return 'Loading'; }
            if (current.ui.error) { return 'Projection unavailable'; }
            return 'Ready';
        });
    }

    function detailText() {
        return state.select(function (current) {
            if (current.ui.loadedAt === null) { return ''; }
            return 'Projection read at ' + new Date(current.ui.loadedAt).toLocaleTimeString();
        });
    }

    function render() {
        /* No paint before mount, and none after unmount: an unmounted tab must
         * not leave live-region text behind for a screen reader. */
        if (!isMounted()) { return false; }
        var status = region('status');
        if (status) { status.innerHTML = statusMarkup(); }
        var live = region('live');
        if (live) { live.textContent = liveText(); }
        var detail = region('detail');
        if (detail) { detail.textContent = detailText(); }
        return true;
    }

    function onRootClick(event) {
        var origin = event && event.target;
        var action = origin && origin.closest ? origin.closest(ACTION_SELECTOR) : null;
        if (!action || !core.contains(action)) { return false; }
        if (action.getAttribute('data-voicesv2-action') !== 'reload') { return false; }
        refresh();
        return true;
    }

    function bindListener() {
        if (listening) { return false; }
        var root = core.getRoot();
        if (!root) { return false; }
        root.addEventListener('click', onRootClick);
        listening = true;
        return true;
    }

    function detachListener() {
        if (!listening) { return false; }
        var root = core.getRoot();
        if (root) { root.removeEventListener('click', onRootClick); }
        listening = false;
        return true;
    }

    function refresh() {
        if (!isMounted()) { return Promise.resolve(false); }
        /* One read at a time. Re-entering the tab, or clicking Reload while a
         * read is running, joins the in-flight read instead of stacking
         * requests against the backend. */
        if (inFlight) { return inFlight; }

        state.dispatch({ type: 'ui/error', error: null });
        state.dispatch({ type: 'ui/loading', loading: true });
        render();

        var pending = api.fetchCharacters().then(function (payload) {
            inFlight = null;
            if (!isMounted()) { return false; }
            state.dispatch({ type: 'characters/set', characters: (payload && payload.characters) || [] });
            state.dispatch({ type: 'orphans/set', orphans: (payload && payload.orphans) || [] });
            state.dispatch({ type: 'ui/loaded' });
            state.dispatch({ type: 'ui/loading', loading: false });
            render();
            return true;
        }, function (error) {
            inFlight = null;
            if (!isMounted()) { return false; }
            state.dispatch({ type: 'ui/loading', loading: false });
            state.dispatch({ type: 'ui/error', error: core.describeError(error) });
            render();
            /* Also surfaced in the tab, not only as a toast:
             * docs/UI_GUIDELINES.md forbids hiding an essential error in a
             * toast alone. The recovery text states plainly that the Voices tab
             * is unaffected, because a reader here cannot assume that. */
            core.notifyFailure('Voices V2 projection unavailable', error,
                'Voices V2 is a separate workspace and shares nothing with the Voices tab, '
                + 'so this does not affect voices you have already assigned. Reload the '
                + 'projection when Alexandria is reachable.');
            return false;
        });

        inFlight = pending;
        return pending;
    }

    function mount() {
        if (!core.getRoot()) { return Promise.resolve(false); }
        if (isMounted()) { return refresh(); }
        state.dispatch({ type: 'ui/mounted', mounted: true });
        bindListener();
        render();
        return refresh();
    }

    function unmount() {
        if (!isMounted()) { return false; }
        state.dispatch({ type: 'ui/mounted', mounted: false });
        detachListener();
        state.dispatch({ type: 'ui/loading', loading: false });
        /* Any read still in flight keeps its promise but discards its result:
         * both continuations re-check isMounted() before touching the store. */
        inFlight = null;
        return true;
    }

    namespace.lifecycle = {
        mount: mount,
        refresh: refresh,
        unmount: unmount,
        isMounted: isMounted,
        render: render
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));