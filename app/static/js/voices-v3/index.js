/* Voices V3 — bootstrap.
 *
 * Wires the pieces together in dependency order and publishes one global. Nothing
 * runs at page load: the tab initialises the first time the Voices V3 nav link is
 * activated, so a session that never visits the tab pays nothing for it.
 *
 * Load order is a contract, enforced by the script tags in the page shell:
 *
 *   core -> state -> selectors -> api -> save -> widgets -> panels -> events
 *   -> actions -> lifecycle -> index
 *
 * Every module attaches to the same namespace object and reads its siblings at
 * call time rather than at load time, so the order only has to satisfy "defined
 * before the first render".
 */
(function (namespace) {
    'use strict';

    namespace.name = 'VoicesV3';
    namespace.phase = 1;
    namespace.root = namespace.core.ROOT_ID;

    /* The save controller is the one object that needs the store, the API, and a
     * re-read callback at construction time, so it is built here rather than in
     * any module. */
    namespace.saveController = namespace.save.createController({
        dispatch: namespace.state.dispatch,
        getState: namespace.state.getState,
        api: namespace.api,
        core: namespace.core,
        buildPayload: function () {
            return namespace.selectors.buildVoiceDocument(namespace.state.getState());
        },
        reload: function () {
            return namespace.lifecycle.loadAll();
        }
    });

    /* Flat republication so panels can reach the store's surface without knowing
     * where it lives. These are the same function references, so there is exactly
     * one dispatch path.
     */
    namespace.dispatch = namespace.state.dispatch;
    namespace.select = namespace.state.select;
    namespace.getState = namespace.state.getState;
    namespace.subscribe = namespace.state.subscribe;

    namespace.selectors = namespace.selectors;
    namespace.panels = {
        toolbar: namespace.toolbarPanel,
        personas: namespace.personasPanel,
        roster: namespace.rosterPanel,
        states: namespace.statesPanel,
        suggestions: namespace.suggestionsPanel,
        cast: namespace.castPanel,
        card: namespace.cardPanel
    };

    namespace.mount = namespace.lifecycle.mount;
    namespace.unmount = namespace.lifecycle.unmount;
    namespace.refresh = namespace.lifecycle.reloadVoices;

    if (!window[namespace.name]) {
        window[namespace.name] = namespace;
    }

    /* Guard for a restored or URL-selected tab: app-core activates it through
     * `VoicesV3.mount()`, but restoreTab() can land here before that runs. */
    if (document.readyState !== 'loading') {
        try {
            window.addEventListener('hashchange', function () {
                if (window.location.hash === '#voicesv3' && namespace.lifecycle.isMounted()) {
                    namespace.lifecycle.mount();
                }
            });
        } catch (error) { /* non-fatal */ }
    }
}(window.VoicesV3 || (window.VoicesV3 = {})));