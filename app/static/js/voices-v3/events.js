/* Voices V3 — delegated event handling.
 *
 * One listener per region, bound once. Because interactivity is expressed with
 * `data-voicesv3-action` and `data-voicesv3-field` attributes rather than inline
 * handlers, the whole roster can be re-rendered at any time without re-binding
 * anything.
 *
 * Every field edit writes to the store and then schedules a save. The save is
 * debounced upstream, so a burst of keystrokes produces one write.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var selectors = namespace.selectors;
    var state = namespace.state;

    function fieldOf(node) {
        return node ? node.getAttribute('data-voicesv3-field') : null;
    }

    function nameOf(node) {
        return node ? (node.getAttribute('data-voicesv3-name') || node.closest('[data-voice]')?.getAttribute('data-voice')) : null;
    }

    function actionOf(node) {
        return node ? node.getAttribute('data-voicesv3-action') : null;
    }

    function valueOf(node) {
        return node.getAttribute('data-voicesv3-value');
    }

    function indexOf(node) {
        var raw = node.getAttribute('data-voicesv3-index');
        var parsed = parseInt(raw, 10);
        return Number.isFinite(parsed) ? parsed : null;
    }


    /* ------------------------------------------------------------------ */
    /* working-configuration edits                                         */
    /* ------------------------------------------------------------------ */

    function applyFieldEdit(storeState, name, field, value) {
        if (!name || !field) { return; }
        var current = Object.assign({}, selectors.workingOf(storeState, name));
        if (field === 'members') {
            // Members are a set, so the toggle is computed from the control rather
            // than written as a value.
            current.members = value;
        } else {
            current[field] = value;
        }
        state.dispatch({ type: 'working/set', name: name, entry: current });
        namespace.saveController.scheduleSave();
    }


    /* Switching voice type keeps the values already entered for the other
     * families, exactly as the original tab does: only the visible block
     * changes, the stored working entry keeps every field. */
    function applyTypeChange(storeState, name, type) {
        var current = Object.assign({}, selectors.workingOf(storeState, name));
        current.type = type;
        if (type === 'builtin_lora' || type === 'lora') {
            // The adapter selects for the two LoRA families share one working slot
            // in the original form; keep them independent here so switching back
            // and forth does not overwrite the other family's adapter.
            current.adapter_id = current.adapter_id || '';
        }
        state.dispatch({ type: 'working/set', name: name, entry: current });
        namespace.saveController.scheduleSave();
    }

    function collectEnsembleMembers(card, name) {
        var selected = [];
        Array.prototype.slice.call(card.querySelectorAll('.ensemble-member')).forEach(function (box) {
            if (box.checked) { selected.push(box.value); }
        });
        return selected;
    }

    /* ------------------------------------------------------------------ */
    /* roster                                                              */
    /* ------------------------------------------------------------------ */

    function onRosterChange(event) {
        var node = event.target;
        var storeState = state.getState();
        var name = nameOf(node);

        // The clone upload control is a file input, so it arrives here rather than
        // through the action table.
        if (node.classList && node.classList.contains('clone-voice-file-input')) {
            var file = node.files && node.files[0];
            /* `name`, not `speakerOf(...)`: the upload is a ROW-LOCAL write, and
             * uploadCloneVoice persists under versions[age_group] for a state row.
             * Collapsing to the character put the file on the base entry instead.
             * This also read `storeState` before it was assigned - the var was
             * hoisted, so it was undefined here and speakerOf got no roster. */
            if (file) { namespace.actions.uploadCloneVoice(name, file); }
            // Reset so re-picking the same file fires another change event.
            node.value = '';
            return;
        }

        if (node.classList && node.classList.contains('ensemble-member')) {
            applyFieldEdit(storeState, name, 'members',
                collectEnsembleMembers(node.closest('.voice-card'), name));
            return;
        }

        var action = actionOf(node);

        if (action === 'type-set') {
            applyTypeChange(storeState, name, node.value);
            return;
        }
        if (action === 'ready-toggle') {
            applyFieldEdit(storeState, name, 'ready', !!node.checked);
            return;
        }
        if (action === 'reference-select') {
            applyReferenceSelection(storeState, name, node.value);
            return;
        }

        var field = fieldOf(node);
        if (field) {
            var value = node.value;
            if (node.type === 'checkbox') { value = !!node.checked; }
            applyFieldEdit(storeState, name, field, value);
            return;
        }

        if (action === 'state-source') {
            // A state choice is applied deliberately, never auto-saved.
            return;
        }
    }

    function onRosterInput(event) {
        var node = event.target;
        var field = fieldOf(node);
        if (!field) { return; }
        applyFieldEdit(state.getState(), nameOf(node), field, node.value);
    }

    /* The script-entry range a state row covers, read off the button.
 * `end` is exclusive and absent for the last state, which runs to the end of
 * the book - so the backend is given only `start` and it defaults `end` there. */
function entryRangeOf(node) {
    var start = node.getAttribute('data-voicesv3-from-entry');
    if (start === null || start === '') { return null; }
    var parsed = parseInt(start, 10);
    if (!Number.isFinite(parsed) || parsed < 0) { return null; }
    var end = node.getAttribute('data-voicesv3-to-entry');
    if (end === null || end === '') { return { start: parsed }; }
    var parsedEnd = parseInt(end, 10);
    if (!Number.isFinite(parsedEnd)) { return { start: parsed }; }
    return { start: parsed, end: parsedEnd };
}

function onRosterClick(event) {
        var node = event.target;
        var actionNode = node.closest('[data-voicesv3-action]');
        if (!actionNode) { return; }
        var action = actionOf(actionNode);
        var storeState = state.getState();
        var name = actionNode.getAttribute('data-voicesv3-name');

        /* `name` here is the row key: "MARO" for a plain row, "MARO#adult" for one
         * settled state. Store writes use the key; every speaker-scoped API call
         * must use the CHARACTER, or it addresses a speaker that does not exist.
         * Resolving it once here keeps the nine call sites below from each having
         * to remember. */
        var speaker = selectors.speakerOf(storeState, name);

        switch (action) {
            case 'style-point-remove':
                event.preventDefault();
                namespace.actions.removeStylePoint(speaker, indexOf(actionNode));
                break;
            case 'persona-regenerate':
                /* `speaker`, not `name`: the request filter is the CHARACTER, and
                 * _require_script_speaker rejects anything not in the script - so a
                 * row key here 404s with "Speaker is not present in the active
                 * script". A state row additionally carries the age band and the
                 * script-entry range it covers; a plain row carries neither. */
                namespace.personasPanel.regenerateOne(speaker, {
                    ageGroup: actionNode.getAttribute('data-voicesv3-age'),
                    entryRange: entryRangeOf(actionNode)
                });
                break;
            case 'persona-audit-edit':
                namespace.actions.editPersonaVoiceAudit(speaker);
                break;
            case 'approval':
                namespace.actions.setApproval(speaker, actionNode.getAttribute('data-voicesv3-field'), valueOf(actionNode));
                break;
            case 'version-select':
                namespace.actions.selectVersion(speaker, actionNode.value);
                break;
            case 'version-add':
                namespace.actions.addVersion(speaker);
                break;
            case 'version-generate-age':
                namespace.actions.generateAgeVersion(speaker, actionNode.getAttribute('data-voicesv3-age'));
                break;
            case 'states-open':
                namespace.statesPanel.open(storeState, name);
                break;
            case 'states-apply':
                namespace.statesPanel.apply(storeState, name);
                break;

            case 'states-clear':
                namespace.statesPanel.clear(storeState, name);
                break;
            case 'suggest-more':
                namespace.suggestionsPanel.suggestMore(storeState, name);
                break;
            case 'suggestion-apply':
                namespace.suggestionsPanel.applyOne(speaker, actionNode.getAttribute('data-voicesv3-id'));
                break;
            case 'candidate-select':
                namespace.actions.selectCandidate(speaker, actionNode.getAttribute('data-voicesv3-id'));
                break;
            case 'candidate-delete':
                namespace.actions.deleteCandidate(speaker, actionNode.getAttribute('data-voicesv3-id'));
                break;
            case 'candidate-favorite':
                namespace.actions.favoriteCandidate(speaker, actionNode.getAttribute('data-voicesv3-id'), valueOf(actionNode) === 'true');
                break;
            case 'clone-upload':
                triggerCloneFilePicker(name);
                break;
            /* `name`, not `speaker`: these read and write ROW-LOCAL state via
             * selectors.workingOf/storedConfig, which are keyed by the roster row.
             * Handing them the character collapsed "MARO#adult" to "MARO", so a
             * state row's own reference audio was invisible to its play button -
             * it reported "no reference audio for MARO" while the row's field was
             * visibly full. Same latent bug would have let one state row's delete
             * target another row's reference. */
            case 'clone-play':
                namespace.actions.playCloneVoice(name);
                break;
            case 'clone-delete':
                namespace.actions.deleteCloneVoice(name);
                break;
            case 'design-open':
                namespace.actions.openVoiceDesigner(name, actionNode);
                break;
            case 'seed-repair':
                namespace.actions.applyStableVoiceSeeds();
                break;
            case 'draft-recover':
                namespace.actions.recoverDraft(indexOf(actionNode));
                break;
            case 'draft-discard':
                namespace.actions.discardDraft(indexOf(actionNode));
                break;
            case 'save-discard':
                namespace.saveController.discardAndReload();
                break;
            default:
                break;
        }
    }

    function triggerCloneFilePicker(name) {
        var host = core.region('roster');
        if (!host) { return; }
        var input = host.querySelector('.clone-voice-file-input[data-voicesv3-name="'
            + String(name).replace(/"/g, '\\"') + '"]');
        if (input) { input.click(); }
    }

    /* A reference selection writes both the catalogue row's identity and, for a
     * clone, the transcript the engine needs. */
    function applyReferenceSelection(storeState, name, value) {
        var current = Object.assign({}, selectors.workingOf(storeState, name));
        if (!value) { return; }
        if (value === '__manual__') {
            // Manual path: the existing ref_audio stays as typed.
            return;
        }
        var separator = value.indexOf(':');
        var kind = value.slice(0, separator);
        var id = value.slice(separator + 1);
        var pool = kind === 'clone' ? selectors.selectCloneVoices(storeState) : selectors.selectDesignedVoices(storeState);
        var row = pool.find(function (candidate) { return candidate.id === id; });
        if (!row) { return; }
        current.type = 'clone';
        current.ref_audio = (kind === 'clone' ? 'clone_voices/' : 'designed_voices/') + row.filename;
        current.ref_text = row.ref_text || current.ref_text || '';
        state.dispatch({ type: 'working/set', name: name, entry: current });
        namespace.saveController.scheduleSave();
    }


    /* ------------------------------------------------------------------ */
    /* toolbar                                                             */
    /* ------------------------------------------------------------------ */

    function toolbarControl(name) {
        return namespace.toolbarPanel.control(name);
    }

    function onToolbarChange(event) {
        var node = event.target;
        var controlName = node.getAttribute && node.getAttribute('data-voicesv3-control');
        if (!controlName) { return; }
        var storeState = state.getState();

        switch (controlName) {
            case 'narrator-strategy':
                state.dispatch({ type: 'narrator/patch', strategy: node.value });
                namespace.actions.saveNarratorStrategy(node.value);
                break;
            case 'narrator-focus':
                state.dispatch({ type: 'narrator/patch', previewFocus: node.value });
                break;
            case 'narrator-version':
                state.dispatch({ type: 'narrator/patch', previewVersion: node.value });
                break;
            case 'scope':
                state.dispatch({ type: 'view/patch', scope: node.value, scopeUserSet: true });
                break;
            case 'hide-ready':
                state.dispatch({ type: 'view/patch', hideReady: !!node.checked });
                namespace.lifecycle.render();
                break;
            case 'persona-advanced':
                state.dispatch({ type: 'persona/patch', advanced: !!node.checked });
                break;
            case 'persona-batch-size':
                state.dispatch({ type: 'persona/patch', batchSize: node.value });
                break;
            case 'persona-context':
                state.dispatch({ type: 'persona/patch', contextLines: node.value });
                break;
            case 'persona-context-custom-input':
                state.dispatch({ type: 'persona/patch', contextCustom: node.value });
                break;
            case 'keep-in-library':
                state.dispatch({ type: 'persona/patch', keepInLibrary: !!node.checked });
                break;
            default:
                break;
        }
    }

    function onToolbarInput(event) {
        var controlName = event.target.getAttribute && event.target.getAttribute('data-voicesv3-control');
        if (controlName === 'persona-batch-size' || controlName === 'persona-context-custom-input') {
            onToolbarChange(event);
        }
    }

    function onToolbarClick(event) {
        var node = event.target;
        var actionNode = node.closest('[data-voicesv3-action]');
        var storeState = state.getState();

        if (actionNode) {
            switch (actionNode.getAttribute('data-voicesv3-action')) {
                case 'narrator-preview':
                    namespace.actions.previewNarratorSelection();
                    break;
                case 'persona-generate':
                    namespace.personasPanel.generate(storeState);
                    break;
                case 'persona-cancel':
                    namespace.personasPanel.cancel(storeState);
                    break;
                case 'persona-refresh-retry':
                    namespace.lifecycle.reloadCatalogues();
                    break;
                case 'suggest':
                    namespace.suggestionsPanel.suggest(storeState);
                    break;
                case 'suggest-apply-all':
                    namespace.suggestionsPanel.applyAll(storeState);
                    break;
                case 'suggest-dismiss':
                    namespace.suggestionsPanel.dismiss();
                    break;
                default:
                    break;
            }
            return;
        }

        var controlName = node.getAttribute && node.getAttribute('data-voicesv3-control');
        if (controlName === 'narrator-preview') {
            namespace.actions.previewNarratorSelection();
        }
    }

    /* ------------------------------------------------------------------ */
    /* persona recovery                                                    */
    /* ------------------------------------------------------------------ */

    function onPersonaInput(event) {
        var controlName = event.target.getAttribute && event.target.getAttribute('data-voicesv3-control');
        if (!controlName) { return; }
        var map = {
            'recovery-speaker': 'speaker',
            'recovery-json': 'json',
            'recovery-samples': 'samples',
            'recovery-narration': 'narration'
        };
        var field = map[controlName];
        if (!field) { return; }
        state.dispatch({ type: 'persona/recovery/patch', [field]: event.target.value });
    }

    function onPersonaClick(event) {
        var node = event.target.closest('[data-voicesv3-control]');
        if (!node) { return; }
        var storeState = state.getState();
        switch (node.getAttribute('data-voicesv3-control')) {
            case 'recovery-copy':
                namespace.personasPanel.copyPrompt(storeState);
                break;
            case 'recovery-save':
                namespace.personasPanel.recover(storeState, false);
                break;
            case 'recovery-resume':
                namespace.personasPanel.recover(storeState, true);
                break;
            default:
                break;
        }
    }

    /* ------------------------------------------------------------------ */
    /* cast                                                                */
    /* ------------------------------------------------------------------ */

    function onCastChange(event) {
        var node = event.target;
        var controlName = node.getAttribute && node.getAttribute('data-voicesv3-control');
        var action = actionOf(node);

        if (controlName === 'select') {
            state.dispatch({ type: 'cast/patch', selected: node.value, panel: null });
            state.dispatch({ type: 'cast/bulk/patch', open: false });
            return;
        }
        if (action === 'cast-bulk-select') {
            var selection = Object.assign({}, state.getState().cast.bulk.selection);
            selection[node.value] = !!node.checked;
            state.dispatch({ type: 'cast/bulk/patch', selection: selection });
        }
    }

    function onCastClick(event) {
        var node = event.target;
        var actionNode = node.closest('[data-voicesv3-action]');
        var storeState = state.getState();

        if (actionNode) {
            switch (actionNode.getAttribute('data-voicesv3-action')) {
                case 'cast-member-delete':
                    namespace.castPanel.removeMember(storeState,
                        actionNode.getAttribute('data-voicesv3-cast'),
                        actionNode.getAttribute('data-voicesv3-key'));
                    break;
                case 'cast-apply-confirm':
                    namespace.castPanel.apply(storeState);
                    break;
                case 'cast-apply-cancel':
                    namespace.castPanel.cancelApply();
                    break;
                case 'cast-bulk-apply':
                    namespace.castPanel.applyBulk(storeState);
                    break;
                default:
                    break;
            }
            return;
        }

        var controlName = node.getAttribute && node.getAttribute('data-voicesv3-control');
        if (!controlName) { return; }
        switch (controlName) {
            case 'create':
                namespace.castPanel.create(storeState);
                break;
            case 'delete':
                namespace.castPanel.remove(storeState);
                break;
            case 'save':
                namespace.castPanel.save(storeState);
                break;
            case 'apply':
                namespace.castPanel.openApply(storeState);
                break;
            case 'apply-bulk':
                namespace.castPanel.openBulk(storeState);
                break;
            default:
                break;
        }
    }

    /* ------------------------------------------------------------------ */
    /* clone file input                                                    */
    /* ------------------------------------------------------------------ */

    namespace.events = {
        onRosterChange: onRosterChange,
        onRosterInput: onRosterInput,
        onRosterClick: onRosterClick,
        onToolbarChange: onToolbarChange,
        onToolbarInput: onToolbarInput,
        onToolbarClick: onToolbarClick,
        onPersonaInput: onPersonaInput,
        onPersonaClick: onPersonaClick,
        onCastChange: onCastChange,
        onCastClick: onCastClick
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));