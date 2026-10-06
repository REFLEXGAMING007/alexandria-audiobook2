/* Voices V3 — the roster.
 *
 * Owns the container every character card is rendered into, plus the seed-repair
 * banner that sits above them. State panels are filled immediately after the
 * cards, because a card only creates the panel's container — the content comes
 * from a separate read that may not have happened yet.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var states = namespace.statesPanel;
    var escape = core.escape;

    var bound = false;

    function render(state) {
        var container = core.region('roster');
        if (!container) { return; }

        var rows = selectors.selectVisibleRows(state);
        var snapshot = namespace.saveController ? namespace.saveController.getSnapshot() : null;

        var html = markup.seedRepairBanner(state.seedRepair.changes, state.seedRepair.pending)
            + markup.draftBanner(state.save.recoveryDrafts, snapshot ? snapshot.bookToken : null);

        if (!rows.length) {
            // An empty roster is a first-run state, not a failure. The seed banner
            // may still be present above it, so it is appended rather than replaced.
            container.innerHTML = html + markup.emptyRoster();
            return;
        }

        html += rows.map(function (row, index) {
            return namespace.cardPanel.card(state, row, index);
        }).join('');

        container.innerHTML = html;

        // State panels are painted after the cards so their containers exist.
        rows.forEach(function (row) {
            states.renderPanel(state, row.name);
        });
    }

    /* A state panel can change on its own — a load finishing, a save landing —
     * without the roster needing a full repaint. */
    function refreshStatePanels(state) {
        selectors.selectRosterRows(state).forEach(function (row) {
            states.renderPanel(state, row.name);
        });
    }

    /* Candidates are re-fetched after a favourite or a use, and the change is
     * confined to one character's block. */
    function refreshCandidates(state, name) {
        var host = core.region('roster');
        if (!host || !name) { return; }
        var block = host.querySelector('[data-voicesv3-candidates="' + String(name).replace(/"/g, '\\"') + '"]');
        if (!block) { return; }
        var candidates = selectors.selectCandidates(state, name).map(function (candidate) {
            return Object.assign({}, candidate, { name: name });
        });
        block.innerHTML = markup.candidateRows(candidates);
    }

    function bind() {
        if (bound) { return; }
        bound = true;
        var container = core.region('roster');
        if (!container) { return; }
        // One delegated listener for the whole roster. Every control inside a card
        // is reachable from here, so a re-render never needs re-binding.
        container.addEventListener('change', namespace.events.onRosterChange);
        container.addEventListener('input', namespace.events.onRosterInput);
        container.addEventListener('click', namespace.events.onRosterClick);
    }

    function unbind() {
        // The delegated listeners live on the container, which survives a re-render,
        // so they are intentionally not removed. `bound` guards double-binding.
    }

    function mount() {
        bind();
    }

    namespace.rosterPanel = {
        mount: mount,
        bind: bind,
        unbind: unbind,
        render: render,
        refreshStatePanels: refreshStatePanels,
        refreshCandidates: refreshCandidates
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));