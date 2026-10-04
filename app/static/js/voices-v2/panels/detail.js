/* Voices V2 — the read-only character detail panel.
 *
 * Six sections, in the order a user asks for them: what this character is, what
 * voice they currently have, what the script says they are like, what voices are
 * saved for them, what persona exists, and why they might be in an odd state.
 *
 * Every section states absence rather than hiding it. A character with no
 * versions says so; a book with no traits explains that the active script was
 * generated without them instead of leaving the row blank; an orphan says
 * plainly that its configuration outlived its script lines. Nothing here
 * suggests a fix, because repairing any of it is a later phase.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var labels = namespace.labels;
    var states = namespace.states;
    var selectors = namespace.selectors;

    function detailRegion() {
        return core.region('detail');
    }

    function row(label, value, modifier) {
        return '<div class="vv2-field">'
            + '<dt class="vv2-field-label">' + core.escape(label) + '</dt>'
            + '<dd class="vv2-field-value' + (modifier ? ' ' + core.escape(modifier) : '') + '">'
            + value + '</dd></div>';
    }

    function value(text, modifier) {
        return '<span' + (modifier ? ' class="' + core.escape(modifier) + '"' : '') + '>'
            + core.escape(text) + '</span>';
    }

    function section(title, body, id) {
        return '<section class="vv2-detail-section"'
            + (id ? ' data-voicesv2-section="' + core.escape(id) + '"' : '') + '>'
            + '<h5 class="vv2-detail-title">' + core.escape(title) + '</h5>'
            + '<dl class="vv2-fields mb-0">' + body + '</dl></section>';
    }

    function list(items) {
        return '<ul class="vv2-plain-list mb-0">' + items.join('') + '</ul>';
    }

    function overviewSection(character) {
        var fields = [
            row('Name', value(character.name, 'vv2-strong')),
            row('Identity key', value(character.identityKey || labels.NOT_AVAILABLE,
                'vv2-mono')),
            row('Line count', value(labels.lineCountLabel(character.lineCount))),
            row('Priority', value(labels.priorityLabel(character.priority))),
            row('In active script', value(character.presentInScript ? 'Yes' : 'No',
                character.presentInScript ? null : 'vv2-warn'))
        ];
        var labels_ = character.aliases.concat(
            character.knownAs.filter(function (label) {
                return label !== character.name && character.aliases.indexOf(label) < 0;
            }));
        fields.push(row(labels_.length ? 'Aliases and known names' : 'Aliases',
            labels_.length ? list(labels_.map(function (label) {
                return '<li>' + core.escape(label) + '</li>';
            })) : value('None registered', 'vv2-muted')));
        if (character.possibleDuplicateOf.length) {
            fields.push(row('Possible duplicate of',
                list(character.possibleDuplicateOf.map(function (label) {
                    return '<li>' + core.escape(label) + '</li>';
                })), 'vv2-warn'));
        }
        return section('Overview', fields.join(''), 'overview');
    }

    function voiceSection(character) {
        var voice = character.voice;
        var fields = [
            row('Category', value(labels.voiceCategoryLabel(voice.category))),
            row('Voice', value(voice.label, voice.assigned ? 'vv2-strong' : 'vv2-warn')),
            row('Assignment', value(labels.assignedLabel(voice.assigned))),
            row('Readiness', value(labels.readyLabel(character.ready))),
            row('Stored status', character.voiceStatus
                ? value(labels.titleise(character.voiceStatus))
                : value('Not recorded', 'vv2-muted')),
            row('Persona status', character.personaStatus
                ? value(labels.titleise(character.personaStatus))
                : value('Not recorded', 'vv2-muted'))
        ];
        if (voice.adapterId) {
            fields.push(row('Adapter', value(voice.adapterId, 'vv2-mono'), voice.adapterAvailable
                ? null : 'vv2-warn'));
            fields.push(row('Adapter on disk', voice.adapterAvailable
                ? value('Found')
                : value('Not found', 'vv2-warn')));
        }
        if (voice.hasRefAudio) {
            fields.push(row('Reference recording', voice.refAudioPresent
                ? value('Present')
                : value('Missing from disk', 'vv2-warn')));
        }
        if (voice.aliasOf) {
            fields.push(row('Defers to', value(voice.aliasOf), 'vv2-warn'));
        }
        if (voice.ensembleMembers) {
            fields.push(row('Ensemble members', value(String(voice.ensembleMembers))));
        }
        return section('Current voice', fields.join(''), 'voice');
    }

    /* Traits are reported per character AND per state, because `speaker_traits`
     * exists so a character can change across a time skip. A single value would
     * be the thing that module was written to avoid. */
    function traitsSection(character, meta) {
        if (!meta.traitsAvailable) {
            return section('Traits', row('Gender', value(labels.NOT_AVAILABLE, 'vv2-muted'))
                + row('Age', value(labels.NOT_AVAILABLE, 'vv2-muted'))
                + '<p class="small text-muted vv2-note mb-0 mt-2">'
                + 'The active script was generated without per-line speaker traits, so this book '
                + 'records no gender or age for any character. Regenerate the script with '
                + 'per-line speaker traits to populate this.</p>', 'traits');
        }
        if (!character.traits) {
            return section('Traits', row('Gender', value('Not recorded', 'vv2-muted'))
                + row('Age', value('Not recorded', 'vv2-muted'))
                + '<p class="small text-muted vv2-note mb-0 mt-2">'
                + 'This book has per-line speaker traits, but none were recorded for this '
                + 'character.</p>', 'traits');
        }
        var traits = character.traits;
        var fields = [
            row('Gender', value(labels.genderLabel(traits.gender))),
            row('Age group', value(labels.ageGroupLabel(traits.ageGroup))),
            row('Ageless', value(traits.ageless ? 'Yes' : 'No')),
            row('Traited lines', value(String(traits.lines))),
            row('Current state', value(labels.genderLabel(traits.current.gender)
                + ' \u00b7 ' + labels.ageGroupLabel(traits.current.ageGroup)))
        ];
        if (character.states.length) {
            fields.push(row('States in this book', list(character.states.map(function (item) {
                var from = (item.fromEntry === null) ? 'start' : 'line ' + item.fromEntry;
                return '<li>' + core.escape(from) + ' \u2014 ' + core.escape(
                    labels.genderLabel(item.gender) + ' \u00b7 ' + labels.ageGroupLabel(item.ageGroup))
                    + '</li>';
            }))));
        }
        return section('Traits', fields.join(''), 'traits');
    }

    function versionsSection(character) {
        var body = row('Saved versions', character.versions.length
            ? String(character.versions.length)
            : value('None saved', 'vv2-muted'));
        if (character.activeVersion) {
            body += row('Active version', value(character.activeVersion, 'vv2-mono'));
        }
        if (character.versions.length) {
            body += row('Versions', list(character.versions.map(function (version) {
                var active = version.versionId === character.activeVersion;
                return '<li' + (active ? ' class="vv2-strong"' : '') + '>'
                    + core.escape(version.versionId)
                    + ' \u2014 ' + core.escape(labels.voiceCategoryLabel(version.category))
                    + (version.ageGroup ? ' \u00b7 ' + core.escape(labels.ageGroupLabel(version.ageGroup))
                        : '')
                    + (active ? ' \u00b7 active' : '')
                    + '</li>';
            })));
        }
        if (character.versionTimeline.length) {
            body += row('Version timeline', list(character.versionTimeline.map(function (point) {
                var from = (point.fromIndex === null) ? 'start' : 'chunk ' + point.fromIndex;
                return '<li>' + core.escape(from) + ' \u2192 '
                    + core.escape(point.versionId || labels.NOT_AVAILABLE) + '</li>';
            })));
        }
        if (character.candidateCount) {
            body += row('Candidates', value(String(character.candidateCount)));
        }
        return section('Versions', body, 'versions');
    }

    function personaSection(character) {
        var body = row('Persona status', character.personaStatus
            ? value(labels.titleise(character.personaStatus))
            : value('Not recorded', 'vv2-muted'));
        body += row('Description', character.voice.hasDescription
            ? value('Present')
            : value('None', 'vv2-muted'));
        body += row('Persona file', character.personaRef
            ? value(character.personaRef, 'vv2-mono') + ' '
              + (character.personaRefResolves
                  ? value('(found)', 'vv2-muted')
                  : value('(missing from disk)', 'vv2-warn'))
            : value('Not referenced', 'vv2-muted'));
        return section('Persona', body, 'persona');
    }

    function problemsSection(character) {
        if (!character.problems.length) {
            return section('Warnings', '<div class="vv2-field">'
                + '<dd class="vv2-field-value vv2-muted">No warnings for this character.</dd>'
                + '</div>', 'warnings');
        }
        var items = character.problems.map(function (code) {
            var text = labels.problemText(code);
            return '<li><strong>' + core.escape(text.title) + '</strong><br>'
                + '<span class="vv2-muted">' + core.escape(text.detail) + '</span></li>';
        });
        return section('Warnings', '<div class="vv2-field vv2-warn-field"><dd>'
            + list(items) + '</dd></div>', 'warnings');
    }

    /* An orphan is explained before anything else, because it is the one reason
     * a character is here at all. */
    function orphanNote(character) {
        if (character.presentInScript) { return ''; }
        return '<div class="alert alert-warning vv2-orphan-note" role="status">'
            + '<strong>This character is not in the active script.</strong> A voice configuration '
            + 'for "' + core.escape(character.name) + '" is stored, but no line in the current '
            + 'script has that speaker, so the Voices tab does not show it. Voices V2 lists it '
            + 'read-only and has not changed it.'
            + '</div>';
    }

    function render(nextState) {
        var container = detailRegion();
        if (!container) { return false; }
        var character = selectors.selectSelected(nextState);
        if (!character) {
            container.innerHTML = states.detailEmptyMarkup();
            return true;
        }
        container.innerHTML = orphanNote(character)
            + overviewSection(character)
            + voiceSection(character)
            + traitsSection(character, nextState.meta)
            + versionsSection(character)
            + personaSection(character)
            + problemsSection(character);
        return true;
    }

    namespace.detailPanel = {
        render: render,
        sections: ['overview', 'voice', 'traits', 'versions', 'persona', 'warnings']
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));