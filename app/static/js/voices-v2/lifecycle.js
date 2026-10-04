/* Voices V2 — tab lifecycle: mount / refresh / unmount, and render orchestration.
 *
 * Nothing runs at load time. The Voices V2 workspace initialises the first time
 * activateTab('voicesv2') asks for it, which is the same trigger the Voices tab
 * uses for loadVoices() and which keeps Phase 1 free of any page-load cost.
 *
 * Four properties this file is responsible for:
 *
 *   Idempotent mount. A nav link fires activateTab() on every click, so mount()
 *     is called repeatedly for as long as the user stays on the tab. It binds
 *     each panel's listeners exactly once and issues at most one in-flight read;
 *     a second call while mounted re-reads rather than re-binding.
 *
 *   Scoped DOM. Every element touched is the #voicesv2-tab root or a
 *     `[data-voicesv2-region]` descendant of it. The Voices tab's markup, ids,
 *     classes and globals are never read or written.
 *
 *   Cleanup that is safe when interrupted. unmount() flips the mounted flag
 *     first, so a read that was already in flight discards its result instead of
 *     painting into a torn-down tab.
 *
 *   One path from a read to a view. The response is adapted once
 *     (selectors.adaptProjection) and handed to the store; panels render from
 *     the store and never see the wire shape.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var api = namespace.api;
    var selectors = namespace.selectors;
    var states = namespace.states;
    var toolbar = namespace.toolbar;
    var charactersPanel = namespace.charactersPanel;
    var detailPanel = namespace.detailPanel;

    var ACTION_SELECTOR = '[data-voicesv2-action]';
    var listening = false;
    var inFlight = null;
    var stopRenderSubscription = null;
    var renderQueued = false;

    var PANELS = [toolbar, charactersPanel, detailPanel];

    /* Published so the set of panels is discoverable in one place: a new panel
     * is added here and nowhere else, and a test can assert the roster. */
    namespace.panels = {
        toolbar: toolbar,
        charactersPanel: charactersPanel,
        detailPanel: detailPanel
    };

    function isMounted() {
        return state.select(function (current) { return current.ui.mounted; });
    }

    function region(name) {
        return core.region(name);
    }

    /* Loading, error and the book-level banners all live in one region, above the
     * controls. Detail problems live in the detail panel instead, because a
     * warning about one character should not look like a warning about the read.
     * The error and the loading state are mutually exclusive, so the error wins;
     * the two book-level notices are independent and may both apply. */
    function statusMarkup(nextState) {
        if (nextState.ui.error) { return states.errorMarkup(nextState.ui.error); }
        if (nextState.ui.loading) { return states.loadingMarkup(); }
        if (nextState.meta.schemaVersion === null) { return ''; }
        return states.traitsBanner(nextState.meta) + states.aliasesBanner(nextState.meta);
    }

    function liveText(nextState) {
        if (nextState.ui.loading) { return 'Loading'; }
        if (nextState.ui.error) { return 'Projection unavailable'; }
        if (nextState.meta.schemaVersion === null) { return 'Not loaded'; }
        var summary = selectors.selectSummary(nextState);
        return summary.shown + ' of ' + summary.total + ' characters';
    }

    /* Panels are the only writers of panel markup; this only decides what the
     * tab says about the read itself. */
    function render() {
        if (!isMounted()) { return false; }
        var nextState = state.getState();

        toolbar.sync(nextState);
        charactersPanel.render(nextState);
        detailPanel.render(nextState);

        var status = region('status');
        if (status) { status.innerHTML = statusMarkup(nextState); }
        var live = region('live');
        if (live) { live.textContent = liveText(nextState); }
        return true;
    }

    /* One subscription, one render path.
     *
     * Every dispatch paints the affected regions, so a filter change needs no
     * panel to know that anything else must be redrawn, and a new panel inherits
     * that for free. Renders are coalesced onto a microtask because one read
     * dispatches several commands (meta, characters, orphans, ui), and painting
     * the list once per dispatch would rebuild the same markup several times.
     */
    function scheduleRender() {
        if (renderQueued) { return false; }
        renderQueued = true;
        Promise.resolve().then(function () {
            renderQueued = false;
            render();
        });
        return true;
    }

    function bindStore() {
        if (stopRenderSubscription) { return false; }
        stopRenderSubscription = state.subscribe('*', scheduleRender);
        return true;
    }

    function unbindStore() {
        if (!stopRenderSubscription) { return false; }
        stopRenderSubscription();
        stopRenderSubscription = null;
        return true;
    }

    function onRootClick(event) {
        var origin = event && event.target;
        var action = origin && origin.closest ? origin.closest(ACTION_SELECTOR) : null;
        if (!action || !core.contains(action)) { return false; }
        var name = action.getAttribute('data-voicesv2-action');
        if (name === 'reload' || name === 'retry') {
            refresh();
            return true;
        }
        if (name === 'clear-filters') {
            state.dispatch({ type: 'filters/reset' });
            return true;
        }
        return false;
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

    /* Applies a successful read. Every continuation re-checks isMounted() before
     * touching the store, so an unmounted tab is never written into. */
    function applyPayload(payload) {
        var adapted = selectors.adaptProjection(payload);
        state.dispatch({ type: 'meta/set', meta: adapted.meta });
        state.dispatch({ type: 'characters/set', characters: adapted.characters });
        state.dispatch({ type: 'orphans/set', orphans: adapted.orphans });
        state.dispatch({ type: 'ui/loaded' });
        state.dispatch({ type: 'ui/loading', loading: false });
        /* A selection that no longer exists would leave the detail panel blank
         * with no explanation, so it is dropped when the roster changes under it. */
        var selected = state.getState().selection.key;
        if (selected && !selectors.findByKey(state.getState(), selected)) {
            state.dispatch({ type: 'selection/set', key: null });
        }
        toolbar.mount(state.getState());
    }

    function refresh() {
        if (!isMounted()) { return Promise.resolve(false); }
        /* One read at a time. Re-entering the tab, or clicking Retry while a read
         * is running, joins the in-flight read instead of stacking requests. */
        if (inFlight) { return inFlight; }

        state.dispatch({ type: 'ui/error', error: null });
        state.dispatch({ type: 'ui/loading', loading: true });

        var pending = api.fetchCharacters().then(function (payload) {
            inFlight = null;
            if (!isMounted()) { return false; }
            applyPayload(payload);
            return true;
        }, function (error) {
            inFlight = null;
            if (!isMounted()) { return false; }
            state.dispatch({ type: 'ui/loading', loading: false });
            state.dispatch({ type: 'ui/error', error: core.describeError(error) });
            /* Also surfaced in the tab, not only as a toast:
             * docs/UI_GUIDELINES.md forbids hiding an essential error in a toast
             * alone. The recovery text states plainly that the Voices tab is
             * unaffected, because a reader here cannot assume that. */
            core.notifyFailure('Voices V2 projection unavailable', error,
                'Voices V2 is a separate workspace and shares nothing with the Voices tab, '
                + 'so this does not affect voices you have already assigned. Use Retry in the '
                + 'Voices V2 tab when Alexandria is reachable.');
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
        bindStore();
        /* Panels bind before the first render so a click during the in-flight read
         * is handled rather than dropped. */
        PANELS.forEach(function (panel) {
            if (panel && typeof panel.mount === 'function') { panel.mount(state.getState()); }
        });
        render();
        return refresh();
    }

    function unmount() {
        if (!isMounted()) { return false; }
        /* Unsubscribe before the final dispatches: a torn-down tab must not
         * schedule a paint. */
        unbindStore();
        state.dispatch({ type: 'ui/mounted', mounted: false });
        detachListener();
        PANELS.forEach(function (panel) {
            if (panel && typeof panel.unmount === 'function') { panel.unmount(); }
        });
        state.dispatch({ type: 'ui/loading', loading: false });
        /* Any read still in flight keeps its promise but discards its result:
         * the continuation re-checks isMounted() before touching the store. */
        inFlight = null;
        return true;
    }

    namespace.lifecycle = {
        mount: mount,
        refresh: refresh,
        unmount: unmount,
        isMounted: isMounted,
        render: render,
        scheduleRender: scheduleRender,
        applyPayload: applyPayload,
        statusMarkup: statusMarkup,
        liveText: liveText
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));