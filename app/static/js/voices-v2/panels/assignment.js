/* Voices V2 — the assignment editor: draft actions and the save.
 *
 * Split of responsibility, and why:
 *
 *   detail.js      renders the voice section, including a `voice-editor` region,
 *                  and dispatches actions on click and change. It holds no
 *                  persistence logic and no sequencing.
 *   assignment.js  owns what an action *means*: the draft transitions, and the
 *                  one async path a save takes.
 *
 * So the order of a save — command, then re-read, then mark saved, then forget
 * the draft — is written once, here, rather than being reassembled by whichever
 * panel happened to render the button.
 *
 * The save is deliberately explicit. Choosing a different voice writes nothing;
 * only pressing Save sends a request. That is what makes it possible to leave a
 * half-finished decision, and it is why a dirty draft is guarded against being
 * lost by navigation.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var selectors = namespace.selectors;
    var api = namespace.api;
    var labels = namespace.labels;

    var bound = false;
    var inFlight = null;

    function editorRegion() {
        return core.region('voice-editor');
    }

    /* ── Draft transitions ───────────────────────────────────────────────
     * Each of these is a single dispatch. They exist so that no panel has to
     * know which command name means "the user picked something else". */

    function chooseVoice(voiceId) {
        if (typeof voiceId !== 'string' || !voiceId) { return false; }
        state.dispatch({ type: 'draft/choose', voiceId: voiceId });
        return true;
    }

    /* Clear is an edit, not an action: it becomes a draft that says "no voice"
     * and still waits for Save. Anything else would let a stray click destroy a
     * configured voice with no undo. */
    function clearVoice() {
        state.dispatch({ type: 'draft/clearVoice' });
        return true;
    }

    function discardDraft() {
        state.dispatch({ type: 'draft/discard' });
        return true;
    }

    /* ── The save ─────────────────────────────────────────────────────── */

    function save() {
        if (inFlight) { return inFlight; }
        var current = state.getState();
        if (!selectors.selectCanSave(current)) { return Promise.resolve(false); }

        var draft = selectors.selectDraft(current);
        var command = selectors.selectPendingCommand(current);
        /* Both tokens come from the read the user is looking at. Sending anything
         * else would defeat the guard the save contract exists to provide. */
        var revision = current.meta.revision;
        var bookToken = current.meta.book.token;
        if (!revision || !bookToken) {
            state.dispatch({
                type: 'save/failed',
                code: api.CODES.INVALID_CONFIGURATION,
                message: 'Voices V2 has not loaded the save token for this book yet. '
                    + 'Reload the projection and try again.'
            });
            return Promise.resolve(false);
        }

        state.dispatch({ type: 'save/start' });
        var pending = api.sendCommand({
            command: command,
            character: draft.characterKey,
            voiceId: draft.voiceId,
            revision: revision,
            bookToken: bookToken
        }).then(function () {
            inFlight = null;
            /* Re-read before reporting success, so the list, the detail and the
             * revision all describe what is now on disk rather than what was
             * asked for. A failed re-read does not undo the write: the write
             * happened, and `ui.error` says the view is stale. */
            return namespace.lifecycle.refresh();
        }).then(function () {
            state.dispatch({ type: 'save/succeeded' });
            state.dispatch({ type: 'draft/reset' });
            /* A save may have been what the user was waiting on before a
             * blocked navigation, so let the pending switch through now. */
            if (state.select(function (current) { return current.selection.blocked; })) {
                state.dispatch({ type: 'selection/acceptPending' });
            }
            return true;
        }, function (error) {
            inFlight = null;
            var code = api.refusalCode(error);
            if (error && error.status === 409) {
                state.dispatch({
                    type: 'save/conflict',
                    code: code || api.CODES.STALE_SNAPSHOT,
                    message: api.refusalMessage(error,
                        'The voice configuration changed elsewhere. Nothing was overwritten.')
                });
                return false;
            }
            state.dispatch({
                type: 'save/failed',
                code: code,
                message: api.refusalMessage(error, 'The voice could not be saved.')
            });
            return false;
        });
        inFlight = pending;
        return pending;
    }

    /* ── Recovery ───────────────────────────────────────────────────────
     * A conflict is resolved by showing the user the latest state, never by
     * retrying a request built from a snapshot that is known to be stale. */

    function reloadAfterConflict() {
        state.dispatch({ type: 'save/reset' });
        return namespace.lifecycle.refresh();
    }

    /* ── Rendering ─────────────────────────────────────────────────────── */

    function optionMarkup(voices, selectedId) {
        if (!voices.length) {
            return '<option value="">No assignable voices found</option>';
        }
        return voices.map(function (voice) {
            var selected = voice.voiceId === selectedId ? ' selected' : '';
            var unavailable = voice.available ? '' : ' disabled';
            var reason = voice.available ? '' : ' \u2014 ' + voice.unavailableReason;
            return '<option value="' + core.escape(voice.voiceId) + '"'
                + selected + unavailable + '>' + core.escape(voice.name + reason) + '</option>';
        }).join('');
    }

    function groupLabel(kind) {
        return labels.voiceKindLabel(kind);
    }

    /* Grouped by family so a 79-row catalogue stays navigable, and unavailable
     * voices are still listed - a character may already point at one, and hiding
     * it would make the selector disagree with storage without saying why. */
    function selectMarkup(catalogue, draft, chosen) {
        var groups = {};
        var order = [];
        catalogue.voices.forEach(function (voice) {
            if (!groups[voice.kind]) { groups[voice.kind] = []; order.push(voice.kind); }
            groups[voice.kind].push(voice);
        });
        var selectedId = draft.cleared ? null : draft.voiceId;
        return order.map(function (kind) {
            return '<optgroup label="' + core.escape(groupLabel(kind)) + '">'
                + optionMarkup(groups[kind], selectedId) + '</optgroup>';
        }).join('');
    }

    function saveStateMarkup(nextState, draft, canSave) {
        var save = selectors.selectSaveState(nextState);
        if (save.state === 'saving') {
            return '<div class="alert alert-secondary mb-0 vv2-save-state" role="status">'
                + 'Saving the voice change\u2026 the button stays disabled until it finishes.'
                + '</div>';
        }
        if (save.state === 'saved') {
            return '<div class="alert alert-success mb-0 vv2-save-state" role="status">'
                + 'Voice saved. The projection has been re-read, so what you see now '
                + 'is what is stored.</div>';
        }
        if (save.state === 'conflict') {
            return '<div class="alert alert-warning mb-0 vv2-save-state" role="alert">'
                + '<strong>This change was not saved.</strong> ' + core.escape(save.message)
                + ' Your choice is still selected below.'
                + '<div class="vv2-save-actions mt-2">'
                + '<button type="button" class="btn btn-sm btn-outline-primary" '
                + 'data-voicesv2-action="reload-latest">Refresh latest data</button>'
                + '</div></div>';
        }
        if (save.state === 'error') {
            return '<div class="alert alert-danger mb-0 vv2-save-state" role="alert">'
                + '<strong>The voice could not be saved.</strong> ' + core.escape(save.message)
                + '</div>';
        }
        if (draft.dirty) {
            return '<div class="alert alert-info mb-0 vv2-save-state" role="status">'
                + 'Unsaved change. Nothing is written until you press Save.</div>';
        }
        if (canSave) { return ''; }
        return '<p class="small text-muted mb-0 vv2-save-state">'
            + 'Choose a different voice to enable Save.</p>';
    }

    function unavailableNotice(chosen, character) {
        if (!chosen) { return ''; }
        if (chosen.available) { return ''; }
        return '<p class="small vv2-save-state mb-0 mt-1">'
            + core.escape(chosen.name) + ' cannot be assigned: '
            + core.escape(chosen.unavailableReason) + '</p>';
    }

    function storedNotice(character, draft) {
        if (!character) { return ''; }
        if (!character.voice.catalogueVoiceId && character.voice.assigned) {
            return '<p class="small vv2-save-state mb-0 mt-1">'
                + 'The saved voice ("' + core.escape(character.voice.label) + '") is not in the '
                + 'Voices V2 catalogue, so it cannot be re-selected here. It is left exactly '
                + 'as stored until you choose something else.</p>';
        }
        if (draft.dirty && draft.voiceId === character.voice.catalogueVoiceId) {
            return '<p class="small vv2-save-state mb-0 mt-1">'
                + 'That is the voice already stored, so there is nothing to save.</p>';
        }
        return '';
    }

    function render(nextState) {
        /* The editor region is emitted by detail.js, so it does not exist until
         * a character is selected. Binding on every render is what makes that
         * safe: `bind` is idempotent, and a listener attached at mount time to a
         * region that was not there yet would silently never fire. */
        bind();
        var container = editorRegion();
        if (!container) { return false; }
        var character = selectors.selectSelected(nextState);
        if (!character) { container.innerHTML = ''; return true; }

        var catalogue = selectors.selectCatalogue(nextState);
        var draft = selectors.selectDraft(nextState);
        var canSave = selectors.selectCanSave(nextState);
        var chosen = selectors.selectChosenVoice(nextState);

        var controlId = 'voicesv2-voice-select';
        container.innerHTML = '<div class="vv2-editor">'
            + '<label class="form-label vv2-label" for="' + controlId + '">Assign a voice</label>'
            + (catalogue.error
                ? '<div class="alert alert-danger vv2-save-state" role="alert">'
                  + core.escape(catalogue.error) + '</div>'
                : '')
            + '<select class="form-select form-select-sm" id="' + controlId + '"'
            + ' data-voicesv2-editor="voice-select"'
            + (catalogue.voices.length ? '' : ' disabled')
            + ' aria-describedby="voicesv2-voice-saved">' + selectMarkup(catalogue, draft, chosen)
            + '</select>'
            + '<p class="small text-muted mb-0 mt-1" id="voicesv2-voice-saved">'
            + 'Saved now: ' + core.escape(savedVoiceSentence(character))
            + '</p>'
            + unavailableNotice(chosen, character)
            + storedNotice(character, draft)
            + '<div class="vv2-save-actions">'
            + '<button type="button" class="btn btn-sm btn-primary"'
            + ' data-voicesv2-action="save-voice"'
            + (canSave ? '' : ' disabled') + '>Save voice</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-voicesv2-action="clear-voice"'
            + (canSave || draft.cleared ? '' : ' disabled') + '>Clear voice</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-voicesv2-action="discard-draft"'
            + (draft.dirty ? '' : ' disabled') + '>Discard changes</button>'
            + '</div>'
            + saveStateMarkup(nextState, draft, canSave)
            + '</div>';
        return true;
    }

    function savedVoiceSentence(character) {
        if (!character.voice.assigned) { return 'no voice'; }
        return character.voice.label + ' (' + labels.voiceCategoryLabel(character.voice.category) + ')';
    }

    /* ── Events ──────────────────────────────────────────────────────────
     * One delegated listener per container, bound once. Re-binding on every
     * render is the bug that makes a browser unusable after a few minutes. */

    function onEditorChange(event) {
        var origin = event && event.target;
        if (!origin || origin.getAttribute('data-voicesv2-editor') !== 'voice-select') { return false; }
        chooseVoice(origin.value);
        return true;
    }

    function onEditorClick(event) {
        var origin = event && event.target;
        var action = origin && origin.closest ? origin.closest('[data-voicesv2-action]') : null;
        if (!action || !core.contains(action)) { return false; }
        var name = action.getAttribute('data-voicesv2-action');
        if (name === 'save-voice') { save(); return true; }
        if (name === 'clear-voice') { clearVoice(); return true; }
        if (name === 'discard-draft') { discardDraft(); return true; }
        if (name === 'reload-latest') { reloadAfterConflict(); return true; }
        return false;
    }

    function bind() {
        if (bound) { return false; }
        var container = editorRegion();
        if (!container) { return false; }
        container.addEventListener('change', onEditorChange);
        container.addEventListener('click', onEditorClick);
        bound = true;
        return true;
    }

    function unmount() {
        bound = false;
        inFlight = null;
    }

    function mount() {
        bind();
        /* Warm the container so the delegated listeners have something to sit on
         * even before a character is selected. */
        var region = editorRegion();
        if (region && !region.innerHTML) { region.innerHTML = ''; }
    }

    namespace.assignmentPanel = {
        mount: mount,
        render: render,
        unmount: unmount,
        save: save,
        chooseVoice: chooseVoice,
        clearVoice: clearVoice,
        discardDraft: discardDraft,
        reloadAfterConflict: reloadAfterConflict,
        isSaving: function () { return inFlight !== null; }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));