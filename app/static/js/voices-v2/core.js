/* Voices V2 — namespace root and shared-infrastructure boundary.
 *
 * Voices V2 is a standalone feature domain that runs beside the Voices tab.
 * It owns exactly one global, `window.VoicesV2`; every other file attaches a
 * small, explicit export to it from inside its own closure, so implementation
 * detail never reaches the global scope.
 *
 * Shared infrastructure is reached through the accessors below and only from
 * here. V2 depends on app-wide helpers whose behaviour is stable (API,
 * escapeHtml, showToast, showActionError) and never on Voices-page internals
 * such as createVoiceCard, collectVoiceConfig, window._voicesByName,
 * window._voiceSuggestions, window._selectedCast, or the Voices tab DOM.
 * CLAUDE.md Rule 15 forbids parallel copies of a dispatch path: a V2 HTTP
 * client or escaping helper would be exactly that.
 */
(function () {
    'use strict';

    var NAMESPACE = 'VoicesV2';
    var ROOT_ID = 'voicesv2-tab';

    /* The only DOM element V2 ever looks up by id is its own tab root.
     * Everything else is reached as a descendant region, so a V2 selector can
     * never reach into another tab's markup. */
    function getRoot() {
        return document.getElementById(ROOT_ID);
    }

    /* Every V2-owned element is a `[data-voicesv2-region]` descendant of that
     * root, addressed by name. Panels therefore cannot reach a V2 element by
     * guessing an id, and cannot reach outside the tab at all. */
    function region(name) {
        var root = getRoot();
        return root ? root.querySelector('[data-voicesv2-region="' + name + '"]') : null;
    }

    function contains(node) {
        var root = getRoot();
        return !!(root && node && root.contains(node));
    }

    function escape(value) {
        return escapeHtml(value);
    }

    function notify(message, type, duration) {
        return showToast(message, type, duration);
    }

    function notifyFailure(action, error, recovery) {
        return showActionError(action, error, recovery);
    }

    /* A short inline summary for the tab's own error region. The shared
     * showActionError helper owns the full toast copy; this only needs enough
     * to identify the failure inside the tab, because
     * docs/UI_GUIDELINES.md forbids hiding an error in a toast alone. */
    function describeError(error) {
        var detail = (error && error.message) ? error.message : String(error);
        return 'Projection read failed: ' + detail;
    }

    var core = {
        NAMESPACE: NAMESPACE,
        ROOT_ID: ROOT_ID,
        getRoot: getRoot,
        region: region,
        contains: contains,
        escape: escape,
        notify: notify,
        notifyFailure: notifyFailure,
        describeError: describeError
    };

    window[NAMESPACE] = window[NAMESPACE] || {};
    window[NAMESPACE].core = core;
}());