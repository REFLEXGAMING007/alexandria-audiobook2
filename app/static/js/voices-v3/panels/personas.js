/* Voices V3 — persona controls and the manual recovery panel.
 *
 * Two responsibilities the original tab keeps in one markup block:
 *
 *  1. Status of the persona run, and the manual recovery escape hatch for when
 *     the LLM run fails and a persona has to be finished by hand.
 *  2. The resource-refresh status line, which reports a failed voice-catalogue
 *     reload with a retry rather than losing the list.
 *
 * Recovery is deliberately a 4-step documented path rather than a single form:
 * copy the prompt out, paste the reply back, then validate. `resume` asks the
 * pipeline to continue the run instead of only storing the persona.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var escape = core.escape;

    var bound = false;

    function control(name) {
        var region = core.region('personas');
        return region ? region.querySelector('[data-voicesv3-control="' + name + '"]') : null;
    }

    function render(state) {
        var region = core.region('personas');
        if (!region) { return; }

        var recovery = state.persona.recovery;
        var statusNode = control('recovery-status');
        var contextNode = control('recovery-context');

        if (statusNode) {
            statusNode.textContent = recovery.status || '';
            statusNode.className = 'form-text' + (recovery.busy ? ' text-muted' : '');
        }
        if (contextNode) {
            if (recovery.context) {
                contextNode.textContent = recovery.context;
                contextNode.style.display = '';
            } else {
                contextNode.textContent = '';
                contextNode.style.display = 'none';
            }
        }

        var speaker = control('recovery-speaker');
        var json = control('recovery-json');
        var samples = control('recovery-samples');
        var narration = control('recovery-narration');
        var saveButton = control('recovery-save');
        var resumeButton = control('recovery-resume');
        var copyButton = control('recovery-copy');

        // Diff-writes, so an in-progress edit is never clobbered by a repaint.
        if (speaker && document.activeElement !== speaker) { speaker.value = recovery.speaker || ''; }
        if (json && document.activeElement !== json) { json.value = recovery.json || ''; }
        if (samples && document.activeElement !== samples) { samples.value = recovery.samples || ''; }
        if (narration && document.activeElement !== narration) { narration.value = recovery.narration || ''; }

        [saveButton, resumeButton, copyButton].forEach(function (button) {
            if (button) { button.disabled = !!recovery.busy; }
        });
    }

    function bind() {
        if (bound) { return; }
        var region = core.region('personas');
        if (!region) { return; }
        region.addEventListener('input', namespace.events.onPersonaInput);
        region.addEventListener('click', namespace.events.onPersonaClick);
        bound = true;
    }

    function unbind() {}

    function mount() { bind(); }

    /* ---- actions ---- */

    function contextLineCount(state) {
        if (state.persona.contextLines === 'custom') {
            var custom = parseInt(state.persona.contextCustom, 10);
            return Number.isFinite(custom) && custom > 0 ? custom : 10;
        }
        var parsed = parseInt(state.persona.contextLines, 10);
        return Number.isFinite(parsed) && parsed > 0 ? parsed : 10;
    }

    /* Before an "all characters" run the current voices are written to a cast, so
     * a regenerate cannot silently destroy them. Returns false when the save
     * failed, which must stop the run rather than continue unprotected. */
    async function keepCurrentVoicesIfAsked(state) {
        if (state.view.scope === 'new') { return true; }
        if (!state.persona.keepInLibrary) { return true; }
        var have = selectorsScopeHave(state);
        if (!have.length) { return true; }

        var castName = state.cast.selected || state.meta.bookId || 'current book';
        try {
            try {
                await namespace.api.createCast(castName);
            } catch (error) {
                // 409 means the cast already exists, which is the expected path.
                if (!namespace.api.isConflict(error)) { throw error; }
            }
            var result = await namespace.api.saveCast({ cast: castName, characters: have, cast_specific: [] });
            core.notify('Saved ' + have.length + ' current voices to the library as "' + castName + '".', 'success');
            try { await namespace.lifecycle.loadCastLibrary(); } catch (error) { /* display only */ }
            return !!result;
        } catch (error) {
            core.notifyFailure('Not started: saving current voices to the library failed', error,
                'Check the cast library for the saved voices before starting again. Keep the save-to-library ' +
                'option enabled to protect the current assignments.');
            return false;
        }
    }

    function selectorsScopeHave(state) {
        return namespace.selectors.selectScopeSummary(state).have;
    }

    async function generate(state) {
        if (!namespace.actions.claimPersona()) { return; }
        try {
            var scopeIsNew = namespace.selectors.selectScopeIsNew(state);
            if (!scopeIsNew) {
                var kept = await keepCurrentVoicesIfAsked(state);
                if (!kept) { return; }
            }
            // Field names must match GeneratePersonasRequest exactly. Pydantic
            // ignores unknown keys, so a wrong name is dropped silently rather
            // than rejected: `only_missing` here meant every persona was
            // re-rolled regardless of the scope filter.
            var response = await namespace.api.generatePersonas({
                new_only: scopeIsNew,
                batch_size: parseInt(state.persona.batchSize, 10) || 40,
                context_lines: contextLineCount(state)
            });
            namespace.state.dispatch({
                type: 'persona/patch',
                running: true,
                status: response && response.message ? String(response.message) : 'Persona generation started.'
            });
            namespace.lifecycle.startPersonaPolling();
        } catch (error) {
            core.notifyFailure('Persona generation did not start', error,
                'Reload Voices and check the persona status before starting again.');
        } finally {
            namespace.actions.releasePersona();
        }
    }

    async function cancel(state) {
        try {
            await namespace.api.cancelPersonas();
            namespace.state.dispatch({ type: 'persona/patch', running: false, status: 'Cancelling persona generation…' });
            namespace.lifecycle.stopPersonaPolling();
        } catch (error) {
            core.notifyFailure('Could not cancel persona generation', error,
                'Check the persona status; the run may already have finished.');
        }
    }

    /* `options.ageGroup` turns this into a PER-STATE persona.
     *
     * The backend supports it: generate_personas.py takes --age-group, tells the
     * LLM which age profile to write for, and stores the result as
     * versions[age_group] instead of overwriting the character's own entry. That
     * is the same key a state chip saves under, so a state persona pre-fills the
     * chip rather than colliding with it.
     *
     * The character filter is `speaker` (singular). Sending `characters` looked
     * plausible and was silently dropped by the request model, which made this
     * regenerate EVERY character in the book instead of the one clicked. */
    /* `speaker` is the CHARACTER name, never a roster row key. The request's
     * speaker field is validated against the script, so a row key ("MARO#adult")
     * is rejected with "Speaker is not present in the active script". */
    async function regenerateOne(speaker, options) {
        if (!namespace.actions.claimPersona()) { return false; }
        try {
            var state = namespace.state.getState();
            var ageGroup = options && options.ageGroup ? String(options.ageGroup) : '';
            var payload = {
                speaker: speaker,
                new_only: false,
                batch_size: 1,
                context_lines: contextLineCount(state)
            };
            if (ageGroup) { payload.age_group = ageGroup; }
            /* A state row also sends the SCRIPT-ENTRY range it covers, so the
             * persona is written from that state's lines and the narration around
             * them. Without it the prompt for a thirty-eight-year-old state was
             * assembled from the character's sixteen-year-old lines, and the age
             * instruction was the only thing asking the model to reconcile that. */
            var range = options && options.entryRange;
            if (range && typeof range.start === 'number' && typeof range.end === 'number'
                && range.end > range.start) {
                payload.entry_range = range.start + ':' + range.end;
            }

            var response = await namespace.api.generatePersonas(payload);
            namespace.state.dispatch({
                type: 'persona/patch',
                running: true,
                status: 'Regenerating the persona for ' + speaker
                    + (ageGroup ? ' (' + ageGroup.replace(/_/g, ' ') + ')' : '') + '…'
            });
            namespace.lifecycle.startPersonaPolling();
            if (response && response.message) {
                namespace.state.dispatch({ type: 'persona/patch', status: String(response.message) });
            }
            return true;
        } catch (error) {
            core.notifyFailure('Could not regenerate the persona for ' + speaker, error,
                'Reload Voices and check the persona status before trying again.');
            return false;
        } finally {
            namespace.actions.releasePersona();
        }
    }

    async function copyPrompt(state) {
        var recovery = state.persona.recovery;
        if (!recovery.speaker) {
            core.notify('Enter the speaker name before copying the prompt.', 'warning');
            return false;
        }
        try {
            var prompt = window.buildPersonaPrompt
                ? window.buildPersonaPrompt({
                    speaker: recovery.speaker,
                    samples: recovery.samples,
                    narration: recovery.narration
                })
                : null;
            if (!prompt) {
                // The prompt builder lives in the legacy tab. Without it, the copy
                // path cannot fabricate a prompt that would produce a different
                // persona, so it is refused rather than approximated.
                core.notify('The persona prompt builder is unavailable here. Use Generate Personas, ' +
                    'or paste a persona JSON directly.', 'warning');
                return false;
            }
            await navigator.clipboard.writeText(prompt);
            namespace.state.dispatch({ type: 'persona/recovery/patch', status: 'Prompt copied to the clipboard.' });
            return true;
        } catch (error) {
            core.notifyFailure('Could not copy the persona prompt', error,
                'Select and copy the prompt manually, then paste the reply into Persona JSON.');
            return false;
        }
    }

    async function recover(state, resume) {
        var recovery = state.persona.recovery;
        if (!recovery.speaker) {
            core.notify('Enter the speaker name before recovering a persona.', 'warning');
            return false;
        }
        if (!recovery.json) {
            core.notify('Paste the persona JSON reply before validating.', 'warning');
            return false;
        }
        namespace.state.dispatch({ type: 'persona/recovery/patch', busy: true, status: 'Validating the persona JSON…' });
        try {
            var response = await namespace.api.saveDesignedVoice({
                recover_persona: true,
                speaker: recovery.speaker,
                persona: recovery.json,
                resume: !!resume
            });
            namespace.state.dispatch({
                type: 'persona/recovery/patch',
                busy: false,
                status: response && response.message
                    ? String(response.message)
                    : 'Persona validated and saved.',
                context: '',
                json: ''
            });
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            namespace.state.dispatch({
                type: 'persona/recovery/patch',
                busy: false,
                status: namespace.api.messageOf(error, 'The persona JSON could not be validated.')
            });
            return false;
        }
    }

    namespace.personasPanel = {
        mount: mount,
        bind: bind,
        unbind: unbind,
        render: render,
        control: control,
        generate: generate,
        cancel: cancel,
        regenerateOne: regenerateOne,
        copyPrompt: copyPrompt,
        recover: recover,
        contextLineCount: contextLineCount,
        keepCurrentVoicesIfAsked: keepCurrentVoicesIfAsked
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));