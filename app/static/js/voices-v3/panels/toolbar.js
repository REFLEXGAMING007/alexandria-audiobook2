/* Voices V3 — the toolbar.
 *
 * Holds every control that is not per-character: narrator strategy, the apply-to
 * scope, the persona knobs, the ready count, the hide-ready switch, and the save
 * status.
 *
 * Controls here are static markup in the page shell. This panel fills option lists
 * and writes values, and it writes a control only when the value differs — so a
 * select the user is interacting with is never rebuilt underneath them.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var labels = namespace.labels;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var escape = core.escape;

    var bound = false;
    var populatedSignature = null;

    function control(name) {
        var region = core.region('toolbar');
        return region ? region.querySelector('[data-voicesv3-control="' + name + '"]') : null;
    }

    function signature(state) {
        return [
            state.meta.revision,
            selectors.selectNarratorStrategy(state),
            state.narrator.previewFocus,
            state.narrator.previewVersion,
            state.view.scope,
            state.view.hideReady,
            state.persona.advanced,
            state.persona.contextLines,
            state.persona.running,
            state.meta.bookToken
        ].join('|');
    }

    /* Option lists are only rebuilt when the inputs that define them change. */
    function populate(state) {
        var current = signature(state);
        if (current === populatedSignature) { return; }
        populatedSignature = current;

        var strategy = control('narrator-strategy');
        if (strategy && !strategy.dataset.populated) {
            strategy.innerHTML = labels.NARRATOR_STRATEGIES.map(function (entry) {
                return markup.option(entry.value, entry.label, false);
            }).join('');
            strategy.dataset.populated = '1';
        }

        var scope = control('scope');
        if (scope) {
            var options = selectors.selectScopeOptions(state);
            scope.options[0].textContent = options.pending;
            scope.options[1].textContent = options.all;
        }

        var context = control('persona-context');
        if (context && !context.dataset.populated) {
            context.innerHTML = labels.PERSONA_CONTEXT_OPTIONS.map(function (entry) {
                return markup.option(entry.value, entry.label, false);
            }).join('');
            context.dataset.populated = '1';
        }
    }

    function writeValue(element, value) {
        if (!element) { return; }
        var next = value === null || value === undefined ? '' : String(value);
        if (element.value !== next) { element.value = next; }
    }

    function writeChecked(element, value) {
        if (!element) { return; }
        var next = !!value;
        if (element.checked !== next) { element.checked = next; }
    }

    function writeText(element, value) {
        if (!element) { return; }
        var next = value === null || value === undefined ? '' : String(value);
        if (element.textContent !== next) { element.textContent = next; }
    }

    function writeVisible(element, visible) {
        if (!element) { return; }
        var next = visible ? '' : 'none';
        if (element.style.display !== next) { element.style.display = next; }
    }

    function writeDisabled(element, disabled) {
        if (!element) { return; }
        if (element.disabled !== !!disabled) { element.disabled = !!disabled; }
    }

    function sync(state) {
        populate(state);

        var storedStrategy = selectors.selectNarratorStrategy(state);
        var effectiveScope = selectors.resolveScope(state);
        var options = selectors.selectScopeOptions(state);
        var preview = selectors.selectNarratorPreviewControls(state);

        writeValue(control('narrator-strategy'), state.narrator.strategy || storedStrategy);
        writeText(control('narrator-preview-status'), state.narrator.status || '');
        writeDisabled(control('narrator-preview'), !!state.narrator.previewing);

        var focus = control('narrator-focus');
        var focusGroup = control('narrator-focus-group');
        writeVisible(focusGroup, preview.focus.length > 0);
        if (focus && focus.dataset.signature !== String(preview.focus.length)) {
            focus.innerHTML = preview.focus.map(function (entry) {
                return markup.option(entry.value, entry.label, false);
            }).join('');
            focus.dataset.signature = String(preview.focus.length);
        }
        writeValue(focus, state.narrator.previewFocus);

        var version = control('narrator-version');
        var versionGroup = control('narrator-version-group');
        writeVisible(versionGroup, preview.version.length > 1);
        if (version && version.dataset.signature !== String(preview.version.length)) {
            version.innerHTML = preview.version.map(function (entry) {
                return markup.option(entry.value, entry.label, false);
            }).join('');
            version.dataset.signature = String(preview.version.length);
        }
        writeValue(version, state.narrator.previewVersion);

        writeValue(control('scope'), effectiveScope);
        writeVisible(control('keep-wrap'), options.showKeepCheckbox);
        writeText(control('keep-cast'), options.keepLabel);
        writeChecked(control('keep-in-library'), state.persona.keepInLibrary);

        writeChecked(control('persona-advanced'), state.persona.advanced);
        writeVisible(control('persona-batch'), !!state.persona.advanced);
        writeValue(control('persona-batch-size'), state.persona.batchSize);
        writeValue(control('persona-context'), state.persona.contextLines);
        writeVisible(control('persona-context-custom-input'), state.persona.contextLines !== 'custom');
        writeValue(control('persona-context-custom-input'), state.persona.contextCustom);
        writeText(control('persona-status'), state.persona.status || '');

        writeVisible(control('persona-cancel'), !!state.persona.running);
        writeDisabled(control('persona-generate'), !!state.persona.running);

        var ready = selectors.selectReadySummary(state);
        writeText(control('ready-count'), ready.label);
        writeChecked(control('hide-ready'), state.view.hideReady);

        var statusText = state.save.state === 'saved'
            ? '<i class="fas fa-check text-success me-1"></i>saved'
            : (state.save.message || '');
        var status = control('save-status');
        if (status) {
            var isMessage = state.save.state !== 'saved';
            if (isMessage && state.save.message) {
                status.innerHTML = '<i class="fas fa-times text-danger me-1"></i>' + escape(state.save.message)
                    + ' <button type="button" class="btn btn-link btn-sm" data-voicesv3-action="save-discard">'
                    + 'Discard edits and reload</button>';
            } else {
                status.innerHTML = statusText;
            }
        }

        writeText(control('persona-refresh-status'), state.persona.resourcesStatus || '');
        writeVisible(control('persona-refresh-retry'), !!state.persona.resourcesStatus);
    }

    function bind() {
        if (bound) { return; }
        var region = core.region('toolbar');
        if (!region) { return; }
        region.addEventListener('change', namespace.events.onToolbarChange);
        region.addEventListener('input', namespace.events.onToolbarInput);
        region.addEventListener('click', namespace.events.onToolbarClick);
        bound = true;
    }

    function unbind() { /* delegated listeners live on the shell, not on rendered markup */ }

    function mount() { bind(); }

    namespace.toolbarPanel = {
        mount: mount,
        bind: bind,
        unbind: unbind,
        sync: sync,
        control: control
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));