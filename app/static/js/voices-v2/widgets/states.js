/* Voices V2 — status, empty and banner markup.
 *
 * Every state the browser can be in, in one place, so a new panel cannot invent a
 * fourth way to say "nothing here". Four states, each saying what happened and
 * what to do next:
 *
 *   loading    a read is in flight
 *   empty      the book has no characters yet
 *   noResults  the book has characters, the current search and filters exclude all
 *   error      the read failed
 *
 * All four are also announced through the tab's live region by lifecycle.js, so
 * none of this is colour-only or screen-reader-silent.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var labels = namespace.labels;

    var REGION = '[data-voicesv2-region="status"]';

    function loadingMarkup() {
        return '<div class="alert alert-secondary mb-0 vv2-state" role="status">'
            + 'Reading the Voices V2 character projection...</div>';
    }

    /* A book with no script is not a failure. The Voices tab answers 422 here;
     * this tab explains what to do instead, which is the difference between an
     * error and a first run. */
    function emptyMarkup() {
        return '<div class="alert alert-info mb-0 vv2-state" role="status">'
            + '<strong>No characters yet.</strong> Voices V2 reads the active script, so it has '
            + 'nothing to show until a script is generated or a saved book is opened.'
            + '</div>';
    }

    function noResultsMarkup(summary) {
        var narrowed = [];
        if (summary.narrowed) { narrowed.push('search or filters'); }
        return '<div class="alert alert-warning mb-0 vv2-state" role="status">'
            + '<strong>No characters match.</strong> '
            + (narrowed.length ? 'The current ' + narrowed.join(' and ')
                + ' exclude all ' + summary.scoped + ' in scope.'
                : 'Nothing is in the current scope.')
            + ' <button type="button" class="btn btn-sm btn-outline-secondary ms-1" '
            + 'data-voicesv2-action="clear-filters">Clear filters</button>'
            + '</div>';
    }

    function errorMarkup(message) {
        return '<div class="alert alert-danger mb-0 vv2-state" role="alert">'
            + '<strong>Voices V2 could not read the character projection.</strong><br>'
            + core.escape(message)
            + '<br>Voices V2 is a separate workspace and shares nothing with the Voices tab, '
            + 'so this does not affect voices already assigned there. '
            + '<button type="button" class="btn btn-sm btn-outline-danger mt-2" '
            + 'data-voicesv2-action="retry">Retry</button>'
            + '</div>';
    }

    /* Traits are a book-level fact, so the warning belongs beside the controls
     * that would otherwise imply otherwise. It names the switch that produced
     * them rather than guessing why they are missing. */
    function traitsBanner(meta) {
        if (meta.traitsAvailable) { return ''; }
        var requested = meta.traitsRequested === true
            ? 'Script generation recorded the trait switch as on, but no line carries speaker traits.'
            : 'Script generation was run without per-line speaker traits.';
        return '<div class="alert alert-secondary mb-0 vv2-state vv2-traits-note" role="status">'
            + '<strong>Speaker traits are not available for this book.</strong> ' + requested
            + ' Gender and age are only recorded when the active script was generated with'
            + ' per-line speaker traits, so the filters for them are disabled.'
            + '</div>';
    }

    function aliasesBanner(meta) {
        if (meta.aliasesRegistered) { return ''; }
        return '<p class="small text-muted mb-0 vv2-state">'
            + 'No character aliases are registered for this book, so search covers names,'
            + ' voice labels and adapter ids only.</p>';
    }

    function detailEmptyMarkup() {
        return '<div class="vv2-detail-empty text-muted small" role="status">'
            + 'Select a character to inspect their voice, traits, versions and persona.'
            + '</div>';
    }

    namespace.states = {
        REGION: REGION,
        loadingMarkup: loadingMarkup,
        emptyMarkup: emptyMarkup,
        noResultsMarkup: noResultsMarkup,
        errorMarkup: errorMarkup,
        traitsBanner: traitsBanner,
        aliasesBanner: aliasesBanner,
        detailEmptyMarkup: detailEmptyMarkup
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));