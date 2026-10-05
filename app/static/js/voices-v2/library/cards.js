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
    var state = namespace.state;

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

    /* Phase 3 had one static button here. It now delegates to previewControl,
     * which is the single place that decides between Play, Generate and Retry
     * from the same state - so a card can never offer a control the data cannot
     * back, and a generated preview appears in exactly the same control a
     * recorded one did. */
    function previewButton(voice) {
        return previewControl(voice);
    }

    /* The preview control, which is never a dead button.
 *
 * Four states, each with its own action:
 *   nothing yet   Generate Preview, enabled when the voice can be generated
 *   queued/running a disabled control plus the live status, so a second click
 *                 cannot become a second render
 *   ready         Play, or Stop while this voice is the one playing
 *   failed        Retry, with the server's own message
 *
 * The status line is plain text rather than a spinner so the state is readable
 * without colour or motion.
 */
    function previewControl(voice) {
        var previews = namespace.libraryPreviews;
        var generating = previews.isGenerating(voice);
        var label = previews.previewLabel(voice);
        var detail = previews.previewDetail(voice);
        var playing = namespace.libraryAudio.isPlaying(voice.voiceId);
        var loading = namespace.libraryAudio.isLoading(voice.voiceId);
        var status = '<p class="vv2-preview-state vv2-preview-' + core.escape(
            generating ? 'generating' : (label === 'Preview failed' ? 'failed' : 'idle')
        ) + '" role="status">'
            + '<span class="vv2-preview-label">' + core.escape(label) + '</span>'
            + (detail ? ' <span class="vv2-muted">&mdash; ' + core.escape(detail) + '</span>' : '')
            + '</p>';

        var control;
        if (generating) {
            control = '<button type="button" class="btn btn-sm btn-outline-secondary"'
                + ' data-voicesv2-action="cancel-preview"'
                + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '"'
                + ' data-voicesv2-job="' + core.escape(voiceJobId(voice)) + '"'
                + '>Cancel</button>';
        } else if (label === 'Preview failed' && previews.canRetry(voice)) {
            control = '<button type="button" class="btn btn-sm btn-outline-danger"'
                + ' data-voicesv2-action="generate-preview"'
                + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '">Retry</button>';
        } else if (previews.canPlay(voice)) {
            control = '<button type="button" class="btn btn-sm btn-outline-secondary"'
                + ' data-voicesv2-action="play-preview"'
                + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '"'
                + ' aria-pressed="' + (playing ? 'true' : 'false') + '"'
                + (loading ? ' disabled' : '') + '>'
                + core.escape(loading ? 'Loading\u2026' : (playing ? 'Stop' : 'Play'))
                + '</button>';
        } else if (voice.previewGeneratable && voice.available) {
            control = '<button type="button" class="btn btn-sm btn-outline-primary"'
                + ' data-voicesv2-action="generate-preview"'
                + ' data-voicesv2-voice="' + core.escape(voice.voiceId) + '">'
                + 'Generate Preview</button>';
        } else {
            /* Nothing to offer, and the status line has already said why. */
            control = '';
        }

        return '<div class="vv2-voice-preview">' + status
            + '<div class="vv2-voice-actions">' + control + '</div></div>';
    }

    function voiceJobId(voice) {
        var job = namespace.libraryPreviews.effectiveJob(state.getState(), voice);
        return job && job.jobId ? job.jobId : '';
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
            + favouriteButton(voice)
            + '</div>'
            + previewControl(voice)
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