/* Voices V2 — the character list.
 *
 * A row is a button, not a div with a click handler: keyboard focus, Enter and
 * Space then work without any key handling, and the selected row carries
 * `aria-current="true"` so the selection is announced rather than only drawn.
 *
 * The row shows what a user needs to decide whether to open a character, and
 * nothing that would turn it into a second version of the Voices card: name,
 * lines, priority, voice, traits, readiness and warnings. Everything else lives
 * in the detail panel.
 *
 * Selection uses the record's `key`, which the backend derives from the stored
 * name. Sorting or filtering never changes who is selected, because position is
 * never an identity here.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var selectors = namespace.selectors;
    var labels = namespace.labels;
    var states = namespace.states;

    var bound = false;

    function listRegion() {
        return core.region('characters');
    }

    /* Status is never conveyed by colour alone: every badge carries a word. */
    function badge(text, modifier, extra) {
        return '<span class="badge vv2-badge vv2-badge-' + core.escape(modifier)
            + (extra ? ' ' + core.escape(extra) : '') + '">' + core.escape(text) + '</span>';
    }

    function voiceBadge(character) {
        if (!character.voice.assigned) {
            return badge(labels.assignedLabel(false), 'warning', 'vv2-badge-unassigned');
        }
        return badge(character.voice.label, 'secondary');
    }

    function traitBadge(character, traitsAvailable) {
        if (!traitsAvailable || !character.traits) {
            return badge(labels.NOT_AVAILABLE, 'light', 'vv2-badge-unknown');
        }
        return badge(labels.traitSentence(character.traits, traitsAvailable), 'light');
    }

    function warningBadges(character) {
        if (!character.problems.length) { return ''; }
        /* The count, not every code: the detail panel explains each one, and a row
         * covered in badges stops being scannable. */
        return badge(character.problems.length + (character.problems.length === 1
            ? ' warning' : ' warnings'), 'danger', 'vv2-badge-warning');
    }

    function rowMarkup(character, nextState, selectedKey) {
        var selected = character.key === selectedKey;
        var classes = ['vv2-row'];
        if (selected) { classes.push('is-selected'); }
        if (!character.presentInScript) { classes.push('is-orphan'); }
        return '<li class="vv2-row-item">'
            + '<button type="button" class="' + classes.join(' ') + '"'
            + ' data-voicesv2-character="' + core.escape(character.key) + '"'
            + ' aria-current="' + (selected ? 'true' : 'false') + '">'
            + '<span class="vv2-row-head">'
            + '<span class="vv2-row-name">' + core.escape(character.name) + '</span>'
            + badgesMarkup(character, nextState)
            + '</span>'
            + '<span class="vv2-row-meta">'
            + core.escape(labels.lineCountLabel(character.lineCount))
            + ' \u00b7 ' + core.escape(labels.priorityLabel(character.priority))
            + (character.versions.length
                ? ' \u00b7 ' + character.versions.length
                  + (character.versions.length === 1 ? ' version' : ' versions')
                : '')
            + '</span>'
            + '</button></li>';
    }

    function badgesMarkup(character, nextState) {
        return '<span class="vv2-row-badges">'
            + voiceBadge(character)
            + (character.ready ? badge(labels.readyLabel(true), 'success') : '')
            + traitBadge(character, nextState.meta.traitsAvailable)
            + warningBadges(character)
            + '</span>';
    }

    /* Rebuilt on every render. At the scale this is built for — one entry per
     * named character in one book — that is a few hundred nodes, and it removes a
     * whole class of diffing bugs. Phase 2 can revisit it if a book ever needs
     * more; the selector boundary means that change would be local to this file. */
    function render(nextState) {
        var container = listRegion();
        if (!container) { return false; }
        var visible = selectors.selectVisible(nextState);
        var summary = selectors.selectSummary(nextState);

        if (!nextState.meta.book.scriptPresent) {
            container.innerHTML = states.emptyMarkup();
            return true;
        }
        if (!summary.total) {
            container.innerHTML = states.emptyMarkup();
            return true;
        }
        if (!visible.length) {
            container.innerHTML = states.noResultsMarkup(summary);
            return true;
        }
        container.innerHTML = '<ul class="vv2-list" role="list">'
            + visible.map(function (character) {
                return rowMarkup(character, nextState, nextState.selection.key);
            }).join('')
            + '</ul>';
        return true;
    }

    function bind() {
        if (bound) { return false; }
        var container = listRegion();
        if (!container) { return false; }
        container.addEventListener('click', function (event) {
            var origin = event && event.target;
            var row = origin && origin.closest ? origin.closest('[data-voicesv2-character]') : null;
            if (!row || !core.contains(row)) { return; }
            state.dispatch({ type: 'selection/set', key: row.getAttribute('data-voicesv2-character') });
        });
        bound = true;
        return true;
    }

    function unmount() {
        bound = false;
    }

    function mount() {
        bind();
    }

    namespace.charactersPanel = {
        mount: mount,
        render: render,
        unmount: unmount,
        badge: badge
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));