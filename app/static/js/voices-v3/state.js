/* Voices V3 — the store.
 *
 * The whole point of this store is the single decision it makes differently from
 * the original Voices tab: the working voice configuration lives here, keyed by
 * character name, instead of living in the DOM markup that a save scrapes.
 *
 * Two invariants, both load-bearing:
 *
 *  1. The store holds data only. No DOM node ever enters it. A command carrying
 *     one is rejected rather than silently stored, because the save payload is
 *     computed from this state and a node in here would make it unreproducible.
 *
 *  2. `dispatch` is the only writer. Panels read through selectors and write
 *     through commands. That is what makes the payload builder a pure function
 *     and what lets a save be rebuilt from state after any number of renders.
 */
(function (namespace) {
    'use strict';

    var TYPES = Object.freeze(['custom', 'builtin_lora', 'clone', 'lora', 'design', 'ensemble']);
    var PERSONA_CONTEXT_OPTIONS = Object.freeze(['10', '25', '50', '100', 'custom']);
    var APPROVAL_STATUSES = Object.freeze(['unreviewed', 'generated', 'reviewed', 'approved', 'rejected']);

    /* Fields the per-character form owns. The save payload strips exactly these
     * from the stored server entry before merging the working values back in, so
     * every other server field — versions, timelines, candidates, statuses, the
     * persona audit, generated trait metadata — survives untouched.
     *
     * The original tab's strip list also removed `seed` and `default_style`. Both
     * are removed here too, with one deliberate difference:
     *
     *   - `seed` is server-owned either way. The form never exposes it, and the
     *     original preserved the stored value unconditionally.
     *   - `default_style` is PRESERVED here. The original dropped it, which
     *     silently killed the `character_style || default_style` fallback the
     *     card itself renders and that `tts.py` still reads. Preserving a field
     *     the UI displays is not a feature change; it removes a data-loss path.
     */
    var FORM_OWNED_KEYS = Object.freeze([
        'type', 'voice', 'character_style', 'ref_audio', 'ref_text',
        'adapter_id', 'adapter_path', 'description', 'members', 'alias_of', 'ready'
    ]);

    function text(value) {
        if (typeof value !== 'string') { return ''; }
        var trimmed = value.trim();
        return trimmed;
    }

    function createInitialState() {
        return {
            /* Server truth for the active book. */
            meta: {
                revision: null,
                bookToken: null,
                bookId: '',
                seedChanges: [],
                loadedAt: null,
                rosterCount: 0
            },

            /* Working edits, keyed by character name. Values are the form-owned
             * fields only; the stored entry stays in `roster.byName`. */
            working: {},

            /* Display and scope controls. */
            view: {
                hideReady: false,
                scope: 'new',
                scopeUserSet: false
            },

            /* Narrator strategy block. */
            narrator: {
                strategy: 'global',
                previewFocus: '',
                previewVersion: '',
                status: '',
                previewing: false
            },

            /* Persona generation block. */
            persona: {
                running: false,
                advanced: false,
                batchSize: '40',
                contextLines: '10',
                contextCustom: '10',
                status: '',
                resourcesStatus: '',
                keepInLibrary: true,
                castName: '',
                recovery: {
                    speaker: '', json: '', samples: '', narration: '',
                    status: '', context: '', busy: false
                }
            },

            /* Suggestion block: per character, the candidates the LLM proposed. */
            suggestions: {
                byName: {},
                running: false,
                status: '',
                catalogStatus: ''
            },

            /* Per-character state timeline panels. */
            states: {},


            /* Series Cast block. */
            cast: {
                library: { casts: [], shared: [], current_characters: [] },
                selected: '',
                status: '',
                panel: null,
                busy: false,
                bulk: { open: false, scripts: [], selection: {}, matches: null, status: '' }
            },

            /* Dropdown sources. Each may fail independently; a failed list is
             * reported rather than thrown, and the previous list is kept. */
            catalogues: {
                lora: [],
                designed: [],
                clone: [],
                aliases: {}
            },

            /* Save pipeline. The queue itself lives in save.js. */
            save: {
                state: 'idle',   // idle | unsaved | saving | saved | failed | conflict
                message: '',
                draftKey: null,
                draftGeneration: 0,
                recoveryDrafts: [],
                storageError: null
            },

            /* Stable-seed repair banner. */
            seedRepair: { pending: false, changes: [] },

            /* Transient UI state. */
            ui: {
                mounted: false,
                loading: false,
                error: null,
                resourcesRefreshedAt: -Infinity,
                liveText: '',
                castExpanded: false
            }
        };
    }

    var state = createInitialState();
    var subscribers = [];
    var pathDepth = 0;

    function resolve(path) {
        var parts = String(path).split('.');
        var cursor = state;
        for (var index = 0; index < parts.length; index += 1) {
            if (cursor === null || typeof cursor !== 'object') { return undefined; }
            cursor = cursor[parts[index]];
        }
        return cursor;
    }

    function matches(subscription, path) {
        if (subscription === '*') { return true; }
        return subscription === path || path.indexOf(subscription + '.') === 0;
    }

    function notify(path) {
        for (var index = 0; index < subscribers.length; index += 1) {
            if (matches(subscribers[index].path, path)) {
                try { subscribers[index].listener(state, path); } catch (error) {
                    // A panel that throws while rendering must not stop the others.
                    if (window.console) { window.console.error('VoicesV3 subscriber failed', error); }
                }
            }
        }
    }

    function subscribe(path, listener) {
        var entry = { path: path, listener: listener };
        subscribers.push(entry);
        return function unsubscribe() {
            var position = subscribers.indexOf(entry);
            if (position >= 0) { subscribers.splice(position, 1); }
        };
    }

    function rejectNode(value, label) {
        if (value && typeof value === 'object' && typeof value.nodeType === 'number') {
            throw new Error('VoicesV3 store commands cannot carry a DOM node (' + label + ').');
        }
        return value;
    }

    function workingEntryFrom(config) {
        var entry = {};
        if (!config || typeof config !== 'object') { return entry; }
        for (var index = 0; index < FORM_OWNED_KEYS.length; index += 1) {
            var key = FORM_OWNED_KEYS[index];
            if (Object.prototype.hasOwnProperty.call(config, key)) {
                entry[key] = Array.isArray(config[key]) ? config[key].slice() : config[key];
            }
        }
        return entry;
    }

    function reduce(command) {
        if (!command || typeof command.type !== 'string') {
            throw new Error('VoicesV3 commands require a type.');
        }
        if (command.value && command.value.nodeType) {
            throw new Error('VoicesV3 commands cannot carry a DOM node.');
        }

        switch (command.type) {

            case 'meta/set': {
                state.meta.revision = command.revision;
                state.meta.bookToken = command.bookToken;
                state.meta.bookId = command.bookId || '';
                state.meta.seedChanges = Array.isArray(command.seedChanges) ? command.seedChanges : [];
                state.meta.rosterCount = typeof command.rosterCount === 'number' ? command.rosterCount : 0;
                state.meta.loadedAt = new Date().toISOString();
                return 'meta';
            }

            case 'roster/set': {
                state.roster = rejectNode(command.roster, 'roster');
                return 'roster';
            }

            case 'working/set': {
                rejectNode(command.name, 'name');
                if (!command.name) { throw new Error('A working entry requires a character name.'); }
                state.working[command.name] = command.entry || {};
                return 'working';
            }

            case 'working/reset': {
                if (command.name) {
                    delete state.working[command.name];
                } else {
                    state.working = {};
                }
                return 'working';
            }

            case 'view/patch': {
                var viewKeys = ['hideReady', 'scope', 'scopeUserSet'];
                for (var v = 0; v < viewKeys.length; v += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, viewKeys[v])) {
                        state.view[viewKeys[v]] = command[viewKeys[v]];
                    }
                }
                return 'view';
            }

            case 'narrator/patch': {
                var narratorKeys = ['strategy', 'previewFocus', 'previewVersion', 'status', 'previewing'];
                for (var n = 0; n < narratorKeys.length; n += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, narratorKeys[n])) {
                        state.narrator[narratorKeys[n]] = command[narratorKeys[n]];
                    }
                }
                return 'narrator';
            }

            case 'persona/patch': {
                var personaKeys = ['running', 'advanced', 'batchSize', 'contextLines',
                    'contextCustom', 'status', 'resourcesStatus', 'keepInLibrary', 'castName'];
                for (var p = 0; p < personaKeys.length; p += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, personaKeys[p])) {
                        state.persona[personaKeys[p]] = command[personaKeys[p]];
                    }
                }
                return 'persona';
            }

            case 'persona/recovery/patch': {
                var recoveryKeys = ['speaker', 'json', 'samples', 'narration', 'status', 'context', 'busy'];
                for (var r = 0; r < recoveryKeys.length; r += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, recoveryKeys[r])) {
                        state.persona.recovery[recoveryKeys[r]] = command[recoveryKeys[r]];
                    }
                }
                return 'persona.recovery';
            }

            case 'suggestions/set': {
                state.suggestions.byName = command.byName || {};
                return 'suggestions.byName';
            }

            case 'suggestions/status': {
                state.suggestions.running = !!command.running;
                state.suggestions.status = text(command.status);
                state.suggestions.catalogStatus = text(command.catalogStatus);
                return 'suggestions';
            }

            case 'states/set': {
                var name = text(command.name);
                if (!name) { throw new Error('A state panel requires a character name.'); }
                var existing = state.states[name] || {};
                state.states[name] = {
                    loading: !!command.loading,
                    loaded: command.loaded !== undefined ? !!command.loaded : existing.loaded,
                    rows: command.rows !== undefined ? command.rows : (existing.rows || []),
                    applied: command.applied !== undefined ? command.applied : (existing.applied || []),
                    offerGenerate: command.offerGenerate !== undefined
                        ? !!command.offerGenerate : existing.offerGenerate,
                    saving: !!command.saving,
                    error: command.error !== undefined ? text(command.error) : (existing.error || ''),
                    notice: command.notice !== undefined ? text(command.notice) : (existing.notice || '')
                };
                return 'states';
            }

            case 'states/clear': {
                if (command.name) {
                    delete state.states[command.name];
                } else {
                    state.states = {};
                }
                return 'states';
            }

            case 'cast/patch': {
                var castKeys = ['selected', 'status', 'panel', 'busy', 'library'];
                for (var c = 0; c < castKeys.length; c += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, castKeys[c])) {
                        state.cast[castKeys[c]] = rejectNode(command[castKeys[c]], castKeys[c]);
                    }
                }
                return 'cast';
            }

            case 'cast/bulk/patch': {
                var bulkKeys = ['open', 'scripts', 'selection', 'matches', 'status'];
                for (var b = 0; b < bulkKeys.length; b += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, bulkKeys[b])) {
                        state.cast.bulk[bulkKeys[b]] = rejectNode(command[bulkKeys[b]], bulkKeys[b]);
                    }
                }
                return 'cast.bulk';
            }

            case 'catalogues/set': {
                var catalogueKeys = ['lora', 'designed', 'clone', 'aliases'];
                for (var k = 0; k < catalogueKeys.length; k += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, catalogueKeys[k])) {
                        state.catalogues[catalogueKeys[k]] = rejectNode(command[catalogueKeys[k]], catalogueKeys[k]);
                    }
                }
                return 'catalogues';
            }

            case 'save/state': {
                var saveKeys = ['state', 'message', 'draftKey', 'draftGeneration', 'recoveryDrafts', 'storageError'];
                for (var s = 0; s < saveKeys.length; s += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, saveKeys[s])) {
                        state.save[saveKeys[s]] = rejectNode(command[saveKeys[s]], saveKeys[s]);
                    }
                }
                return 'save';
            }

            case 'seedRepair/set': {
                state.seedRepair.pending = !!command.pending;
                state.seedRepair.changes = Array.isArray(command.changes) ? command.changes : [];
                return 'seedRepair';
            }

            case 'ui/patch': {
                var uiKeys = ['mounted', 'loading', 'error', 'liveText', 'resourcesRefreshedAt', 'castExpanded'];
                for (var u = 0; u < uiKeys.length; u += 1) {
                    if (Object.prototype.hasOwnProperty.call(command, uiKeys[u])) {
                        state.ui[uiKeys[u]] = rejectNode(command[uiKeys[u]], uiKeys[u]);
                    }
                }
                return 'ui';
            }

            default:
                throw new Error('Unknown VoicesV3 command: ' + command.type);
        }
    }

    function dispatch(command) {
        if (pathDepth > 32) { throw new Error('VoicesV3 dispatch recursion limit reached.'); }
        pathDepth += 1;
        try {
            var changed = reduce(command);
            if (changed) { notify(changed); }
            return changed;
        } finally {
            pathDepth -= 1;
        }
    }

    function select(reader) {
        return reader(state);
    }

    function getState() {
        return state;
    }

    function reset() {
        var mounted = state.ui.mounted;
        var refreshedAt = state.ui.resourcesRefreshedAt;
        state = createInitialState();
        // A reset must never orphan a mounted tab.
        state.ui.mounted = mounted;
        state.ui.resourcesRefreshedAt = refreshedAt;
        notify('*');
    }

    namespace.state = {
        TYPES: TYPES,
        PERSONA_CONTEXT_OPTIONS: PERSONA_CONTEXT_OPTIONS,
        APPROVAL_STATUSES: APPROVAL_STATUSES,
        FORM_OWNED_KEYS: FORM_OWNED_KEYS,
        createInitialState: createInitialState,
        workingEntryFrom: workingEntryFrom,
        dispatch: dispatch,
        select: select,
        getState: getState,
        subscribe: subscribe,
        resolve: resolve,
        reset: reset,
        text: text
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));