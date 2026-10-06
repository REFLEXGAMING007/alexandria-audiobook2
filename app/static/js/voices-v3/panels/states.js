/* Voices V3 — the per-character voice-change panel.
 *
 * A character whose settled age or gender changes across the book gets one voice
 * per state. The panel suggests a source per state; nothing changes audio until
 * Apply is pressed, and the toast says so explicitly afterwards because already
 * rendered lines keep their old voice.
 *
 * Ranking order for an unapplied state is deliberate and matches the original:
 * main voice, then the character's own matching versions, then library voices
 * nobody uses, then library voices other characters use, then offer to generate an
 * age version.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var escape = core.escape;

    function attr(value) { return escape(value); }

    function prettyAge(ageGroup) {
        return String(ageGroup || '').replace(/_/g, ' ');
    }

    function container(name) {
        var host = core.region('roster');
        if (!host) { return null; }
        var safe = String(name).replace(/"/g, '\\"');
        return host.querySelector('[data-voicesv3-state-panel="' + safe + '"]');
    }

    function appliedDefault(entry, applied, index) {
        var point = (applied || []).find(function (candidate) {
            return candidate.from_index === entry.from_index;
        });
        if (point) { return point.version_id ? 'version:' + point.version_id : 'main'; }
        var sources = entry.sources || {};
        if (index === 0) { return 'main'; }
        if ((sources.versions || []).length) { return 'version:' + sources.versions[0].version_id; }
        if ((sources.library_unused || []).length) { return 'library:' + sources.library_unused[0].adapter_id; }
        if ((sources.library_used || []).length) { return 'library:' + sources.library_used[0].adapter_id; }
        return 'main';
    }

    function libraryOption(candidate, selected, suffix) {
        var label = (candidate.name || candidate.adapter_id) + ' · ' + (candidate.gender || '')
            + ' · ' + prettyAge(candidate.age_group) + suffix;
        return markup.option('library:' + candidate.adapter_id, label, selected === ('library:' + candidate.adapter_id));
    }

    function row(state, entry, applied, index, speaker) {
        var sources = entry.sources || {};
        var selected = appliedDefault(entry, applied, index);
        var located = entry.from_index !== null && entry.from_index !== undefined;
        var where = located ? 'from line ' + (entry.from_index + 1) : 'line not found in the Editor yet';
        var age = prettyAge(entry.age_group);

        var options = [markup.option('main', 'Main voice', selected === 'main')];
        (sources.versions || []).forEach(function (version) {
            options.push(markup.option('version:' + version.version_id, 'Version: ' + version.version_id,
                selected === ('version:' + version.version_id)));
        });
        // An applied version stays selectable even when it no longer ranks as a
        // match, so a saved choice is never silently dropped from the control.
        if (selected.indexOf('version:') === 0 && !(sources.versions || []).some(function (version) {
            return 'version:' + version.version_id === selected;
        })) {
            options.push(markup.option(selected, 'Version: ' + selected.slice(8), true));
        }
        (sources.library_unused || []).forEach(function (candidate) {
            options.push(libraryOption(candidate, selected, ' · unused'));
        });
        (sources.library_used || []).forEach(function (candidate) {
            options.push(libraryOption(candidate, selected, ' · used by ' + ((candidate.used_by || []).join(', '))));
        });

        var generate = sources.offer_generate
            ? ' <button class="btn btn-sm btn-link p-0" type="button" data-voicesv3-action="version-generate-age"'
              + ' data-voicesv3-name="' + attr(speaker) + '" data-voicesv3-age="' + attr(entry.age_group) + '">'
              + 'Generate ' + escape(age) + ' version</button>'
            : '';

        var ariaLabel = 'Voice for ' + speaker + ', ' + entry.gender + ', ' + age + ', ' + where;

        return '<div class="voice-state-row small mt-1"'
            + ' data-from-index="' + (located ? Number(entry.from_index) : '') + '"'
            + ' data-age="' + attr(entry.age_group) + '">'
            + '<div>' + escape(entry.gender) + ' · ' + escape(age)
            + (entry.chapter ? ', ' + escape(entry.chapter) : '')
            + ' <span class="text-muted">(' + escape(where) + ')</span></div>'
            + '<select class="form-select form-select-sm voice-state-source"'
            + ' data-voicesv3-action="state-source"'
            + ' aria-label="' + attr(ariaLabel) + '"'
            + (located ? '' : ' disabled') + '>' + options.join('') + '</select>'
            + generate
            + '</div>';
    }

    function actions(speaker) {
        return '<div class="mt-1">'
            + '<button class="btn btn-sm btn-primary" type="button" data-voicesv3-action="states-apply"'
            + ' data-voicesv3-name="' + attr(speaker) + '"'
            + ' aria-label="' + attr('Apply voice changes for ' + speaker) + '">Apply</button> '
            + '<button class="btn btn-sm btn-outline-secondary" type="button" data-voicesv3-action="states-clear"'
            + ' data-voicesv3-name="' + attr(speaker) + '"'
            + ' aria-label="' + attr('Clear voice changes for ' + speaker) + '">Clear</button>'
            + '</div>';
    }

    function renderPanel(storeState, speaker) {
        var target = container(speaker);
        if (!target) { return; }
        var panel = selectors.selectStatePanel(storeState, speaker);

        if (panel.loading) {
            target.innerHTML = '<div class="small text-muted">Loading voice changes…</div>';
            return;
        }
        if (panel.error) {
            target.innerHTML = markup.alert('warning',
                escape(panel.error) + ' <button type="button" class="btn btn-sm btn-link"'
                + ' data-voicesv3-action="states-open" data-voicesv3-name="' + attr(speaker) + '">Retry</button>');
            return;
        }
        if (!panel.loaded) {
            // Closed by default. The card only renders the button when the trait
            // summary reports more than one settled state, so there is always
            // something to look at.
            target.innerHTML = '';
            return;
        }
        if (!panel.rows.length) {
            target.innerHTML = '<div class="small text-muted">No detected change in age or gender for this character.</div>';
            return;
        }

        var body = panel.rows.map(function (entry, index) {
            return row(panel, entry, panel.applied, index, speaker);
        }).join('');
        target.innerHTML = body + actions(speaker)
            + (panel.notice ? '<div class="small text-muted mt-1">' + escape(panel.notice) + '</div>' : '');
    }

    /* ---- actions ---- */

    async function open(storeState, speaker) {
        if (selectors.selectStatePanel(storeState, speaker).loading) { return; }
        namespace.state.dispatch({ type: 'states/set', name: speaker, loading: true, error: '' });
        try {
            var data = await namespace.api.fetchStateTimeline(speaker);
            namespace.state.dispatch({
                type: 'states/set',
                name: speaker,
                loading: false,
                loaded: true,
                rows: selectors.arrayOf(data && data.states),
                applied: selectors.arrayOf(data && data.applied),
                offerGenerate: true,
                error: ''
            });
        } catch (error) {
            namespace.state.dispatch({
                type: 'states/set',
                name: speaker,
                loading: false,
                loaded: false,
                error: 'Voice changes could not be loaded: ' + namespace.api.messageOf(error, '')
            });
        }
    }

    function currentSelections(name) {
        var target = container(name);
        if (!target) { return []; }
        return Array.prototype.slice.call(target.querySelectorAll('.voice-state-source')).map(function (select) {
            var row = select.closest('.voice-state-row');
            return {
                fromIndex: row && row.dataset.fromIndex !== '' ? Number(row.dataset.fromIndex) : null,
                ageGroup: row ? row.dataset.age : '',
                value: select.value,
                enabled: !select.disabled
            };
        });
    }

    async function apply(storeState, speaker) {
        var panel = selectors.selectStatePanel(storeState, speaker);
        var selections = currentSelections(speaker).filter(function (entry) {
            return entry.enabled && entry.fromIndex !== null;
        });
        if (!selections.length) {
            core.notify('No applicable voice changes to apply for ' + speaker + '.', 'warning');
            return false;
        }

        namespace.state.dispatch({ type: 'states/set', name: speaker, saving: true, error: '', notice: '' });
        try {
            var points = [];
            for (var index = 0; index < selections.length; index += 1) {
                var selection = selections[index];
                var versionId = 'main';
                if (selection.value.indexOf('library:') === 0) {
                    var adapterId = selection.value.slice('library:'.length);
                    versionId = (selection.ageGroup + '-' + adapterId).slice(0, 80);
                    await namespace.api.addVersion(speaker, {
                        version_id: versionId,
                        age_group: selection.ageGroup,
                        adapter_id: adapterId,
                        source: 'state_panel'
                    });
                } else if (selection.value.indexOf('version:') === 0) {
                    versionId = selection.value.slice('version:'.length);
                }
                points.push({ from_index: selection.fromIndex, version_id: versionId });
            }
            await namespace.api.saveVersionTimeline(speaker, points);
            namespace.state.dispatch({
                type: 'states/set',
                name: speaker,
                saving: false,
                notice: 'Applied. Lines already rendered keep the voice they had.'
            });
            core.notify('Voice changes applied for ' + speaker
                + '. Lines already rendered keep the voice they had.', 'success', 8000);
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            namespace.state.dispatch({
                type: 'states/set',
                name: speaker,
                saving: false,
                error: 'Could not apply the voice changes: ' + namespace.api.messageOf(error, '')
            });
            return false;
        }
    }

    async function clear(storeState, speaker) {
        var confirmed = await core.confirm(
            'Clear the voice changes for ' + speaker + '?',
            { title: 'Clear voice changes?', actionLabel: 'Clear changes', danger: true });
        if (!confirmed) { return false; }
        namespace.state.dispatch({ type: 'states/set', name: speaker, saving: true, error: '', notice: '' });
        try {
            await namespace.api.clearVersionTimeline(speaker);
            namespace.state.dispatch({ type: 'states/set', name: speaker, saving: false, notice: 'Cleared.' });
            core.notify('Voice changes cleared for ' + speaker + '.', 'success');
            await namespace.lifecycle.reloadVoices();
            return true;
        } catch (error) {
            namespace.state.dispatch({
                type: 'states/set',
                name: speaker,
                saving: false,
                error: 'Could not clear the voice changes: ' + namespace.api.messageOf(error, '')
            });
            return false;
        }
    }

    namespace.statesPanel = {
        mount: function () {},
        unbind: function () {},
        renderPanel: renderPanel,
        container: container,
        open: open,
        apply: apply,
        clear: clear,
        currentSelections: currentSelections,
        appliedDefault: appliedDefault
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));