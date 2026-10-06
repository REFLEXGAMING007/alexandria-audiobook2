/* Voices V3 — the per-character card.
 *
 * This is a feature-for-feature replica of the original tab's voice card: the
 * same identity column, the same two independent review axes, the same version
 * select, the same state-change entry point, the same candidates list, the same
 * ready switch and alias select, and all six voice-type option blocks.
 *
 * It renders from the store. Nothing here reads the DOM to decide what to show,
 * which is the whole reason a re-render cannot lose an edit.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var labels = namespace.labels;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var escape = core.escape;

    function attr(value) { return escape(value); }

    function text(value) { return typeof value === 'string' ? value : ''; }

    /* ---- identity column ---- */

    function aliasBadge(name, aliasOf) {
        if (!aliasOf) { return ''; }
        return '<span class="badge bg-info ms-2" title="Alias of ' + attr(aliasOf) + '">' + escape(aliasOf) + '</span>';
    }

    function lineCountBadge(lineCount) {
        if (lineCount === null || lineCount === undefined) { return ''; }
        return '<span class="badge bg-secondary ms-2" title="' + escape(lineCount)
            + ' lines in this book">' + escape(lineCount) + ' lines</span>';
    }

    function reviewStatusLine(config) {
        return '<div class="small text-muted">Persona review: ' + escape(config.persona_status || 'unreviewed')
            + ' · Voice review: ' + escape(config.voice_status || 'unassigned') + '</div>';
    }

    function personaAuditLine(name, config) {
        var audit = config.persona_voice_audit;
        if (!audit || typeof audit !== 'object') { return ''; }
        return '<div class="small text-muted" title="' + attr(audit.suggestion_reason || '') + '">'
            + 'Persona-to-voice audit: ' + escape(audit.voice_adapter_id || 'manual')
            + ' · ' + escape(audit.persona_ref || 'inline persona')
            + ' <button class="btn btn-sm btn-link p-0" type="button" data-voicesv3-action="persona-audit-edit"'
            + ' data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="Edit persona-to-voice audit for ' + attr(name) + '">Edit</button></div>';
    }

    function approvalButtons(name) {
        return '<div class="btn-group btn-group-sm mt-1" role="group" aria-label="Approval status" aria-describedby="voicesv3-approval-help">'
            + labels.APPROVAL_ACTIONS.map(function (action) {
                return '<button class="btn ' + action.kind + '" type="button"'
                    + ' data-voicesv3-action="approval" data-voicesv3-name="' + attr(name) + '"'
                    + ' data-voicesv3-field="' + attr(action.field) + '"'
                    + ' data-voicesv3-value="' + attr(action.status) + '">'
                    + escape(action.label) + '</button>';
            }).join('')
            + '</div>';
    }

    function versionSelect(state, name) {
        var versions = selectors.selectVersions(state, name);
        var html = optionPlaceholder('Choose a saved version');
        html += versions.options.map(function (entry) {
            var label = entry.id + (entry.ageGroup ? ' · ' + entry.ageGroup : '');
            return markup.option(entry.id, label, entry.active);
        }).join('');
        return '<div class="input-group input-group-sm mt-2">'
            + '<select class="form-select voice-version-select" data-voicesv3-action="version-select"'
            + ' data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Voice version for ' + name) + '">' + html + '</select>'
            + '<button class="btn btn-outline-secondary" type="button" data-voicesv3-action="version-add"'
            + ' data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Add voice version for ' + name) + '">Version</button>'
            + '</div>'
            + '<div class="form-text">' + escape(labels.VERSION_HELP) + '</div>';
    }

    function optionPlaceholder(text_) {
        return '<option value="" disabled>' + escape(text_) + '</option>';
    }

    /* The original hides this entry point entirely when a character has one or
     * fewer settled states, so it appears only when there is a change to review. */
    /* `key` is the roster row key, so a state row's panel is its own container.
     * The Voice changes panel stays available on every row as the documented
     * fallback; state rows just get one scoped to themselves. */
    function voiceChangesButton(key, traits, label) {
        var stateCount = selectors.selectTraitStateCount(traits);
        if (stateCount <= 1) { return ''; }
        var changes = stateCount - 1;
        var title = label || 'Voice changes';
        return '<div class="voice-states mt-1">'
            + '<button class="btn btn-sm btn-outline-primary" type="button" data-voicesv3-action="states-open"'
            + ' data-voicesv3-name="' + attr(key) + '"'
            + ' aria-label="' + attr('Load voice changes for ' + (label || key)) + '">'
            + '<i class="fas fa-user-clock me-1"></i>' + escape(title) + ' (' + changes + ' change' + (changes === 1 ? '' : 's') + ')</button>'
            + '<div class="form-text">Review which voice is used before and after each change.</div>'
            + '<div class="voice-state-rows" data-voicesv3-state-panel="' + attr(key) + '"></div>'
            + '</div>';
    }

    function candidatesBlock(state, name) {
        var candidates = selectors.selectCandidates(state, name);
        var rows = markup.candidateRows(candidates.map(function (candidate) {
            return Object.assign({}, candidate, { name: name });
        }));
        return '<button class="btn btn-sm btn-outline-secondary mt-1" type="button"'
            + ' data-voicesv3-action="suggest-more" data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Generate more voice candidates for ' + name) + '">'
            + '<i class="fas fa-wand-magic-sparkles me-1"></i>Generate more candidates</button>'
            + '<div class="saved-voice-candidates" data-voicesv3-candidates="' + attr(name) + '">' + rows + '</div>'
            + '<div data-voicesv3-suggestions="' + attr(name) + '"></div>';
    }


    function readySwitch(name, index, ready) {
        return '<div class="form-check form-switch small">'
            + '<input class="form-check-input voice-ready" type="checkbox" id="voicesv3-ready-' + index + '"'
            + ' data-voicesv3-action="ready-toggle" data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Ready for audio generation for ' + name) + '"'
            + (ready ? ' checked' : '') + '>'
            + '<label class="form-check-label" for="voicesv3-ready-' + index + '">Ready</label>'
            + '</div>';
    }

    function aliasSelect(state, name, aliasOf) {
        var options = selectors.selectAliasOptions(state, name);
        return '<div class="form-text small text-muted mt-1">Alias of:</div>'
            + '<select class="form-select form-select-sm alias-select mt-1" data-voicesv3-field="alias_of"'
            + ' data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Alias target for ' + name) + '">'
            + markup.option('', '-- None --', !aliasOf)
            + options.map(function (candidate) { return markup.option(candidate, candidate, candidate === aliasOf); }).join('')
            + '</select>';
    }

    /* ---- type radios ---- */

    function typeRadios(name, index, selected) {
        return labels.VOICE_TYPES.map(function (type) {
            var isChecked = type === selected;
            return '<div class="form-check form-check-inline">'
                + '<input class="form-check-input voice-type" type="radio" name="voicesv3-type-' + index + '"'
                + ' value="' + attr(type) + '" id="voicesv3-type-' + index + '-' + attr(type) + '"'
                + ' data-voicesv3-action="type-set" data-voicesv3-name="' + attr(name) + '"' 
                + ' aria-label="' + attr((labels.VOICE_TYPE_ARIA[type] || type) + ' for ' + name) + '"'
                + (isChecked ? ' checked' : '') + '>'
                + '<label class="form-check-label" for="voicesv3-type-' + index + '-' + attr(type) + '">'
                + escape(labels.voiceTypeLabel(type)) + '</label>'
                + '</div>';
        }).join('');
    }

    function shown(type, selected) { return type === selected ? 'block' : 'none'; }

    /* ---- the six option blocks ---- */

    function customBlock(state, name, type, working, reference) {
        var options = selectors.selectCustomVoiceOptions(state, name);
        return '<div class="custom-opts" style="display: ' + shown('custom', type) + '">'
            + '<div class="row g-2">'
            + '<div class="col-md-6">'
            + '<select class="form-select voice-select" data-voicesv3-field="voice" data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Custom voice for ' + name) + '">'
            + markup.customVoiceOptions(options, working.voice) + '</select>'
            + '</div>'
            + '<div class="col-md-6">'
            + '<input type="text" class="form-control character-style" data-voicesv3-field="character_style"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Custom voice style for ' + name) + '"'
            + ' placeholder="Character style (e.g. refined aristocratic tone, heavy Scottish accent)"'
            + ' value="' + attr(working.character_style || '') + '">'
            + markup.styleTimeline(selectors.selectStylePoints(state, name), name)
            + '</div>'
            + '</div>'
            + '</div>';
    }

    function builtinLoraBlock(state, name, type, working) {
        var style = type === 'builtin_lora' ? (working.character_style || '') : '';
        return '<div class="builtin-lora-opts" style="display: ' + shown('builtin_lora', type) + '">'
            + '<div class="row g-2">'
            + '<div class="col-md-6">'
            + '<select class="form-select builtin-lora-select" data-voicesv3-field="adapter_id"'
            + ' data-voicesv3-type="builtin_lora" data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Built-in LoRA voice for ' + name) + '">'
            + markup.builtinLoraGroups(state, working.adapter_id) + '</select>'
            + '</div>'
            + '<div class="col-md-6">'
            + '<input type="text" class="form-control builtin-lora-style" data-voicesv3-field="character_style"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Built-in LoRA voice style for ' + name) + '"'
            + ' placeholder="Character style (e.g. refined aristocratic tone, heavy Scottish accent)"'
            + ' value="' + attr(style) + '">'
            + '</div>'
            + '</div>'
            + '<small class="text-muted mt-1 d-block">' + escape(labels.BUILTIN_HELP) + '</small>'
            + '</div>';
    }

    function cloneBlock(state, name, type, working, reference) {
        var refAudio = working.ref_audio || '';
        return '<div class="clone-opts" style="display: ' + shown('clone', type) + '">'
            + '<div class="row g-2 mb-2 align-items-center">'
            + '<div class="col">'
            + '<select class="form-select designed-voice-select" data-voicesv3-action="reference-select"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Reference voice for ' + name) + '">'
            + markup.referenceVoiceOptions(state, reference, refAudio) + '</select>'
            + '</div>'
            + '<div class="col-auto">'
            + '<button class="btn btn-sm btn-outline-primary" type="button" data-voicesv3-action="clone-upload"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Upload reference audio for ' + name) + '" title="Upload audio file">'
            + '<i class="fas fa-upload"></i> Upload</button>'
            + '<input type="file" class="clone-voice-file-input" data-voicesv3-action="clone-file"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Upload reference audio for ' + name) + '"'
            + ' accept=".wav,.mp3,.flac,.ogg" style="display:none">'
            + '</div>'
            + '</div>'
            + '<input type="text" class="form-control ref-text mb-2" data-voicesv3-field="ref_text"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Reference transcript for ' + name) + '"'
            + ' placeholder="Reference Text" value="' + attr(working.ref_text || '') + '">'
            + '<div class="input-group">'
            + '<input type="text" class="form-control ref-audio" data-voicesv3-field="ref_audio"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Reference audio path for ' + name) + '"'
            + ' placeholder="Path to audio file" value="' + attr(refAudio) + '"'
            + (reference ? ' readonly' : '') + '>'
            + '<button class="btn btn-sm btn-outline-secondary clone-play-btn" type="button"'
            + ' data-voicesv3-action="clone-play" data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Play reference audio for ' + name) + '" title="Play reference audio"'
            + ' style="display:' + (refAudio ? 'inline-block' : 'none') + '"><i class="fas fa-play"></i></button>'
            + '<button class="btn btn-sm btn-outline-danger clone-delete-btn" type="button"'
            + ' data-voicesv3-action="clone-delete" data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Delete uploaded reference voice for ' + name) + '" title="Delete uploaded voice"'
            + ' style="display:' + (reference && reference.type === 'clone' ? 'inline-block' : 'none') + '">'
            + '<i class="fas fa-trash"></i></button>'
            + '</div>'
            + '</div>';
    }

    function loraBlock(state, name, type, working) {
        var style = type === 'lora' ? (working.character_style || '') : '';
        return '<div class="lora-opts" style="display: ' + shown('lora', type) + '">'
            + '<div class="row g-2">'
            + '<div class="col-md-6">'
            + '<select class="form-select lora-adapter-select" data-voicesv3-field="adapter_id"'
            + ' data-voicesv3-type="lora" data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Trained LoRA voice for ' + name) + '">'
            + markup.userLoraOptions(state, working.adapter_id) + '</select>'
            + '</div>'
            + '<div class="col-md-6">'
            + '<input type="text" class="form-control lora-character-style" data-voicesv3-field="character_style"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('LoRA voice style for ' + name) + '"'
            + ' placeholder="Character style (e.g. refined aristocratic tone, heavy Scottish accent)"'
            + ' value="' + attr(style) + '">'
            + '</div>'
            + '</div>'
            + '</div>';
    }

    function designBlock(state, name, type, working) {
        return '<div class="design-opts" style="display: ' + shown('design', type) + '">'
            + '<input type="text" class="form-control design-description mb-1" data-voicesv3-field="description"'
            + ' data-voicesv3-name="' + attr(name) + '"' 
            + ' aria-label="' + attr('Base voice description for ' + name) + '"'
            + ' placeholder="Base voice description (e.g. Young strong soldier)"'
            + ' value="' + attr(working.description || '') + '">'
            + '<span class="text-muted small">' + escape(labels.DESIGN_HELP) + '</span>'
            + '<div class="mt-2">'
            + '<button type="button" class="btn btn-sm btn-outline-primary" data-voicesv3-action="design-open"'
            + ' data-voicesv3-name="' + attr(name) + '"'
            + ' aria-label="' + attr('Re-design voice for ' + name) + '">'
            + '<i class="fas fa-wand-magic-sparkles me-1"></i>Re-design Voice</button>'
            + '</div>'
            + '</div>';
    }

    function ensembleBlock(state, name, type, working) {
        var suggestions = selectors.selectEnsembleSuggestions(state, name);
        /* Read from the edit target, not `workingOf`, so a state ensemble can
         * differ from the character's own ensemble. */
        var members = working.members || [];
        return '<div class="ensemble-opts" style="display: ' + shown('ensemble', type) + '">'
            + '<div class="ensemble-members small">'
            + markup.ensembleMembers(selectors.arrayOf(state.roster.names), members, suggestions)
            + '</div>'
            + '<span class="text-muted small">' + escape(labels.ENSEMBLE_HELP) + '</span>'
            + '</div>';
    }

    /* ---- the card ---- */

    function card(state, row, index) {
        /* `row.key` is the store/DOM identity ("MARO#adult"); `row.name` is what
         * the card shows and what the line count and trait badge look up. Every
         * control is bound to the KEY so the three MARO rows stay distinct. */
        var key = row.key;
        var name = row.name;
        var stored = row.config || {};
        var working = selectors.workingOf(state, key);
        var type = text(working.type) || text(stored.type) || 'custom';
        var reference = selectors.selectLibraryReference(state, working.ref_audio || stored.ref_audio || '');
        var ready = !!working.ready;

        return '<div class="card voice-card mb-3' + (ready ? ' border-success' : '') + '"'
            + ' data-voice="' + attr(key) + '"'
            + ' data-speaker="' + attr(row.speaker) + '"'
            + ' data-ready="' + (ready ? '1' : '0') + '">'
            + '<div class="card-body"><div class="row">'

            + '<div class="col-md-3">'
            + '<h5 class="card-title">' + escape(name)
            + aliasBadge(name, working.alias_of)
            + lineCountBadge(row.lineCount)
            + markup.traitBadge(row.traits)
            + (row.isState ? stateBadge(row) : '')
            + '</h5>'

            /* Regenerate persona passes the age band when this is a state row, so
             * generate_personas.py stores the result under versions[age_group]
             * instead of overwriting the character's own persona. */
            + '<button class="btn btn-sm btn-outline-primary mt-1" type="button" data-voicesv3-action="persona-regenerate"'
            + ' data-voicesv3-name="' + attr(key) + '"'
            + (row.ageGroup ? ' data-voicesv3-age="' + attr(row.ageGroup) + '"' : '')
            + ' aria-label="' + attr((row.isState ? 'Regenerate persona for ' + name + ' in the '
                + row.ageGroup.replace(/_/g, ' ') + ' state' : 'Regenerate persona for ' + name)) + '">'
            + '<i class="fas fa-rotate me-1"></i>Regenerate persona</button>'
            + reviewStatusLine(stored)
            + personaAuditLine(name, stored)
            + approvalButtons(key)
            /* The version picker chooses the CHARACTER's active version, which is
             * the wrong scope on a state row: a state row's own voice is already
             * a version, and promoting another one would change the character, not
             * the state. So it is plain rows only. */
            + (row.isState ? '' : versionSelect(state, key))
            + voiceChangesButton(key, row.traits,
                    row.isState ? 'Voice changes (character)' : null)
            + candidatesBlock(state, key)
            + readySwitch(key, index, ready)
            + aliasSelect(state, key, working.alias_of)
            + '</div>'

            + '<div class="col-md-9">'
            + '<div class="mb-2">' + typeRadios(key, index, type) + '</div>'
            + customBlock(state, key, type, working, reference)
            + builtinLoraBlock(state, key, type, working)
            + cloneBlock(state, key, type, working, reference)
            + loraBlock(state, key, type, working)
            + designBlock(state, key, type, working)
            + ensembleBlock(state, key, type, working)
            + '</div>'

            + '</div></div></div>';
    }

    /* Marks a card as one settled state of a character, and says whether that
     * state has a voice yet. The title stays the character's own name, so nothing
     * that matches on the visible name changes. */
    function stateBadge(row) {
        var label = 'state';
        var css = 'vv3-state-badge';
        if (row.hasVersion) { label = 'voice set'; css += ' is-set'; }
        return '<span class="' + css + '" title="This card is one settled state of '
            + escape(row.name) + '. Its voice is saved under versions.'
            + escape(row.ageGroup) + '.">' + escape(label) + '</span>';
    }

    namespace.cardPanel = {
        card: card,
        typeRadios: typeRadios,
        approvalButtons: approvalButtons,
        voiceChangesButton: voiceChangesButton
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));
