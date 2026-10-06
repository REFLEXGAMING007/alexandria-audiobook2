/* Voices V3 — the Series Cast panel.
 *
 * Reuse a character's voice across books in a series so a recurring character
 * sounds the same. The narrator is shared across the whole series unless a cast
 * saves its own, which is why the save path carries an explicit member list.
 *
 * Cast application goes through a match step rather than applying blindly: the
 * backend proposes a mapping between cast members and the current book's
 * characters, the user sees the proposed pairs plus anything ambiguous, and only
 * then is it applied. Applying also refreshes the suggestion and favourite data
 * that live in the same file.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var markup = namespace.markup;
    var selectors = namespace.selectors;
    var escape = core.escape;

    var bound = false;

    function attr(value) { return escape(value); }

    function control(name) {
        var region = core.region('cast');
        return region ? region.querySelector('[data-voicesv3-control="' + name + '"]') : null;
    }

    /* ---- rendering ---- */

    function memberRow(member) {
        var key = member.key || member.name || '';
        var knownAs = selectors.arrayOf(member.known_as);
        return '<tr>'
            + '<td>' + escape(key) + '</td>'
            + '<td>' + escape(member.name || '') + '</td>'
            + '<td>' + escape(member.line_count != null ? member.line_count : '') + '</td>'
            + '<td>' + (member.generic ? '<span class="badge bg-secondary">generic</span>' : '') + '</td>'
            + '<td class="small text-muted">' + escape(knownAs.join(', ')) + '</td>'
            + '<td class="text-end"><button class="btn btn-sm btn-outline-danger py-0" type="button"'
            + ' data-voicesv3-action="cast-member-delete"'
            + ' data-voicesv3-cast="' + attr(namespace.state.getState().cast.selected) + '"'
            + ' data-voicesv3-key="' + attr(key) + '"'
            + ' aria-label="Remove ' + attr(key) + ' from this cast">Remove</button></td>'
            + '</tr>';
    }

    function renderMembers(state) {
        var host = control('members');
        if (!host) { return; }
        var castName = state.cast.selected;
        var members = selectors.selectCastMembers(state);
        if (!castName) {
            host.innerHTML = '<div class="text-muted small">No cast selected. Create one to start reusing voices across books.</div>';
            return;
        }
        if (!members.length) {
            host.innerHTML = '<div class="text-muted small">This cast has no members yet. Use Save to cast to add the current voices.</div>';
            return;
        }
        host.innerHTML = '<div class="table-responsive"><table class="table table-sm align-middle">'
            + '<thead><tr><th>Key</th><th>Name</th><th>Lines</th><th></th><th>Known as</th><th></th></tr></thead>'
            + '<tbody>' + members.map(memberRow).join('') + '</tbody></table></div>';
    }

    function renderBulk(state) {
        var host = control('bulk');
        if (!host) { return; }
        var bulk = state.cast.bulk;
        if (!bulk.open) { host.innerHTML = ''; return; }

        var rows = bulk.scripts.map(function (script) {
            var checked = !!bulk.selection[script];
            return '<div class="form-check">'
                + '<input class="form-check-input" type="checkbox" value="' + attr(script) + '"'
                + ' data-voicesv3-action="cast-bulk-select"'
                + (checked ? ' checked' : '') + '>'
                + '<label class="form-check-label">' + escape(script) + '</label>'
                + '</div>';
        }).join('') || '<div class="text-muted small">No other books are available.</div>';

        var actions = Object.keys(bulk.selection).filter(function (key) { return bulk.selection[key]; }).length
            ? '<button class="btn btn-sm btn-success mt-2" type="button" data-voicesv3-action="cast-bulk-apply">'
              + 'Apply to selected books</button>'
            : '';
        host.innerHTML = '<div class="border rounded p-2 mt-2">'
            + '<div class="small fw-bold mb-1">Apply to multiple books</div>'
            + rows + actions
            + (bulk.status ? '<div class="small text-muted mt-1">' + escape(bulk.status) + '</div>' : '')
            + '</div>';
    }

    function sync(state) {
        var castSelect = control('select');
        var names = selectors.selectCasts(state).map(function (cast) { return cast.name; });
        var signature = names.join('|') + '#' + state.cast.selected;
        if (castSelect && castSelect.dataset.signature !== signature) {
            castSelect.innerHTML = names.length
                ? names.map(function (name) { return markup.option(name, name, name === state.cast.selected); }).join('')
                : markup.option('', '(no casts yet)', true);
            castSelect.dataset.signature = signature;
        }

        var hasCast = !!state.cast.selected;
        ['save', 'apply', 'apply-bulk', 'delete'].forEach(function (name) {
            var button = control(name);
            if (button) { button.disabled = !hasCast || !!state.cast.busy; }
        });
        var create = control('create');
        if (create) { create.disabled = !!state.cast.busy; }

        var status = control('status');
        if (status) { status.textContent = state.cast.status || ''; }

        renderMembers(state);
        renderBulk(state);
    }

    /* ---- actions ---- */

    async function loadLibrary(state) {
        var library = await namespace.api.fetchVoiceLibrary();
        var casts = selectors.arrayOf(library && library.casts);
        var names = casts.map(function (cast) { return cast.name; });
        var selected = state.cast.selected;
        if (names.indexOf(selected) < 0) {
            selected = names[0] || '';
        }
        namespace.state.dispatch({
            type: 'cast/patch',
            library: {
                casts: casts,
                shared: selectors.arrayOf(library && library.shared),
                current_characters: selectors.arrayOf(library && library.current_characters)
            },
            selected: selected
        });
        return true;
    }

    async function create(state) {
        var name = window.prompt('Name for the new cast:', state.meta.bookId || 'My Cast');
        if (!name || !String(name).trim()) { return false; }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Creating cast…' });
        try {
            await namespace.api.createCast(String(name).trim());
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: 'Cast created.' });
            await loadLibrary(namespace.state.getState());
            return true;
        } catch (error) {
            if (namespace.api.isConflict(error)) {
                // Already exists: select it rather than reporting a failure.
                namespace.state.dispatch({ type: 'cast/patch', busy: false, selected: String(name).trim(), status: '' });
                await loadLibrary(namespace.state.getState());
                return true;
            }
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not create the cast', error, 'Try a different name, then reload Voices.');
            return false;
        }
    }

    async function remove(state) {
        var name = state.cast.selected;
        if (!name) { return false; }
        var confirmed = await core.confirm('Delete the cast "' + name + '"?', {
            title: 'Delete cast?', actionLabel: 'Delete cast', danger: true });
        if (!confirmed) { return false; }
        try {
            await namespace.api.deleteCast(name);
            namespace.state.dispatch({ type: 'cast/patch', selected: '', status: 'Cast deleted.' });
            namespace.suggestionsPanel.dismiss();
            await loadLibrary(namespace.state.getState());
            return true;
        } catch (error) {
            core.notifyFailure('Could not delete the cast', error, 'Reload Voices and check the cast list before trying again.');
            return false;
        }
    }

    async function removeMember(state, castName, key) {
        var confirmed = await core.confirm('Remove "' + key + '" from the cast "' + castName + '"?', {
            title: 'Remove cast member?', actionLabel: 'Remove', danger: true });
        if (!confirmed) { return false; }
        try {
            await namespace.api.deleteCastMember(castName, key);
            namespace.state.dispatch({ type: 'cast/patch', status: 'Cast member removed.' });
            await loadLibrary(namespace.state.getState());
            return true;
        } catch (error) {
            core.notifyFailure('Could not remove the cast member', error, 'Reload Voices and check the cast list.');
            return false;
        }
    }

    /* Save the current book's configured voices into the selected cast. */
    async function save(state) {
        var name = state.cast.selected;
        if (!name) { return false; }
        var rows = selectors.selectRosterRows(state);
        var configured = rows.filter(function (row) {
            var config = row.config || {};
            return config.type && config.type !== 'custom' ? true : !!(config.voice || config.adapter_id || config.description);
        }).map(function (row) { return row.name; });
        if (!configured.length) {
            core.notify('There are no configured voices to save to the cast yet.', 'warning');
            return false;
        }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Saving voices to the cast…' });
        try {
            var result = await namespace.api.saveCast({ cast: name, characters: configured, cast_specific: [] });
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: 'Saved ' + configured.length + ' voices to "' + name + '".' });
            await loadLibrary(namespace.state.getState());
            return !!result;
        } catch (error) {
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not save the voices to the cast', error,
                'Reload Voices and check the cast contents before trying again.');
            return false;
        }
    }

    /* Propose a mapping rather than applying blindly, so an ambiguous name is a
     * decision the user makes instead of a silent overwrite. */
    async function openApply(state) {
        var name = state.cast.selected;
        if (!name) { return false; }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Matching this book against the cast…' });
        try {
            var result = await namespace.api.matchCast({ cast: name });
            namespace.state.dispatch({
                type: 'cast/patch',
                busy: false,
                panel: {
                    cast: name,
                    mapping: selectors.arrayOf(result && (result.mapping || result.matches)),
                    warnings: selectors.arrayOf(result && result.warnings)
                },
                status: ''
            });
            renderApplyPanel(namespace.state.getState());
            return true;
        } catch (error) {
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not match the cast to this book', error,
                'Reload Voices and check the character names before trying again.');
            return false;
        }
    }

    function renderApplyPanel(state) {
        var host = control('apply-panel');
        if (!host) { return; }
        var panel = state.cast.panel;
        if (!panel) { host.innerHTML = ''; return; }

        var rows = panel.mapping.map(function (pair, index) {
            var memberKey = pair.member_key || pair.key || '';
            var character = pair.character || pair.name || '';
            return '<tr>'
                + '<td>' + escape(memberKey) + '</td>'
                + '<td><select class="form-select form-select-sm" data-voicesv3-action="cast-map-character"'
                + ' data-voicesv3-index="' + index + '">'
                + markup.option('', '(skip)', !character)
                + selectors.selectRosterRows(state).map(function (row) {
                    return markup.option(row.name, row.name, row.name === character);
                }).join('')
                + '</select></td>'
                + '<td class="small text-muted">'
                + (pair.confidence != null ? escape(pair.confidence) : '')
                + (pair.ambiguous ? ' <span class="badge bg-warning text-dark">ambiguous</span>' : '')
                + (pair.reason ? ' ' + escape(pair.reason) : '')
                + '</td>'
                + '</tr>';
        }).join('');

        var warnings = panel.warnings.length
            ? markup.alert('warning', '<strong>Review before applying</strong><ul>'
                + panel.warnings.map(function (warning) { return '<li>' + escape(warning) + '</li>'; }).join('') + '</ul>')
            : '';

        host.innerHTML = warnings
            + '<div class="table-responsive"><table class="table table-sm align-middle">'
            + '<thead><tr><th>Cast member</th><th>Book character</th><th>Notes</th></tr></thead>'
            + '<tbody>' + rows + '</tbody></table></div>'
            + '<div class="d-flex gap-2 mt-2">'
            + '<button class="btn btn-sm btn-success" type="button" data-voicesv3-action="cast-apply-confirm">Apply cast</button>'
            + '<button class="btn btn-sm btn-outline-secondary" type="button" data-voicesv3-action="cast-apply-cancel">Cancel</button>'
            + '</div>';
    }

    function collectMapping() {
        var panel = namespace.state.getState().cast.panel;
        if (!panel) { return []; }
        var mapping = [];
        panel.mapping.forEach(function (pair, index) {
            var select = core.region('cast').querySelector('[data-voicesv3-action="cast-map-character"][data-voicesv3-index="' + index + '"]');
            var character = select ? select.value : (pair.character || pair.name || '');
            if (!character) { return; }
            mapping.push({ member_key: pair.member_key || pair.key || '', character: character });
        });
        return mapping;
    }

    async function apply(state) {
        var panel = state.cast.panel;
        if (!panel) { return false; }
        var mapping = collectMapping();
        if (!mapping.length) {
            core.notify('Choose at least one book character before applying the cast.', 'warning');
            return false;
        }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Applying the cast…' });
        try {
            var result = await namespace.api.applyCast({ cast: panel.cast, mapping: mapping });
            namespace.state.dispatch({ type: 'cast/patch', busy: false, panel: null, status: 'Cast applied.' });
            core.notify('Cast applied. Re-render to hear the change; already rendered lines keep their voice.',
                'success', 8000);
            await namespace.lifecycle.reloadVoices();
            return !!result;
        } catch (error) {
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not apply the cast', error,
                'Reload Voices and check which characters were changed before trying again.');
            return false;
        }
    }

    function cancelApply() {
        namespace.state.dispatch({ type: 'cast/patch', panel: null });
    }

    async function openBulk(state) {
        var name = state.cast.selected;
        if (!name) { return false; }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Loading the book list…' });
        try {
            var result = await namespace.api.matchCastBulk({ cast: name });
            var scripts = selectors.arrayOf(result && (result.scripts || result.books));
            namespace.state.dispatch({
                type: 'cast/patch',
                busy: false,
                status: ''
            });
            namespace.state.dispatch({
                type: 'cast/bulk/patch',
                open: true,
                scripts: scripts,
                selection: {},
                matches: selectors.arrayOf(result && (result.mapping || result.matches)),
                status: ''
            });
            return true;
        } catch (error) {
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not load the book list', error,
                'Reload Voices and try again, or apply the cast to the current book only.');
            return false;
        }
    }

    async function applyBulk(state) {
        var selected = Object.keys(state.cast.bulk.selection).filter(function (key) {
            return state.cast.bulk.selection[key];
        });
        if (!selected.length) {
            core.notify('Select at least one book.', 'warning');
            return false;
        }
        var confirmed = await core.confirm(
            'Apply the cast "' + state.cast.selected + '" to ' + selected.length + ' book(s)?',
            { title: 'Apply cast to other books?', actionLabel: 'Apply', danger: false });
        if (!confirmed) { return false; }
        namespace.state.dispatch({ type: 'cast/patch', busy: true, status: 'Applying the cast to the selected books…' });
        try {
            await namespace.api.applyCastBulk({ cast: state.cast.selected, scripts: selected });
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: 'Cast applied to ' + selected.length + ' book(s).' });
            namespace.state.dispatch({ type: 'cast/bulk/patch', open: false });
            return true;
        } catch (error) {
            namespace.state.dispatch({ type: 'cast/patch', busy: false, status: '' });
            core.notifyFailure('Could not apply the cast to the selected books', error,
                'Reload Voices and check which books were changed before trying again.');
            return false;
        }
    }

    async function toggleFavorite(adapterId, favorite) {
        try {
            await namespace.api.toggleFavorite(adapterId, favorite);
            // The favourite lives in the same file as the library, so re-read it
            // rather than patching a local copy that could drift.
            await loadLibrary(namespace.state.getState());
            await namespace.lifecycle.reloadCatalogues();
            return true;
        } catch (error) {
            core.notifyFailure('Could not change the favourite', error,
                'Reload Voices and check whether the favourite was saved.');
            return false;
        }
    }

    function bind() {
        if (bound) { return; }
        var region = core.region('cast');
        if (!region) { return; }
        region.addEventListener('change', namespace.events.onCastChange);
        region.addEventListener('click', namespace.events.onCastClick);
        bound = true;
    }

    function unbind() {}

    function mount() { bind(); }

    namespace.castPanel = {
        mount: mount,
        bind: bind,
        unbind: unbind,
        sync: sync,
        control: control,
        loadLibrary: loadLibrary,
        create: create,
        remove: remove,
        removeMember: removeMember,
        save: save,
        openApply: openApply,
        renderApplyPanel: renderApplyPanel,
        apply: apply,
        cancelApply: cancelApply,
        openBulk: openBulk,
        applyBulk: applyBulk,
        toggleFavorite: toggleFavorite
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));