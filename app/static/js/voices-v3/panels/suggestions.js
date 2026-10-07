/* Voices V3 — the suggestion system.
 *
 * The original tab asks the configured LLM to match each character to the
 * best-fitting downloaded LoRA voice, then lets the user apply one, apply all, or
 * dismiss. Suggestions live only in the session: applying one persists it as a
 * candidate, dismissing loses it, and a reload starts clean.
 *
 * A catalogue problem is reported in its own region rather than thrown, because
 * the roster is still perfectly browsable without a voice list and a whole-tab
 * error banner would misdescribe that.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var escape = core.escape;

    function attr(value) { return escape(value); }

    function container(name) {
        var host = core.region('roster');
        if (!host) { return null; }
        return host.querySelector('[data-voicesv3-suggestions="' + String(name).replace(/"/g, '\\"') + '"]');
    }

    function toolbarControl(name) {
        var region = core.region('toolbar');
        return region ? region.querySelector('[data-voicesv3-control="' + name + '"]') : null;
    }

    /* ---- rendering ---- */

    function candidateRow(name, candidate) {
        var label = candidate.adapter_name || candidate.name || candidate.adapter_id || '';
        var detail = [candidate.gender, candidate.age_group].filter(Boolean).join(' · ');
        var reason = candidate.reason || candidate.suggestion_reason || '';
        return '<div class="d-flex align-items-center gap-1 mt-1">'
            + '<span class="text-truncate" title="' + attr(reason) + '">'
            + escape(label) + (detail ? ' · ' + escape(detail) : '') + '</span>'
            + '<button class="btn btn-sm btn-outline-success py-0" type="button"'
            + ' data-voicesv3-action="suggestion-apply" data-voicesv3-name="' + attr(name) + '"'
            + ' data-voicesv3-id="' + attr(candidate.adapter_id || candidate.id || '') + '"'
            + ' aria-label="Use suggested voice ' + attr(label) + ' for ' + attr(name) + '">Use</button>'
            + '</div>';
    }

    function renderFor(state, name) {
        var target = container(name);
        if (!target) { return; }
        var suggestions = selectors.selectSuggestionsFor(state, name);
        if (!suggestions.length) { target.innerHTML = ''; return; }
        target.innerHTML = '<div class="small mt-2"><strong>Suggested voices</strong>'
            + suggestions.map(function (candidate) { return candidateRow(name, candidate); }).join('')
            + '</div>';
    }

    function refreshAll(state) {
        selectors.selectRosterRows(state).forEach(function (row) {
            renderFor(state, row.name);
        });
    }

    function syncToolbar(state) {
        var total = selectors.selectSuggestionTotal(state);
        var applyAll = toolbarControl('suggest-apply-all');
        var dismiss = toolbarControl('suggest-dismiss');
        var status = toolbarControl('suggest-status');
        var catalog = toolbarControl('suggest-catalog-status');
        if (applyAll) { applyAll.style.display = total ? '' : 'none'; }
        if (dismiss) { dismiss.style.display = total ? '' : 'none'; }
        if (status) { status.textContent = state.suggestions.status || ''; }
        if (catalog) { catalog.textContent = state.suggestions.catalogStatus || ''; }
    }

    /* ---- actions ---- */

    async function suggest(state, names) {
        var scopeIsNew = selectors.selectScopeIsNew(state);
        /* Characters, not rows: taking every row name here sent the same character once
         * per settled state, and the request deduplicates by speaker anyway - so
         * a three-state character burned three suggestions to get one answer. */
        var characters = names && names.length
            ? names
            : (scopeIsNew
                ? selectors.selectScopeSummary(state).pending
                : selectors.selectCharacterNames(state));

        if (!characters.length) {
            core.notify('There are no characters to suggest voices for.', 'warning');
            return false;
        }

        namespace.state.dispatch({ type: 'suggestions/status', running: true, status: 'Asking the model to match voices…' });
        try {
            var result = await namespace.api.requestSuggestions({ characters: characters });
            var byName = {};
            var suggestions = selectors.arrayOf(result && result.suggestions);
            // The endpoint answers either as a per-character map or a flat list.
            suggestions.forEach(function (entry) {
                if (entry && typeof entry === 'object' && typeof entry.character === 'string') {
                    byName[entry.character] = selectors.arrayOf(entry.candidates || entry.suggestions);
                } else if (entry && typeof entry === 'object' && typeof entry.name === 'string') {
                    byName[entry.name] = selectors.arrayOf(entry.candidates || entry.suggestions);
                }
            });
            namespace.state.dispatch({
                type: 'suggestions/set',
                byName: byName
            });
            var matched = Object.keys(byName).filter(function (name) { return byName[name].length; }).length;
            namespace.state.dispatch({
                type: 'suggestions/status',
                running: false,
                status: 'Suggested voices for ' + matched + ' of ' + characters.length + ' characters.',
                catalogStatus: result && result.catalog_warning ? String(result.catalog_warning) : ''
            });
            refreshAll(namespace.state.getState());
            return true;
        } catch (error) {
            namespace.state.dispatch({
                type: 'suggestions/status',
                running: false,
                status: '',
                catalogStatus: namespace.api.messageOf(error, 'Voice suggestions could not be generated.')
            });
            core.notifyFailure('Voice suggestions failed', error,
                'Check the model connection and the LoRA catalogue, then try again.');
            return false;
        }
    }

    async function suggestMore(state, name) {
        return suggest(state, [name]);
    }

    async function applyOne(name, adapterId) {
        try {
            await namespace.api.applySuggestion({ character: name, adapter_id: adapterId });
            core.notify('Suggested voice applied to ' + name + '.', 'success');
            var byName = Object.assign({}, namespace.state.getState().suggestions.byName);
            delete byName[name];
            namespace.state.dispatch({ type: 'suggestions/set', byName: byName });
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not apply the suggested voice to ' + name, error,
                'Reload Voices and check whether the candidate was saved before trying again.');
            return false;
        }
    }

    async function applyAll(state) {
        var byName = state.suggestions.byName || {};
        var names = Object.keys(byName).filter(function (name) { return selectors.arrayOf(byName[name]).length; });
        if (!names.length) {
            core.notify('There are no pending suggestions to apply.', 'warning');
            return false;
        }
        namespace.state.dispatch({ type: 'suggestions/status', running: true, status: 'Applying suggestions…' });
        try {
            var result = await namespace.api.applySuggestionsBulk({ characters: names });
            namespace.state.dispatch({ type: 'suggestions/set', byName: {} });
            namespace.state.dispatch({
                type: 'suggestions/status',
                running: false,
                status: 'Applied suggestions for ' + ((result && result.applied) != null ? result.applied : names.length) + ' characters.'
            });
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            namespace.state.dispatch({
                type: 'suggestions/status',
                running: false,
                status: namespace.api.messageOf(error, 'Suggestions could not be applied.')
            });
            core.notifyFailure('Applying suggestions failed', error,
                'Reload Voices and check which candidates were saved before trying again.');
            return false;
        }
    }

    function dismiss() {
        namespace.state.dispatch({ type: 'suggestions/set', byName: {} });
        namespace.state.dispatch({ type: 'suggestions/status', status: '' });
        return true;
    }

    namespace.suggestionsPanel = {
        mount: function () {},
        unbind: function () {},
        renderFor: renderFor,
        refreshAll: refreshAll,
        syncToolbar: syncToolbar,
        toolbarControl: toolbarControl,
        suggest: suggest,
        suggestMore: suggestMore,
        applyOne: applyOne,
        applyAll: applyAll,
        dismiss: dismiss
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));