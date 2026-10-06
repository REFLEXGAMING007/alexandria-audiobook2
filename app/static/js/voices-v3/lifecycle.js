/* Voices V3 — lifecycle.
 *
 * Owns mount, load, re-read, render, and teardown. Two rules shape it:
 *
 *  1. Mount is idempotent and cheap. Re-entering the tab joins an in-flight read
 *     rather than starting a second one, and three fast clicks produce one
 *     listener set and one read.
 *
 *  2. Every read flushes the save queue first. The roster is derived from the
 *     snapshot, so re-reading while a write is queued would repaint from a stale
 *     revision and appear to lose an edit that is actually in flight.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var selectors = namespace.selectors;
    var state = namespace.state;

    var PANELS = ['toolbarPanel', 'personasPanel', 'rosterPanel', 'suggestionsPanel', 'castPanel'];

    var listenersBound = false;
    var storeSubscription = null;
    var renderQueued = false;
    var inFlight = null;
    var catalogueInFlight = null;
    var personaPollTimer = null;
    var personaPollAttempts = 0;

    function isMounted() {
        return state.getState().ui.mounted;
    }

    /* ---- render ---- */

    function render() {
        if (!isMounted()) { return; }
        var storeState = state.getState();
        namespace.toolbarPanel.sync(storeState);
        namespace.rosterPanel.render(storeState);
        namespace.personasPanel.render(storeState);
        namespace.suggestionsPanel.syncToolbar(storeState);
        namespace.castPanel.sync(storeState);
    }

    /* One read dispatches several commands. Coalescing to a microtask means the
     * list is painted once per read instead of once per dispatch. */
    function scheduleRender() {
        if (renderQueued) { return; }
        renderQueued = true;
        Promise.resolve().then(function () {
            renderQueued = false;
            render();
        });
    }

    function bindStore() {
        if (storeSubscription) { return; }
        storeSubscription = state.subscribe('*', scheduleRender);
    }

    function unbindStore() {
        if (!storeSubscription) { return; }
        storeSubscription();
        storeSubscription = null;
    }

    function bindListeners() {
        if (listenersBound) { return; }
        listenersBound = true;
        window.addEventListener('pagehide', onPageHide);
        window.addEventListener('beforeunload', onBeforeUnload);
    }

    function detachListeners() {
        if (!listenersBound) { return; }
        listenersBound = false;
        window.removeEventListener('pagehide', onPageHide);
        window.removeEventListener('beforeunload', onBeforeUnload);
    }

    function onPageHide() {
        // Best effort. The synchronous browser draft is the real safety net.
        namespace.saveController.flush().catch(function () {});
    }

    function onBeforeUnload(event) {
        if (namespace.saveController.isDirty()) {
            event.preventDefault();
            event.returnValue = '';
        }
    }

    /* ---- reads ---- */

    function adoptSnapshot(storeState, snapshot) {
        state.dispatch({
            type: 'meta/set',
            revision: snapshot.revision,
            bookToken: snapshot.book_token,
            bookId: snapshot.book_id || '',
            seedChanges: selectors.arrayOf(snapshot.seed_changes),
            rosterCount: selectors.arrayOf(snapshot.voices).length
        });
        state.dispatch({ type: 'seedRepair/set', pending: false, changes: selectors.arrayOf(snapshot.seed_changes) });
        return snapshot;
    }

    /* Rebuild the working entries from the stored roster. Called after a save
     * lands or after a re-read, so the working state always reflects what the
     * server holds rather than what a previous render assumed. */
    function adoptRoster(roster) {
        var names = [];
        var byName = {};
        var rosterList = roster;
        if (rosterList && !Array.isArray(rosterList) && Array.isArray(rosterList.voices)) {
            rosterList = rosterList.voices;
        }
        if (Array.isArray(rosterList)) {
            rosterList.forEach(function (entry) {
                if (!entry || !entry.name) { return; }
                // Key by row_key, which is the character name for a plain row and
                // "NAME#age" for one settled state. `name` alone would collapse a
                // multi-state character onto one key, so its three cards would
                // share one working entry and one save slot.
                var key = entry.row_key || entry.name;
                if (byName[key]) { return; }
                names.push(key);
                byName[key] = entry;
            });
        }
        state.dispatch({ type: 'roster/set', roster: { names: names, byName: byName } });
        state.dispatch({ type: 'working/reset' });
        var storeState = state.getState();
        names.forEach(function (name) {
            var stored = (byName[name] && byName[name].config) || {};
            state.dispatch({ type: 'working/set', name: name, entry: state.workingEntryFrom(stored) });
        });
        // Drop a state panel whose character no longer exists.
        var live = {};
        names.forEach(function (name) { live[name] = true; });
        Object.keys(storeState.states).forEach(function (name) {
            if (!live[name]) { state.dispatch({ type: 'states/clear', name: name }); }
        });
        return names.length;
    }

    function validateSnapshot(snapshot) {
        if (!snapshot || !Array.isArray(snapshot.voices)
            || !/^[0-9a-f]{64}$/.test(snapshot.revision || '')
            || !/^[0-9a-f]{64}$/.test(snapshot.book_token || '')) {
            throw new Error('Invalid voice snapshot; your voice settings were not replaced.');
        }
        return snapshot;
    }

    async function loadAll() {
        if (inFlight) { return inFlight; }
        inFlight = (async function () {
            await namespace.saveController.flush();
            var localRevision = namespace.saveController.getRevision();
            var snapshot = validateSnapshot(await namespace.api.fetchSnapshot());
            if (namespace.saveController.isDirty()
                || localRevision !== namespace.saveController.getRevision()) {
                throw new Error('Voice edits changed while refreshing. Your edits are still pending; try again.');
            }
            namespace.saveController.setSnapshot({
                revision: snapshot.revision,
                bookToken: snapshot.book_token,
                bookId: snapshot.book_id || '',
                seedChanges: selectors.arrayOf(snapshot.seed_changes)
            });
            adoptSnapshot(state.getState(), snapshot);
            namespace.saveController.refreshRecoveryDrafts();

            var roster = await namespace.api.fetchRoster();
            var count = adoptRoster(roster);
            namespace.saveController.markRendered(snapshot.revision, snapshot.book_token);

            state.dispatch({ type: 'narrator/patch', strategy: selectors.selectNarratorStrategy(state.getState()) });
            state.dispatch({ type: 'ui/patch', error: null, loadedAt: null, liveText: liveText(count) });
            return count;
        })().then(function (count) {
            inFlight = null;
            return count;
        }, function (error) {
            inFlight = null;
            state.dispatch({ type: 'ui/patch', error: core.describeError(error), liveText: 'Voices unavailable' });
            throw error;
        });
        return inFlight;
    }

    function liveText(count) {
        if (!count) { return 'No characters found yet. Generate a script first.'; }
        var ready = selectors.selectReadySummary(state.getState());
        return count + ' characters · ' + ready.label;
    }

    /* Re-read the roster and the snapshot, discarding unsaved working state.
     * Every action that changes stored configuration ends here. */
    async function reloadVoices() {
        try {
            await loadAll();
            return true;
        } catch (error) {
            reportError(error);
            return false;
        }
    }

    function reportError(error) {
        core.notifyFailure('Voices could not be loaded', error,
            'The Voices tab and your saved voice settings were not replaced. Retry, or generate a script first.');
    }

    /* Dropdown sources. Each list is independent: a failure is reported in the
     * persona refresh region and the previous list is kept, because the roster is
     * still usable without a voice catalogue. */
    async function reloadCatalogues() {
        if (catalogueInFlight) { return catalogueInFlight; }
        catalogueInFlight = (async function () {
            var patch = {};
            var failures = [];
            var sources = [
                ['lora', namespace.api.fetchLoraModels, 'LoRA models'],
                ['clone', namespace.api.fetchCloneVoices, 'uploaded reference voices'],
                ['designed', namespace.api.fetchDesignedVoices, 'designed voices']
            ];
            for (var index = 0; index < sources.length; index += 1) {
                var key = sources[index][0];
                try {
                    var list = await sources[index][1]();
                    if (!Array.isArray(list)) { throw new Error('Voice resource list is malformed'); }
                    patch[key] = list;
                } catch (error) {
                    failures.push(sources[index][2]);
                }
            }
            if (Object.keys(patch).length) { state.dispatch(Object.assign({ type: 'catalogues/set' }, patch)); }
            state.dispatch({
                type: 'persona/patch',
                resourcesStatus: failures.length
                    ? 'Could not refresh: ' + failures.join(', ') + '.'
                    : '',
                status: failures.length
                    ? 'Some voice lists are stale. The characters are still editable.'
                    : ''
            });
            state.dispatch({ type: 'ui/patch', resourcesRefreshedAt: Date.now() });
            return failures.length === 0;
        })().then(function (ok) {
            catalogueInFlight = null;
            return ok;
        }, function () {
            catalogueInFlight = null;
            return false;
        });
        return catalogueInFlight;
    }

    async function loadCastLibrary() {
        try {
            await namespace.castPanel.loadLibrary(state.getState());
            return true;
        } catch (error) {
            state.dispatch({ type: 'cast/patch', status: 'The cast library could not be loaded.' });
            return false;
        }
    }

    /* ---- persona polling ---- */

    function stopPersonaPolling() {
        if (personaPollTimer) { window.clearInterval(personaPollTimer); personaPollTimer = null; }
        personaPollAttempts = 0;
    }

    function startPersonaPolling() {
        stopPersonaPolling();
        personaPollAttempts = 0;
        personaPollTimer = window.setInterval(pollPersonaOnce, 1200);
    }

    async function pollPersonaOnce() {
        if (!isMounted()) { stopPersonaPolling(); return; }
        personaPollAttempts += 1;
        if (personaPollAttempts > 1800) { stopPersonaPolling(); return; }
        try {
            var status = await namespace.api.fetchPersonaStatus();
            var running = !!(status && (status.running || status.process || status.status === 'running'));
            state.dispatch({
                type: 'persona/patch',
                running: running,
                status: (status && status.message) ? String(status.message)
                    : (running ? 'Persona generation running…' : 'Persona generation finished.')
            });
            if (!running) {
                stopPersonaPolling();
                await reloadVoices();
            }
        } catch (error) {
            // A failed status read is not a failed run, so stop polling rather
            // than retrying a request that will keep failing.
            stopPersonaPolling();
            state.dispatch({ type: 'persona/patch', running: false });
        }
    }

    /* ---- mount / unmount ---- */

    function mount() {
        if (isMounted()) { return reloadVoices(); }
        if (!core.getRoot()) { return Promise.resolve(false); }

        state.dispatch({ type: 'ui/patch', mounted: true, loading: true, error: null, liveText: 'Loading voices…' });
        bindListeners();
        bindStore();
        PANELS.forEach(function (name) {
            var panel = namespace[name];
            if (panel && typeof panel.mount === 'function') { panel.mount(); }
        });

        render();

        return (async function () {
            try {
                // Catalogues and the cast library are independent of the roster, so
                // they load together with it rather than gating the first paint.
                var results = await Promise.all([
                    loadAll(),
                    reloadCatalogues(),
                    loadCastLibrary()
                ]);
                state.dispatch({ type: 'ui/patch', loading: false });
                render();
                return results[0] !== null;
            } catch (error) {
                state.dispatch({ type: 'ui/patch', loading: false });
                reportError(error);
                render();
                return false;
            }
        })();
    }

    function unmount() {
        // Unsubscribe before the final dispatch so a torn-down tab cannot paint.
        unbindStore();
        stopPersonaPolling();
        core.stopClip();
        PANELS.forEach(function (name) {
            var panel = namespace[name];
            if (panel && typeof panel.unmount === 'function') { panel.unmount(); }
        });
        state.dispatch({ type: 'ui/patch', mounted: false });
        detachListeners();
        namespace.saveController.clearRenderedMarks();
        inFlight = null;
    }

    namespace.lifecycle = {
        mount: mount,
        unmount: unmount,
        render: render,
        scheduleRender: scheduleRender,
        loadAll: loadAll,
        reloadVoices: reloadVoices,
        reloadCatalogues: reloadCatalogues,
        loadCastLibrary: loadCastLibrary,
        adoptRoster: adoptRoster,
        validateSnapshot: validateSnapshot,
        startPersonaPolling: startPersonaPolling,
        stopPersonaPolling: stopPersonaPolling,
        isMounted: isMounted,
        PANELS: PANELS
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));