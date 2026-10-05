/* Voices V2 — the reusable voice card.
 *
 * A card is a list item containing real buttons, not a div with click handlers:
 * focus, Enter and Space then work without any key handling, and every state a
 * user needs to read is a word rather than a colour.
 *
 * Four states are legible from text alone:
 *   available   "Available" / "Not available", plus the reason when it is not
 *   favourite    "Favourite" / "Not a favourite" on the star's accessible name
 *   selected     `aria-current="true"` and a "Selected" line, plus a left rule
 *   provenance   "Declared" / "Inferred" / "Unknown" beside gender and age
 *
 * The provenance suffix is why the library is trustworthy: a gender guessed from
 * an adapter's name looks identical to a stated one unless the card says which
 * it is, and a user who cannot tell will over-trust it.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;

    var PROVENANCE_LABELS = { declared: 'declared', inferred: 'inferred',
        unknown: 'unknown' };

    function badge(text, modifier) {
        return '<span class="badge vv2-badge vv2-badge-' + core.escape(modifier) + '">'
            + core.escape(text) + '</span>';
    }

    function value(text, modifier) {
        return '<span' + (modifier ? ' class="' + core.escape(modifier) + '"' : '') + '>'
            + core.escape(text) + '</span>';
    }

    /* Gender and age, each labelled with how it is known. */
    function traitLine(voice, labels) {
        var gender = labels.genderLabel(voice.gender);
        var age = labels.ageGroupLabel(voice.ageGroup);
        var parts = [
            gender + ' (' + (PROVENANCE_LABELS[voice.genderSource] || 'unknown') + ')',
            age + ' (' + (PROVENANCE_LABELS[voice.ageGroupSource] || 'unknown') + ')'
        ];
        if (voice.ageless) { parts.push('ageless'); }
        return core.escape(parts.join(' \u00b7 '));
    }

    function favouriteButton(voice) {
        if (!voice.favoriteSupported) {
            /* A dead star is worse than no star: say why instead. */
            return '<span class="small vv2-muted">Favourites are for LoRA voices</span>';
        }
        /* The glyph changes shape as well as colour, and `aria-pressed` carries
         * the state, so the favourite is readable three ways. */
        var action = voice.favorite ? 'Remove from favourites' : 'Add to favourites';
        return '<button type="button" class="btn btn-sm vv2-fav-button"'
            + ' data-voicesv2-action="toggle-favorite"'
            + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '"'
            + ' aria-pressed="' + (voice.favorite ? 'true' : 'false') + '"'
            + ' title="' + core.escape(action) + '">'
            + '<span aria-hidden="true">' + (voice.favorite ? '\u2605' : '\u2606') + '</span>'
            + ' Favourite</button>';
    }

    function previewButton(voice) {
        if (!voice.previewCapable) {
            /* No preview available is a fact about the data, so it is stated
             * once per card rather than shown as a control that cannot work. */
            return '<span class="small vv2-muted">No preview recorded</span>';
        }
        var playing = namespace.libraryAudio.isPlaying(voice.voiceId);
        var loading = namespace.libraryAudio.isLoading(voice.voiceId);
        var label = loading ? 'Loading preview' : (playing ? 'Stop preview' : 'Play preview');
        return '<button type="button" class="btn btn-sm btn-outline-secondary"'
            + ' data-voicesv2-action="preview-voice"'
            + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '"'
            + ' aria-pressed="' + (playing ? 'true' : 'false') + '"'
            + (loading ? ' disabled' : '') + '>'
            + core.escape(loading ? 'Loading\u2026' : (playing ? 'Stop' : 'Preview'))
            + '<span class="vv2-sr-only"> ' + core.escape(label) + '</span></button>';
    }

    function card(voice, options) {
        var settings = options || {};
        var labels = namespace.labels;
        var selected = settings.selectedVoiceId === voice.voiceId;
        var cursor = settings.cursorVoiceId === voice.voiceId;
        var classes = ['vv2-voice-card'];
        if (selected) { classes.push('is-selected'); }
        if (cursor) { classes.push('is-cursor'); }
        if (!voice.available) { classes.push('is-unavailable'); }

        return '<li class="vv2-voice-item">'
            + '<div class="' + classes.join(' ') + '">'
            + '<div class="vv2-voice-head">'
            + '<span class="vv2-voice-name">' + core.escape(voice.name) + '</span>'
            + badges(voice, selected)
            + '</div>'
            + '<div class="vv2-voice-meta">'
            + core.escape(traitLine(voice, labels))
            + ' \u00b7 ' + core.escape(voice.source)
            + ' \u00b7 ' + core.escape(voice.availability === 'available'
                ? 'Available' : 'Not available')
            + '</div>'
            + (voice.description
                ? '<p class="vv2-voice-description">' + core.escape(voice.description) + '</p>'
                : '<p class="vv2-voice-description vv2-muted">No description recorded.</p>')
            + (voice.available ? ''
                : '<p class="small vv2-voice-reason">' + core.escape(voice.unavailableReason) + '</p>')
            + (selected
                ? '<p class="small vv2-voice-selected-note">'
                  + 'Selected for this character. Save to apply it.</p>'
                : '')
            + '<div class="vv2-voice-actions">'
            + '<button type="button" class="btn btn-sm vv2-choose-button"'
            + ' data-voicesv2-action="choose-voice"'
            + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '"'
            + (voice.available ? '' : ' disabled')
            + '>' + core.escape(selected ? 'Chosen' : 'Choose') + '</button>'
            + previewButton(voice)
            + favouriteButton(voice)
            + '</div>'
            + '</div>'
            + '</li>';
    }

    function badges(voice, selected) {
        var out = [];
        out.push(badge(voice.source, 'light'));
        if (voice.favorite) { out.push(badge('Favourite', 'warning')); }
        if (selected) { out.push(badge('Selected', 'success')); }
        return out.join('');
    }

    function list(voices, options) {
        if (!voices.length) { return ''; }
        return '<ul class="vv2-voice-list" role="list">' + voices.map(function (voice) {
            return card(voice, options);
        }).join('') + '</ul>';
    }

    namespace.libraryCards = {
        card: card,
        list: list,
        badge: badge,
        PROVENANCE_LABELS: PROVENANCE_LABELS
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));