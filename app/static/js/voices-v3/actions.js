/* Voices V3 — per-character and global actions.
 *
 * Everything that changes state on the server, as opposed to the panels that
 * change it in the store. Each action is deliberately narrow: it calls one
 * endpoint, then re-reads so the view reflects what the server actually stored
 * rather than what the request claimed.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var selectors = namespace.selectors;
    var state = namespace.state;

    /* ------------------------------------------------------------------ */
    /* task claim guards                                                   */
    /* ------------------------------------------------------------------ */

    /* The persona generator owns a server-side task slot. These wrappers use the
     * application's own claim helpers so a Voices V3 click cannot start a second
     * run behind the first tab's back. */
    function claimPersona() {
        if (typeof window.claimTaskStart === 'function') { return window.claimTaskStart('persona'); }
        return true;
    }

    function releasePersona() {
        if (typeof window.releaseTaskStart === 'function') { window.releaseTaskStart('persona'); }
    }

    /* ------------------------------------------------------------------ */
    /* approvals, audit, versions                                          */
    /* ------------------------------------------------------------------ */

    async function setApproval(name, field, status) {
        try {
            await namespace.api.setApproval(name, field, status);
            core.notify('Set ' + field.replace('_', ' ') + ' to ' + status + ' for ' + name + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not set ' + field + ' for ' + name, error,
                'Reload Voices and check the review state before trying again.');
            return false;
        }
    }

    async function editPersonaVoiceAudit(name) {
        var current = namespace.selectors.storedConfig(state.getState(), name).persona_voice_audit || {};
        var next = window.prompt(
            'Persona-to-voice audit for ' + name + '.\nOne line per field: key = value',
            Object.keys(current).map(function (key) { return key + ' = ' + current[key]; }).join('\n'));
        if (next === null) { return false; }
        var payload = {};
        next.split('\n').forEach(function (line) {
            var separator = line.indexOf('=');
            if (separator > 0) {
                payload[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
            }
        });
        try {
            await namespace.api.setPersonaVoiceAudit(name, payload);
            core.notify('Persona-to-voice audit updated for ' + name + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not update the audit for ' + name, error,
                'Reload Voices and check the audit before trying again.');
            return false;
        }
    }

    async function selectVersion(name, versionId) {
        if (!versionId) { return false; }
        try {
            await namespace.api.selectVersion(name, versionId);
            core.notify('Selected version ' + versionId + ' for ' + name + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not select that version for ' + name, error,
                'Reload Voices and check the active version before trying again.');
            return false;
        }
    }

    async function addVersion(name, presetAge) {
        var current = selectors.workingOf(state.getState(), name);
        var age = presetAge || window.prompt('Age group for the new version (for example: young_adult):',
            current.age_group || '') || '';
        if (!age) { return false; }
        try {
            if (current.type === 'ensemble') {
                core.notify('An ensemble cannot be saved as a version.', 'warning');
                return false;
            }
            // A version is a whole configuration snapshot, so it is built from the
            // working entry the user is looking at rather than from the defaults.
            // The fields go inside `config`: `VoiceVersionRequest` only reads
            // `version_id`, `age_group` and `config`, so anything sent as a sibling
            // is discarded and the backend snapshots the character entry instead.
            // Bookkeeping keys are stripped for the same reason tts.get_version_fields
            // strips them when overlaying.
            var snapshot = Object.assign({}, current, { source: 'voices_v3' });
            delete snapshot.members;
            delete snapshot.ready;
            delete snapshot.alias_of;
            delete snapshot.persona_status;
            delete snapshot.voice_status;
            delete snapshot.persona;
            delete snapshot.active_version;
            delete snapshot.active_candidate;
            delete snapshot.versions;
            delete snapshot.version_timeline;
            delete snapshot.style_timeline;
            delete snapshot.candidates;
            delete snapshot.age_group;

            var versionId = (age + '-' + Date.now()).slice(0, 80);
            await namespace.api.addVersion(name, {
                version_id: versionId,
                age_group: age,
                config: snapshot
            });
            await namespace.api.selectVersion(name, versionId);
            core.notify('Saved version ' + versionId + ' for ' + name + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not save a version for ' + name, error,
                'Reload Voices and check the version list before trying again.');
            return false;
        }
    }

    async function generateAgeVersion(name, ageGroup) {
        var age = ageGroup || window.prompt('Age group to generate:', '') || '';
        if (!age) { return false; }
        return addVersion(name, age);
    }

    /* ------------------------------------------------------------------ */
    /* candidates                                                          */
    /* ------------------------------------------------------------------ */

    async function selectCandidate(name, candidateId) {
        if (!candidateId) { return false; }
        try {
            await namespace.api.selectCandidate(name, candidateId);
            core.notify('Applied candidate ' + candidateId + ' to ' + name + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not apply that candidate to ' + name, error,
                'Reload Voices and check the stored candidates before trying again.');
            return false;
        }
    }

    async function deleteCandidate(name, candidateId) {
        var confirmed = await core.confirm(
            'Delete candidate "' + candidateId + '" for ' + name + '?',
            { title: 'Delete voice candidate?', actionLabel: 'Delete', danger: true });
        if (!confirmed) { return false; }
        try {
            await namespace.api.deleteCandidate(name, candidateId);
            core.notify('Deleted candidate ' + candidateId + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not delete that candidate', error,
                'Reload Voices and check the stored candidates before trying again.');
            return false;
        }
    }

    async function favoriteCandidate(name, candidateId, favorite) {
        try {
            await namespace.api.favoriteCandidate(name, candidateId, favorite);
            await namespace.lifecycle.reloadCatalogues();
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not change the candidate favourite', error,
                'Reload Voices and check whether the favourite was saved.');
            return false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* style timeline                                                      */
    /* ------------------------------------------------------------------ */

    async function removeStylePoint(name, fromIndex) {
        if (fromIndex === null) { return false; }
        var confirmed = await core.confirm(
            'Remove the voice-style change for ' + name + ' from line ' + (fromIndex + 1)
            + '? Existing rendered audio is not changed.',
            { title: 'Remove voice-style change?', actionLabel: 'Remove', danger: false });
        if (!confirmed) { return false; }
        try {
            await namespace.api.removeStylePoint(name, fromIndex);
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not remove the change', error,
                'Reload Voices to check whether the voice-style change was removed before trying again.');
            return false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* clone references                                                    */
    /* ------------------------------------------------------------------ */

    /* `scoped` means the reference belongs to an open state draft rather than to
     * the character. The upload itself is the same either way; only the write
     * target differs, and a state draft is never autosaved. */
    async function uploadCloneVoice(name, file, scoped) {
        if (!file || !name) { return false; }
        try {
            var response = await namespace.api.uploadCloneVoice(file);
            await namespace.lifecycle.reloadCatalogues();
            var uploadedId = response && response.id;
            if (uploadedId) {
                var storeState = state.getState();
                var current = scoped
                    ? Object.assign({}, selectors.selectStateDraft(storeState, name).entry)
                    : Object.assign({}, selectors.workingOf(storeState, name));
                var row = selectors.selectCloneVoices(storeState).find(function (voice) { return voice.id === uploadedId; });
                if (row) {
                    current.type = 'clone';
                    current.ref_audio = 'clone_voices/' + row.filename;
                    current.ref_text = row.ref_text || current.ref_text || '';
                    if (scoped) {
                        var draft = selectors.selectStateDraft(storeState, name);
                        state.dispatch({ type: 'state-draft/set', name: name, index: draft.index, entry: current });
                    } else {
                        state.dispatch({ type: 'working/set', name: name, entry: current });
                        namespace.saveController.scheduleSave();
                    }
                }
            }
            core.notify('Reference audio uploaded.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not upload the reference audio', error,
                'Check the file is one clean 3–30 second sentence, then try again.');
            return false;
        }
    }

    async function playCloneVoice(name, scoped) {
        var storeState = state.getState();
        var draft = scoped ? selectors.selectStateDraft(storeState, name) : null;
        var current = draft ? (draft.entry || {}) : selectors.workingOf(storeState, name);
        var path = current.ref_audio || (scoped ? '' : selectors.storedConfig(storeState, name).ref_audio) || '';
        if (!path) {
            core.notify('There is no reference audio for '
                + (draft ? 'this state of ' : '') + name + '.', 'warning');
            return false;
        }
        var namespace_ = path.indexOf('clone_voices/') === 0 ? 'clone_voices'
            : path.indexOf('designed_voices/') === 0 ? 'designed_voices' : null;
        var url = namespace_ ? '/' + namespace_ + '/' + path.slice(namespace_.length + 1) : '/' + path;
        core.playClip(url);
        return true;
    }

    async function deleteCloneVoice(name) {
        var storeState = state.getState();
        var current = selectors.workingOf(storeState, name);
        var reference = selectors.selectLibraryReference(storeState, current.ref_audio || '');
        if (!reference || reference.type !== 'clone') {
            core.notify('Only an uploaded reference voice can be deleted here.', 'warning');
            return false;
        }
        var confirmed = await core.confirm(
            'Delete the uploaded reference voice "' + reference.name + '"? '
            + 'Characters using it will lose their reference.',
            { title: 'Delete uploaded reference voice?', actionLabel: 'Delete', danger: true });
        if (!confirmed) { return false; }
        try {
            await namespace.api.deleteCloneVoice(reference.id);
            core.notify('Reference voice deleted.', 'success');
            await namespace.lifecycle.reloadCatalogues();
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not delete the reference voice', error,
                'Reload Voices and check the reference before trying again.');
            return false;
        }
    }

    /* The Designer tab owns the workspace, and the only supported way in is the
     * original tab's `openVoiceDesignEditor(button)`: it reads the description,
     * reference transcript and alias straight off the card's own controls. So the
     * button node is passed, not the character name - which also means it picks up
     * the STATE draft's values when a state chip is open, because the card renders
     * the draft's fields in the same place. */
    function openVoiceDesigner(name, button) {
        if (typeof window.openVoiceDesignEditor === 'function' && button) {
            window.openVoiceDesignEditor(button);
            return true;
        }
        if (typeof window.activateTab === 'function') {
            window.activateTab('designer');
        }
        core.notify('Open the Voice Designer tab to redesign this voice.', 'info');
        return false;
    }

    /* ------------------------------------------------------------------ */
    /* narrator                                                            */
    /* ------------------------------------------------------------------ */

    async function saveNarratorStrategy(value) {
        try {
            await namespace.api.saveNarratorStrategy({ strategy: value });
            core.notify('Narrator selection saved.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Could not save the narrator selection', error,
                'Reload Voices and check the narrator selection before trying again.');
            return false;
        }
    }

    async function previewNarratorSelection() {
        var storeState = state.getState();
        state.dispatch({ type: 'narrator/patch', previewing: true, status: 'Checking the selection…' });
        try {
            var result = await namespace.api.previewNarrator({
                strategy: storeState.narrator.strategy || selectors.selectNarratorStrategy(storeState),
                focus: storeState.narrator.previewFocus || null,
                version: storeState.narrator.previewVersion || null
            });
            state.dispatch({
                type: 'narrator/patch',
                previewing: false,
                status: (result && result.message)
                    ? String(result.message)
                    : ('Narrator for this selection: ' + ((result && result.voice) || 'main narrator voice'))
            });
            return true;
        } catch (error) {
            state.dispatch({
                type: 'narrator/patch',
                previewing: false,
                status: 'Preview failed: ' + namespace.api.messageOf(error, '')
            });
            return false;
        }
    }

    /* ------------------------------------------------------------------ */
    /* seeds and drafts                                                    */
    /* ------------------------------------------------------------------ */

    async function applyStableVoiceSeeds() {
        var storeState = state.getState();
        if (storeState.seedRepair.pending) { return false; }
        var snapshot = namespace.saveController.getSnapshot();
        if (!snapshot) {
            core.notify('Wait for the voices to finish loading before applying seeds.', 'warning');
            return false;
        }
        state.dispatch({ type: 'seedRepair/set', pending: true, changes: storeState.seedRepair.changes });
        try {
            await namespace.saveController.flush();
            var result = await namespace.api.applySeedRepair({
                revision: snapshot.revision,
                book_token: snapshot.bookToken
            });
            core.notify('Applied ' + (result.changes || []).length + ' stable seeds.'
                + (result.backup ? ' Backup: ' + result.backup : '') + ' Existing audio was kept.', 'success', 8000);
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            core.notifyFailure('Stable seed repair failed', error,
                'Reload Voices and review the current seed suggestions before applying again.');
            return false;
        } finally {
            state.dispatch({ type: 'seedRepair/set', pending: false });
        }
    }

    async function recoverDraft(index) {
        var drafts = state.getState().save.recoveryDrafts;
        return namespace.saveController.recoverDraft(drafts[index]);
    }

    async function discardDraft(index) {
        var drafts = state.getState().save.recoveryDrafts;
        return namespace.saveController.discardStoredDraft(drafts[index]);
    }

    namespace.actions = {
        claimPersona: claimPersona,
        releasePersona: releasePersona,
        setApproval: setApproval,
        editPersonaVoiceAudit: editPersonaVoiceAudit,
        selectVersion: selectVersion,
        addVersion: addVersion,
        generateAgeVersion: generateAgeVersion,
        selectCandidate: selectCandidate,
        deleteCandidate: deleteCandidate,
        favoriteCandidate: favoriteCandidate,
        removeStylePoint: removeStylePoint,
        uploadCloneVoice: uploadCloneVoice,
        playCloneVoice: playCloneVoice,
        deleteCloneVoice: deleteCloneVoice,
        openVoiceDesigner: openVoiceDesigner,
        saveNarratorStrategy: saveNarratorStrategy,
        previewNarratorSelection: previewNarratorSelection,
        applyStableVoiceSeeds: applyStableVoiceSeeds,
        recoverDraft: recoverDraft,
        discardDraft: discardDraft
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));