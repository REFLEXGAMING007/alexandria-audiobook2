/* Voices V2 — display vocabulary.
 *
 * One owner for every human-facing string a record turns into. Panels call these
 * and never spell an enum inline, so `unknown` cannot be shown as a blank cell
 * in one place and as "Unknown" in another, and a wording change is one edit.
 *
 * The wording follows docs/UI_GUIDELINES.md: where the backend genuinely does not
 * know, the UI says Unknown or Unavailable rather than leaving a gap that reads
 * as "nothing to report".
 */
(function (namespace) {
    'use strict';

    var store = namespace.state;

    var NOT_AVAILABLE = 'Not available';

    var GENDER_LABELS = {
        male: 'Male',
        female: 'Female',
        genderless: 'Genderless',
        unknown: 'Unknown'
    };

    var VOICE_CATEGORY_LABELS = {
        custom: 'Custom voice',
        clone: 'Voice clone',
        lora: 'LoRA voice',
        design: 'Designed voice',
        ensemble: 'Ensemble'
    };

    var ASSIGNED_LABELS = { true: 'Assigned', false: 'Unassigned' };

    var PRIORITY_LABELS = { major: 'Major', minor: 'Minor', null: 'No lines' };

    var READY_LABELS = { true: 'Ready', false: 'Not ready' };

    /* Stable codes -> wording. `detail` is the honest explanation, not a fix:
     * Voices V2 reports, and repairing any of these is a separate decision. */
    var PROBLEM_TEXT = {
        config_without_script_line: {
            title: 'No script line',
            detail: 'A voice configuration exists but the character is not in the active script. '
                + 'Voices V2 shows it rather than deleting it.'
        },
        no_spoken_lines: {
            title: 'No spoken lines',
            detail: 'The character is in the active script but has no line with text.'
        },
        unknown_speaker_label: {
            title: 'Unknown speaker label',
            detail: 'The speaker could not be identified during attribution, so traits and '
                + 'per-character data may be wrong.'
        },
        voice_unassigned: {
            title: 'No voice',
            detail: 'No voice has been assigned to this character yet.'
        },
        voice_unavailable: {
            title: 'Voice files missing',
            detail: 'The configuration points at an adapter or reference recording that is not on disk.'
        },
        persona_ref_missing: {
            title: 'Persona file missing',
            detail: 'The stored persona reference does not resolve to a file.'
        },
        alias_of_missing: {
            title: 'Voice alias missing',
            detail: 'The configuration defers to another character who has no configuration.'
        },
        voice_status_conflict: {
            title: 'Status disagrees with the voice',
            detail: 'The stored voice status says unassigned while a voice is configured. '
                + 'The voice shown here is the configured one.'
        },
        multiple_versions_per_age: {
            title: 'Duplicate versions for one age',
            detail: 'More than one saved version targets the same age group, so which one a '
                + 'timeline picks is ambiguous.'
        },
        possible_duplicate_identity: {
            title: 'Possible duplicate character',
            detail: 'Another name in this book differs only by spacing or punctuation. Voices V2 '
                + 'does not merge them; review both.'
        }
    };

    function titleise(value) {
        var text = (value === null || value === undefined) ? '' : String(value);
        var spaced = text.replace(/[_-]+/g, ' ').trim();
        return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : NOT_AVAILABLE;
    }

    function genderLabel(value) {
        if (!value) { return NOT_AVAILABLE; }
        return GENDER_LABELS[value] || titleise(value);
    }

    /* Age band labels come from the projection so the list cannot drift from
     * speaker_traits.AGE_GROUPS. `young_adult` is written "18-29" server-side. */
    function ageGroupLabel(value) {
        if (!value) { return NOT_AVAILABLE; }
        var known = (store.getState().meta.vocabularies.ageGroups || []).filter(function (group) {
            return group.value === value;
        })[0];
        if (known && known.label) { return known.label + ' (' + titleise(known.value) + ')'; }
        return titleise(value);
    }

    function voiceCategoryLabel(value) {
        return VOICE_CATEGORY_LABELS[value] || titleise(value);
    }

    function assignedLabel(assigned) {
        return assigned ? ASSIGNED_LABELS.true : ASSIGNED_LABELS.false;
    }

    function priorityLabel(priority) {
        if (priority === null || priority === undefined) { return PRIORITY_LABELS.null; }
        return PRIORITY_LABELS[priority] || titleise(priority);
    }

    function readyLabel(ready) {
        return ready ? READY_LABELS.true : READY_LABELS.false;
    }

    function personaStatusLabel(value) {
        if (!value) { return 'No persona'; }
        return titleise(value);
    }

    function problemText(code) {
        return PROBLEM_TEXT[code] || { title: titleise(code), detail: NOT_AVAILABLE };
    }

    /* Traits are a pair of independent facts. Rendering them separately, and
     * rendering "Unavailable" when the book has none, is the whole point: an
     * absent summary must not read as a character with no gender. */
    function traitSentence(traits, traitsAvailable) {
        if (!traitsAvailable || !traits) { return NOT_AVAILABLE; }
        var age = ageGroupLabel(traits.ageGroup);
        return genderLabel(traits.gender) + ' \u00b7 ' + age + (traits.ageless ? ' \u00b7 ageless' : '');
    }

    function lineCountLabel(lineCount) {
        var count = (typeof lineCount === 'number' && isFinite(lineCount)) ? lineCount : 0;
        return count === 1 ? '1 line' : count + ' lines';
    }

    namespace.labels = {
        NOT_AVAILABLE: NOT_AVAILABLE,
        genderLabel: genderLabel,
        ageGroupLabel: ageGroupLabel,
        voiceCategoryLabel: voiceCategoryLabel,
        assignedLabel: assignedLabel,
        priorityLabel: priorityLabel,
        readyLabel: readyLabel,
        personaStatusLabel: personaStatusLabel,
        problemText: problemText,
        traitSentence: traitSentence,
        lineCountLabel: lineCountLabel,
        titleise: titleise,
        sortKeyLabel: function (key) {
            var labels = {
                name: 'Name', lineCount: 'Line count', priority: 'Priority',
                voiceStatus: 'Voice status', voice: 'Voice', ready: 'Readiness',
                traitOrder: 'Age'
            };
            return labels[key] || titleise(key);
        },
        filterKeyLabel: function (key) {
            var labels = {
                query: 'Search', scope: 'Show', gender: 'Gender', ageGroup: 'Age',
                assigned: 'Voice', ready: 'Readiness', personaStatus: 'Persona',
                priority: 'Priority', problems: 'Problems', sort: 'Sort by'
            };
            return labels[key] || titleise(key);
        }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));