/* Voices V2 — the HTTP boundary.
 *
 * This is the only file in Voices V2 that names a URL. Panels call the named
 * operations below and never call API.get()/API.post() themselves, so the
 * transport stays swappable and a path cannot drift across panels.
 *
 * It delegates to the shared global `API` helper rather than adding a second
 * HTTP client. That helper owns base-URL handling and, importantly, attaches
 * `status` and `detail` to every rejected request — the error shape V2's
 * recovery copy depends on.
 *
 * PATHS is frozen: a panel that could rewrite the table could also point the
 * read at another endpoint, which is the coupling this file exists to prevent.
 */
(function (namespace) {
    'use strict';

    var PATHS = Object.freeze({
        characters: '/api/voices-v2/characters'
    });

    function fetchCharacters() {
        return API.get(PATHS.characters);
    }

    namespace.api = Object.freeze({
        PATHS: PATHS,
        fetchCharacters: fetchCharacters
    });
}(window.VoicesV2 || (window.VoicesV2 = {})));