/* Voices V3 — pure markup builders.
 *
 * Every function here takes plain data and returns an HTML string. None of them
 * reads the DOM or holds state, so a card can be rebuilt from the store at any
 * time without first checking what the page currently looks like.
 *
 * Interactivity is expressed with `data-voicesv3-action` attributes rather than
 * inline `onclick`. That is the one structural difference from the original tab
 * and it is what lets the whole roster be re-rendered without re-binding a single
 * listener.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var labels = namespace.labels;
    var escape = core.escape;

    function attr(value) { return escape(value); }

    function option(value, label, selected, disabled) {
        return '<option value="' + attr(value) + '"' + (selected ? ' selected' : '')
            + (disabled ? ' disabled' : '') + '>' + escape(label) + '</option>';
    }

    function optionList(options, selected) {
        return options.map(function (entry) {
            return option(entry.value, entry.label, entry.value === selected, !!entry.disabled);
        }).join('');
    }

    /* ---- status and banner blocks ---- */

    function alert(kind, html) {
        return '<div class="alert alert-' + kind + '">' + html + '</div>';
    }

    function seedRepairBanner(changes, pending) {
        if (!changes || !changes.length) { return ''; }
        var rows = changes.map(function (change) {
            return '<li>' + escape(change.name) + ': proposed seed ' + escape(change.seed) + '</li>';
        }).join('');
        return alert('warning',
            '<strong>' + changes.length + ' unseeded voice settings</strong>'
            + '<ul>' + rows + '</ul>'
            + '<p>' + escape(labels.SEED_REPAIR_HELP) + '</p>'
            + '<button type="button" class="btn btn-sm btn-outline-warning" data-voicesv3-action="seed-repair"'
            + (pending ? ' disabled' : '') + '>Apply stable seeds to unseeded entries only</button>');
    }

    function draftBanner(drafts, bookToken) {
        if (!drafts || !drafts.length) { return ''; }
        return drafts.map(function (record, index) {
            var matches = record.book_token === bookToken;
            var recover = matches
                ? '<button type="button" class="btn btn-sm btn-warning" data-voicesv3-action="draft-recover"'
                  + ' data-voicesv3-index="' + index + '">Recover edits</button>'
                : 'Load the original book version to recover this draft.';
            return alert('warning',
                '<strong>Unsaved voice draft</strong> ' + escape(record.book_id || 'unnamed book')
                + ' · ' + escape(record.updated || '')
                + '<details><summary>View saved edits</summary><pre class="text-wrap">'
                + escape(JSON.stringify(record.voices, null, 2)) + '</pre></details>'
                + recover
                + ' <button type="button" class="btn btn-sm btn-link" data-voicesv3-action="draft-discard"'
                + ' data-voicesv3-index="' + index + '">Discard draft</button>');
        }).join('');
    }

    function emptyRoster() {
        return alert('info', 'No voices found. Generate a script first.');
    }

    /* ---- trait badge ---- */

    function traitBadge(traits) {
        var computed = namespace.selectors.selectTraitBadge(traits);
        if (!computed) { return ''; }
        return '<span class="badge bg-light text-dark border ms-2" title="'
            + 'Model-inferred from ' + computed.lines + ' script lines; review against the source">'
            + 'Script estimate: ' + escape(computed.summary) + '</span>';
    }

    /* ---- candidates ---- */

    function candidateRows(candidates) {
        if (!candidates || !candidates.length) { return ''; }
        var rows = candidates.map(function (candidate) {
            var id = candidate.candidate_id || '';
            return '<div class="d-flex align-items-center gap-1 mt-1">'
                + '<span class="text-truncate" title="' + attr(id) + '">' + escape(id)
                + (candidate.rank ? ' · #' + escape(candidate.rank) : '') + '</span>'
                + '<button class="btn btn-sm ' + (candidate.favorite ? 'btn-warning' : 'btn-outline-warning')
                + ' py-0" type="button" data-voicesv3-action="candidate-favorite"'
                + ' data-voicesv3-name="' + attr(candidate.name || '') + '" data-voicesv3-id="' + attr(id) + '"'
                + ' data-voicesv3-value="' + (candidate.favorite ? 'false' : 'true') + '"'
                + ' data-voice-focus-key="candidate-favorite:' + attr(id) + '"'
                + ' aria-label="' + (candidate.favorite ? 'Unfavourite' : 'Favourite') + ' candidate ' + attr(id) + '">★</button>'
                + '<button class="btn btn-sm btn-outline-success py-0" type="button" data-voicesv3-action="candidate-select"'
                + ' data-voicesv3-name="' + attr(candidate.name || '') + '" data-voicesv3-id="' + attr(id) + '"'
                + ' aria-label="Use candidate ' + attr(id) + '">Use</button>'
                + '<button class="btn btn-sm btn-outline-danger py-0" type="button" data-voicesv3-action="candidate-delete"'
                + ' data-voicesv3-name="' + attr(candidate.name || '') + '" data-voicesv3-id="' + attr(id) + '"'
                + ' aria-label="Delete candidate ' + attr(id) + '">×</button>'
                + '</div>';
        }).join('');
        return '<div class="small mt-2"><strong>Saved candidates</strong>' + rows + '</div>';
    }

    /* ---- style timeline ---- */

    function styleTimeline(points, name) {
        if (!points || !points.length) { return ''; }
        var badges = points.map(function (point) {
            return '<span class="badge bg-light text-dark border">from line ' + (point.from_index + 1) + ': '
                + escape(point.character_style)
                + ' <a href="#" title="Remove" data-voicesv3-action="style-point-remove"'
                + ' data-voicesv3-name="' + attr(name) + '" data-voicesv3-index="' + point.from_index + '">'
                + '&times;</a></span>';
        }).join(' ');
        return '<div class="small text-muted mt-1">Changes: ' + badges + '</div>';
    }

    /* ---- ensemble members ---- */

    function ensembleMembers(allNames, members, suggestions, scope) {
        var selected = members || [];
        var ordered = [];
        // Suggestions first so a freshly prefilled ensemble is visible, then the
        // rest of the roster alphabetically.
        (suggestions || []).forEach(function (name) { if (ordered.indexOf(name) < 0) { ordered.push(name); } });
        (allNames || []).forEach(function (name) {
            if (ordered.indexOf(name) < 0) { ordered.push(name); }
        });
        if (!ordered.length) { return '<span class="text-muted">No other characters yet.</span>'; }
        return ordered.map(function (name) {
            var isSelected = selected.indexOf(name) >= 0;
            // The owning character is resolved from the enclosing card by the
            // assignment panel, so no per-checkbox owner attribute is needed.
            return '<div class="form-check">'
                + '<input class="form-check-input ensemble-member" type="checkbox" value="' + attr(name) + '"'
                + ' data-voicesv3-action="ensemble-member"' + (scope || '')
                + (isSelected ? ' checked' : '') + '>'
                + '<label class="form-check-label">' + escape(name) + '</label>'
                + '</div>';
        }).join('');
    }

    /* ---- catalogue option lists ---- */

    function customVoiceOptions(names, selected) {
        return names.map(function (name) { return option(name, name, name === selected); }).join('');
    }

    function builtinLoraGroups(state, selectedId) {
        var groups = namespace.selectors.selectBuiltinLoraGroups(state);
        var html = option('', '-- Select built-in voice --', !selectedId);
        function rows(models) {
            return models.map(function (model) {
                var label = (model.favorite ? '★ ' : '') + (model.name || model.id || '');
                if (model.downloaded === false) { label += ' (not downloaded)'; }
                if (model.description) { label += ' — ' + model.description; }
                return option(model.id, label, model.id === selectedId, model.downloaded === false);
            }).join('');
        }
        if (groups.male.length) { html += '<optgroup label="Male">' + rows(groups.male) + '</optgroup>'; }
        if (groups.female.length) { html += '<optgroup label="Female">' + rows(groups.female) + '</optgroup>'; }
        return html;
    }

    function userLoraOptions(state, selectedId) {
        var models = namespace.selectors.selectUserLoraModels(state);
        if (!models.length) { return option('', '-- No trained adapters yet --', true, true); }
        return option('', '-- Select trained adapter --', !selectedId)
            + models.map(function (model) {
                return option(model.id, (model.favorite ? '★ ' : '') + (model.name || model.id || ''), model.id === selectedId);
            }).join('');
    }

    function referenceVoiceOptions(state, reference, refAudio) {
        var clones = namespace.selectors.selectCloneVoices(state);
        var designs = namespace.selectors.selectDesignedVoices(state);
        var html = option('', '-- Select voice or enter path manually --', !reference && !refAudio);
        if (clones.length) {
            html += '<optgroup label="Uploaded Voices">' + clones.map(function (voice) {
                return option('clone:' + voice.id, voice.name || voice.id,
                    !!(reference && reference.type === 'clone' && reference.id === voice.id));
            }).join('') + '</optgroup>';
        }
        if (designs.length) {
            html += '<optgroup label="Designed Voices">' + designs.map(function (voice) {
                return option('design:' + voice.id, voice.name || voice.id,
                    !!(reference && reference.type === 'design' && reference.id === voice.id));
            }).join('') + '</optgroup>';
        }
        html += option('__manual__', 'Custom path...', !!refAudio && !reference);
        return html;
    }

    namespace.markup = {
        option: option,
        optionList: optionList,
        alert: alert,
        seedRepairBanner: seedRepairBanner,
        draftBanner: draftBanner,
        emptyRoster: emptyRoster,
        traitBadge: traitBadge,
        candidateRows: candidateRows,
        styleTimeline: styleTimeline,
        ensembleMembers: ensembleMembers,
        customVoiceOptions: customVoiceOptions,
        builtinLoraGroups: builtinLoraGroups,
        userLoraOptions: userLoraOptions,
        referenceVoiceOptions: referenceVoiceOptions
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));