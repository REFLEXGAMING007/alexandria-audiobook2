/* Voices V2 — bootstrap. Loaded last, after every Voices V2 dependency.
 *
 * Two jobs: publish the public surface, and guarantee the workspace is mounted
 * if the tab is already the visible one.
 *
 * Publishing the surface here rather than in each file keeps the contract
 * reviewable in one place, and means a future panel can be added without
 * widening what the namespace exposes. The state read/write surface is
 * republished flat because that is the ergonomic entry point for panels; it
 * holds the same function references as `state`, so there is exactly one
 * dispatch path (CLAUDE.md Rule 15). `api` and `state` stay attached as the
 * module-level detail they are.
 *
 * The usual path into Voices V2 is activateTab('voicesv2') -> mount(). The
 * guard below is a second path: restoreTab() runs at the end of app-reports.js,
 * which loads after these files, so if a stored or URL tab is voicesv2 the
 * mount already happened before this line runs. The guard exists so that a
 * future script-order change degrades to a redundant mount() call — which is a
 * no-op — rather than to a tab that renders nothing.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var lifecycle = namespace.lifecycle;

    namespace.phase = 0;
    namespace.root = core.ROOT_ID;

    namespace.mount = lifecycle.mount;
    namespace.refresh = lifecycle.refresh;
    namespace.unmount = lifecycle.unmount;
    namespace.isMounted = lifecycle.isMounted;

    namespace.getState = state.getState;
    namespace.select = state.select;
    namespace.subscribe = state.subscribe;
    namespace.dispatch = state.dispatch;

    var root = core.getRoot();
    if (root && root.style.display === 'block' && !lifecycle.isMounted()) {
        lifecycle.mount();
    }
}(window.VoicesV2 || (window.VoicesV2 = {})));