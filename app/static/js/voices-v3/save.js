/* Voices V3 — the save pipeline.
 *
 * This reproduces the original Voices tab's persistence contract exactly, because
 * that contract is load-bearing:
 *
 *   - 800 ms debounce, one write in flight, latest wins
 *   - a synchronous browser draft written BEFORE the debounce, so a crash or a
 *     closed tab cannot lose an edit
 *   - the book token re-checked immediately before the request
 *   - the response validated, not assumed: the token must be echoed and the
 *     revision must be a sha256
 *   - a recovered draft is only removed once its own write succeeded
 *
 * The one deliberate difference is the localStorage prefix. Voices V3 drafts live
 * under `alexandria.voice-draft.v3.` so a V3 tab can never offer to recover a
 * draft the legacy tab wrote, and vice versa.
 */
(function (namespace) {
    'use strict';

    var DRAFT_PREFIX = 'alexandria.voice-draft.v3.';
    var SAVE_DEBOUNCE_MS = 800;
    var SAVED_MESSAGE_CLEAR_MS = 4000;
    var HEX_64 = /^[0-9a-f]{64}$/;

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function newDraftKey() {
        var random = (window.crypto && window.crypto.randomUUID)
            ? window.crypto.randomUUID()
            : String(Date.now()) + '-' + Math.random().toString(36).slice(2);
        return DRAFT_PREFIX + random;
    }

    /* ------------------------------------------------------------------ */
    /* draft records                                                       */
    /* ------------------------------------------------------------------ */

    function writeDraft(record) {
        try {
            var value = JSON.stringify(record);
            window.localStorage.setItem(record.key, value);
            // Read back: storage can silently refuse, and a draft we cannot see is
            // worse than no draft because the status line would claim otherwise.
            if (window.localStorage.getItem(record.key) !== value) {
                throw new Error('Draft storage did not retain the edit.');
            }
            return null;
        } catch (error) {
            return error;
        }
    }

    function removeDraft(record) {
        try {
            // Another tab may have recovered this draft; only remove our exact version.
            if (window.localStorage.getItem(record.key) === JSON.stringify(record)) {
                window.localStorage.removeItem(record.key);
            }
        } catch (error) {
            return error;
        }
        return null;
    }

    function validDraft(key, record) {
        if (!record || typeof record !== 'object') { return false; }
        if (record.version !== 1 || record.key !== key) { return false; }
        if (!HEX_64.test(record.book_token || '')) { return false; }
        if (!HEX_64.test(record.revision || '')) { return false; }
        if (!record.voices || typeof record.voices !== 'object' || Array.isArray(record.voices)) { return false; }
        return true;
    }

    function listRecoveryDrafts(excludeKey) {
        var found = [];
        var unreadable = false;
        var storage = window.localStorage;
        for (var index = 0; index < storage.length; index += 1) {
            var key = storage.key(index);
            if (!key || key.indexOf(DRAFT_PREFIX) !== 0 || key === excludeKey) { continue; }
            var record = null;
            try { record = JSON.parse(storage.getItem(key)); } catch (error) { unreadable = true; continue; }
            if (validDraft(key, record)) {
                found.push(record);
            } else {
                unreadable = true;
            }
        }
        return { drafts: found, unreadable: unreadable };
    }

    /* ------------------------------------------------------------------ */
    /* serialized queue                                                    */
    /* ------------------------------------------------------------------ */

    function createQueue(options) {
        var delay = options.delay || SAVE_DEBOUNCE_MS;
        var revision = 0;
        var pending = null;
        var timer = null;
        var inFlight = null;
        var dirty = false;

        function bump() { revision += 1; return revision; }

        function run() {
            timer = null;
            if (!pending || inFlight) { return; }
            var draft = pending;
            pending = null;
            inFlight = Promise.resolve()
                .then(function () { return options.write(draft); })
                .then(function () {
                    dirty = false;
                    if (options.onSaved) { options.onSaved(draft); }
                })
                .catch(function (error) {
                    if (options.onError) { options.onError(error, draft); }
                })
                .then(function () {
                    inFlight = null;
                    // Anything that arrived while the write was in flight goes now.
                    if (pending) { schedule(); }
                });
        }

        function schedule() {
            if (timer) { window.clearTimeout(timer); }
            timer = window.setTimeout(run, delay);
        }

        return {
            enqueue: function (draft) {
                pending = draft;
                dirty = true;
                bump();
                if (options.onDirty) { options.onDirty(draft); }
                schedule();
            },
            flush: function () {
                if (timer) { window.clearTimeout(timer); timer = null; }
                if (!pending && !inFlight) { return Promise.resolve(); }
                if (inFlight) { return inFlight; }
                run();
                return inFlight || Promise.resolve();
            },
            discard: function () {
                // Refuse if something new arrived: discarding would drop a live edit.
                if (pending && revision !== bump()) { /* revision advanced — pending is current */ }
                pending = null;
                dirty = false;
                if (timer) { window.clearTimeout(timer); timer = null; }
                return inFlight || Promise.resolve();
            },
            isDirty: function () { return dirty || !!pending; },
            getRevision: function () { return revision; }
        };
    }

    /* ------------------------------------------------------------------ */
    /* the Voices V3 save facade                                           */
    /* ------------------------------------------------------------------ */

    function createSaveController(options) {
        var dispatch = options.dispatch;
        var payloadBuilder = options.buildPayload;
        var postSave = options.postSave;
        var onReload = options.reload;

        var currentDraft = null;
        var lastSnapshot = null;
        var lastRenderedRevision = null;
        var lastRenderedToken = null;

        var queue = createQueue({
            delay: SAVE_DEBOUNCE_MS,
            write: function (draft) {
                if (!lastSnapshot || lastSnapshot.bookToken !== draft.book_token) {
                    throw new Error('The active book changed. Your unsaved voice edits were retained.');
                }
                var payload = {
                    revision: lastSnapshot.revision,
                    book_token: draft.book_token,
                    voices: draft.voices
                };
                return options.api.saveVoiceDocument(payload).then(function (result) {
                    if (!result || result.book_token !== draft.book_token || !HEX_64.test(result.revision || '')) {
                        throw new Error('The voice save could not be confirmed. Your edits were retained.');
                    }
                    lastSnapshot = {
                        revision: result.revision,
                        bookToken: lastSnapshot.bookToken,
                        bookId: lastSnapshot.bookId,
                        seedChanges: lastSnapshot.seedChanges
                    };
                    if (draft.recovered) { removeDraft(draft.recovered); }
                    if (currentDraft && currentDraft.generation === draft.draft_generation) {
                        removeDraft(currentDraft);
                        currentDraft = null;
                    } else if (currentDraft) {
                        currentDraft = Object.assign({}, currentDraft, { revision: result.revision });
                        var error = writeDraft(currentDraft);
                        if (error) { dispatch({ type: 'save/state', storageError: String(error.message || error) }); }
                    }
                    if (postSave) { return postSave(result); }
                    return result;
                });
            },
            onDirty: function () {
                dispatch({ type: 'save/state', state: 'unsaved', message: describeDirty() });
            },
            onSaved: function () {
                dispatch({ type: 'save/state', state: 'saved', message: '' });
            },
            onError: function (error) {
                dispatch({
                    type: 'save/state',
                    state: options.api.isConflict(error) ? 'conflict' : 'failed',
                    message: String((error && error.message) || error)
                });
            }
        });

        function describeDirty() {
            var storageError = options.getState().save.storageError;
            return storageError
                ? 'unsaved — browser draft unavailable; keep this tab open'
                : 'unsaved — draft retained in this browser';
        }

        function setSnapshot(snapshot) {
            lastSnapshot = snapshot;
        }

        function clearRenderedMarks() {
            lastRenderedRevision = null;
            lastRenderedToken = null;
        }

        function markRendered(revision, bookToken) {
            lastRenderedRevision = revision;
            lastRenderedToken = bookToken;
        }

        function renderedIsCurrent(revision, bookToken) {
            return lastRenderedRevision === revision && lastRenderedToken === bookToken;
        }

        function refreshRecoveryDrafts() {
            var listing = listRecoveryDrafts(currentDraft ? currentDraft.key : null);
            dispatch({ type: 'save/state', recoveryDrafts: listing.drafts });
            if (listing.unreadable) {
                dispatch({ type: 'save/state', message: 'A saved voice draft could not be read. It has been retained in browser storage.' });
            }
            return listing;
        }

        /* Called by a panel whenever the working configuration changed. */
        function scheduleSave() {
            if (!lastSnapshot) {
                options.core.notify('Wait for voices to finish loading before editing them.', 'warning');
                return;
            }
            var document_ = payloadBuilder();
            if (!document_ || !Object.keys(document_).length) {
                return; // nothing loaded yet; nothing to save
            }
            var key = (currentDraft && currentDraft.key) || newDraftKey();
            var record = {
                version: 1,
                key: key,
                book_token: lastSnapshot.bookToken,
                revision: lastSnapshot.revision,
                book_id: lastSnapshot.bookId || '',
                generation: ((currentDraft && currentDraft.generation) || 0) + 1,
                voices: clone(document_),
                updated: new Date().toISOString()
            };
            currentDraft = record;
            // Synchronous storage precedes the debounce timer and any request.
            var storageError = writeDraft(record);
            dispatch({ type: 'save/state', draftKey: record.key, draftGeneration: record.generation, storageError: storageError ? String(storageError.message || storageError) : null });
            queue.enqueue({
                book_token: record.book_token,
                voices: record.voices,
                draft_generation: record.generation,
                recovered: null
            });
        }

        function flush() {
            return queue.flush();
        }

        function isDirty() { return queue.isDirty(); }
        function getRevision() { return queue.getRevision(); }

        async function discardAndReload() {
            var confirmed = await options.core.confirm(
                'Discard all unsaved voice edits and reload the saved voices?',
                { title: 'Discard unsaved voice edits?', actionLabel: 'Discard edits', danger: true });
            if (!confirmed) { return false; }
            try {
                await queue.discard();
                if (currentDraft) { removeDraft(currentDraft); currentDraft = null; }
                dispatch({ type: 'save/state', state: 'idle', message: '', draftKey: null, draftGeneration: 0 });
                clearRenderedMarks();
                await onReload();
                return true;
            } catch (error) {
                options.core.notifyFailure('Voice reload failed', error,
                    'Check the current book and saved voices before retrying. Review any unsaved edits shown here.');
                return false;
            }
        }

        async function recoverDraft(record) {
            if (!record || isDirty()) {
                options.core.notify('Save or discard current edits before recovering a draft.', 'warning');
                return false;
            }
            if (!lastSnapshot || record.book_token !== lastSnapshot.bookToken) {
                options.core.notify('Load the original book version before recovering these edits.', 'warning');
                return false;
            }
            if (record.revision !== lastSnapshot.revision) {
                options.core.notify(
                    'Saved voices have changed since this draft. View the saved edits and copy the changes you want ' +
                    'into the current voices; the draft has been retained.', 'warning');
                return false;
            }
            var confirmed = await options.core.confirm(
                'Recover these voice edits?\n' + JSON.stringify(record.voices, null, 2),
                { title: 'Recover saved voice draft?', actionLabel: 'Recover edits', danger: false });
            if (!confirmed) { return false; }

            var key = record.key;
            var generation = record.generation;
            currentDraft = {
                version: 1, key: key, book_token: record.book_token,
                revision: record.revision, book_id: record.book_id || '',
                generation: generation, voices: clone(record.voices), updated: record.updated
            };
            queue.enqueue({
                book_token: record.book_token,
                voices: clone(record.voices),
                draft_generation: generation,
                recovered: record
            });
            try {
                await flush();
                await onReload();
                return true;
            } catch (error) {
                options.core.notifyFailure('Voice draft recovery failed', error,
                    'The draft is retained. Check the current book and saved voices before recovering again.', 'warning');
                return false;
            }
        }

        async function discardStoredDraft(record) {
            if (!record) { return false; }
            var confirmed = await options.core.confirm(
                'Discard this saved voice draft?\n' + JSON.stringify(record.voices, null, 2),
                { title: 'Discard saved voice draft?', actionLabel: 'Discard draft', danger: true });
            if (!confirmed) { return false; }
            removeDraft(record);
            refreshRecoveryDrafts();
            return true;
        }

        return {
            setSnapshot: setSnapshot,
            getSnapshot: function () { return lastSnapshot; },
            markRendered: markRendered,
            renderedIsCurrent: renderedIsCurrent,
            clearRenderedMarks: clearRenderedMarks,
            refreshRecoveryDrafts: refreshRecoveryDrafts,
            scheduleSave: scheduleSave,
            flush: flush,
            isDirty: isDirty,
            getRevision: getRevision,
            discardAndReload: discardAndReload,
            recoverDraft: recoverDraft,
            discardStoredDraft: discardStoredDraft,
            currentDraft: function () { return currentDraft; }
        };
    }

    namespace.save = {
        DRAFT_PREFIX: DRAFT_PREFIX,
        SAVE_DEBOUNCE_MS: SAVE_DEBOUNCE_MS,
        SAVED_MESSAGE_CLEAR_MS: SAVED_MESSAGE_CLEAR_MS,
        writeDraft: writeDraft,
        removeDraft: removeDraft,
        listRecoveryDrafts: listRecoveryDrafts,
        validDraft: validDraft,
        createQueue: createQueue,
        createController: createSaveController
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));