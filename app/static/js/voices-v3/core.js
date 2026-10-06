/* Voices V3 — namespace root and shared-infrastructure boundary.
 *
 * This is the ONLY file in Voices V3 permitted to reach for the application-wide
 * helpers that the legacy Voices tab owns. Everything else goes through `core`,
 * so there is exactly one place where Voices V3 touches shared runtime.
 *
 * The feature set is a deliberate replica of the original Voices tab. The
 * implementation is not: the working configuration lives in a store rather than
 * in the DOM, so the save payload is computed from state instead of scraped from
 * markup.
 */
(function (namespace) {
    'use strict';

    var ROOT_ID = 'voicesv3-tab';
    var NAMESPACE_NAME = 'VoicesV3';

    // The single id lookup in all of Voices V3. Everything else is addressed by
    // `data-voicesv3-region`, so the tab owns no other global id.
    function getRoot() {
        return document.getElementById(ROOT_ID);
    }

    function region(name) {
        var root = getRoot();
        return root ? root.querySelector('[data-voicesv3-region="' + name + '"]') : null;
    }

    function regions() {
        var root = getRoot();
        if (!root) { return []; }
        return Array.prototype.slice.call(root.querySelectorAll('[data-voicesv3-region]'));
    }

    function contains(node) {
        var root = getRoot();
        return !!(root && node && (node === root || root.contains(node)));
    }

    /* ---- shared helpers, taken from the application runtime ---- */

    function escape(value) {
        return window.escapeHtml(value);
    }

    function notify(message, kind, duration) {
        return window.showToast(message, kind, duration);
    }

    function notifyFailure(action, error, recovery, kind) {
        return window.showActionError(action, error, recovery, kind);
    }

    function confirmDialog(message, options) {
        return window.showConfirm(message, options || {});
    }

    function describeError(error) {
        if (!error) { return 'Unknown error.'; }
        if (typeof error.message === 'string' && error.message) { return error.message; }
        return String(error);
    }

    /* ---- one managed audio element, so a preview can never stack ---- */

    var audioFactory = function () {
        var element = new Audio();
        element.preload = 'none';
        return element;
    };
    var audioElement = null;
    var audioVoice = null;

    function ensureAudio() {
        if (!audioElement) { audioElement = audioFactory(); }
        return audioElement;
    }

    function playClip(url) {
        stopClip();
        var element = ensureAudio();
        audioVoice = url;
        element.src = url;
        var done = false;
        var finish = function () {
            if (done) { return; }
            done = true;
            element.onended = null;
            element.onerror = null;
            if (audioVoice === url) { audioVoice = null; }
        };
        element.onended = finish;
        element.onerror = finish;
        var result = element.play();
        if (result && typeof result.catch === 'function') { result.catch(finish); }
        return url;
    }

    function stopClip() {
        if (!audioElement) { return; }
        audioElement.onended = null;
        audioElement.onerror = null;
        try { audioElement.pause(); } catch (error) { /* pause can throw on a dead element */ }
        try { audioElement.removeAttribute('src'); } catch (error) { /* ignore */ }
        audioVoice = null;
    }

    function currentClip() { return audioVoice; }

    function setAudioFactory(factory) { audioFactory = factory; audioElement = null; }

    namespace.core = {
        ROOT_ID: ROOT_ID,
        NAMESPACE_NAME: NAMESPACE_NAME,
        getRoot: getRoot,
        region: region,
        regions: regions,
        contains: contains,
        escape: escape,
        notify: notify,
        notifyFailure: notifyFailure,
        confirm: confirmDialog,
        describeError: describeError,
        playClip: playClip,
        stopClip: stopClip,
        currentClip: currentClip,
        setAudioFactory: setAudioFactory,
        option: function (value, label, selected, disabled) {
            return '<option value="' + escape(value) + '"' + (selected ? ' selected' : '')
                + (disabled ? ' disabled' : '') + '>' + escape(label) + '</option>';
        },
        badge: function (text, kind, extraClass) {
            return '<span class="badge ' + (kind || 'bg-secondary') + (extraClass ? ' ' + extraClass : '')
                + '">' + escape(text) + '</span>';
        }
    };

    if (!window[NAMESPACE_NAME]) {
        window[NAMESPACE_NAME] = namespace;
    }
}(window.VoicesV3 || (window.VoicesV3 = {})));