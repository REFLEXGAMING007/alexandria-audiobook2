/* Voices V2 — library entry point.
 *
 * The library's public surface, plus the one piece of shared behaviour the
 * library and the character detail both need: applying a server-confirmed set
 * of favourites back into the store.
 *
 * Favourites are worth that shared helper because they are a property of a
 * *voice*, not of a character or of a panel. Starring a voice from the library
 * has to be visible in the character editor and vice versa, and the honest way
 * to do that is one function that rewrites the flag on every record from the
 * server's authoritative list rather than one flag the caller flips and hopes
 * survives.
 *
 * The library never saves an assignment. Choosing a voice dispatches
 * `draft/choose`, and Phase 2's assignment panel owns the single save path -
 * revision, book token and conflict handling included.
 */
(function (namespace) {
    'use strict';

    var core = namespace.core;
    var state = namespace.state;
    var panel = namespace.libraryPanel;

    /* Rewrite `favorite` on every record from the server's list.
     *
     * The server resolves adapter aliases before answering, so matching on the
     * adapter id is the only reliable way; a record whose `native_id` is not in
     * the list is set to false rather than left alone, because the list is
     * authoritative and a stale true would be a lie.
     */
    function applyFavorites(favorites) {
        var wanted = {};
        (favorites || []).forEach(function (id) { wanted[id] = true; });
        var voices = state.getState().catalogue.voices.map(function (voice) {
            var isFavorite = !!wanted[voice.nativeId];
            if (voice.favorite === isFavorite) { return voice; }
            return Object.assign({}, voice, { favorite: isFavorite });
        });
        state.dispatch({ type: 'catalogue/voices', voices: voices });
        return voices.length;
    }

    function isOpen() {
        return state.select(function (current) { return current.library.open; });
    }

    /* Open for a character: the library prefills its context from that
     * character's traits, so the filters start with something to suggest. */
    function openFor(characterKey) {
        panel.open(characterKey);
    }

    /* Open with no subject: a plain catalogue browser. */
    function open() {
        panel.open(null);
    }

    function close() {
        panel.close();
    }

    function choose(voiceId) {
        return panel.choose(voiceId);
    }

    namespace.libraryIndex = {
        mount: function () { panel.mount(); },
        unmount: function () { panel.unmount(); },
        render: function () { return panel.render(); },
        open: open,
        openFor: openFor,
        close: close,
        choose: choose,
        isOpen: isOpen,
        applyFavorites: applyFavorites,
        filters: namespace.libraryFilters,
        panel: panel,
        audio: namespace.libraryAudio,
        previews: namespace.libraryPreviews,
        cards: namespace.libraryCards,
        root: core.ROOT_ID
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));