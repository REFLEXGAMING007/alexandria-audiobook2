/* Voices V2 — the HTTP boundary.
 *
 * This is the only file in Voices V2 that names a URL. Panels call the named
 * operations below and never call API.get()/API.post() themselves, so the
 * transport stays swappable and a path cannot drift across panels.
 *
 * It delegates to the shared global `API` helper rather than adding a second
 * HTTP client. That helper owns base-URL handling and, importantly, attaches
 * `status` and `detail` to every rejected request — the error shape the save
 * path depends on, because a 409 is a conflict to recover from and a 400 is a
 * refusal to explain.
 *
 * PATHS is frozen: a panel that could rewrite the table could also point a read
 * at another endpoint, which is the coupling this file exists to prevent.
 */
(function (namespace) {
    'use strict';

    var PATHS = Object.freeze({
        characters: '/api/voices-v2/characters',
        voices: '/api/voices-v2/voices',
        command: '/api/voices-v2/command'
    });

    /* Refusal codes the backend can return. They are stable, so a panel can pick
     * wording from `code` instead of parsing an English message. Anything not
     * listed is treated as `unknown`, which is why this list and
     * labels.refusalText are kept side by side. */
    var CODES = Object.freeze({
        INVALID_VOICE: 'invalid_voice',
        UNKNOWN_VOICE: 'unknown_voice',
        VOICE_UNAVAILABLE: 'voice_unavailable',
        UNKNOWN_CHARACTER: 'unknown_character',
        AMBIGUOUS_CHARACTER: 'ambiguous_character',
        CHARACTER_GONE: 'character_no_longer_present',
        NOTHING_TO_CLEAR: 'nothing_to_clear',
        UNKNOWN_COMMAND: 'unknown_command',
        INVALID_CONFIGURATION: 'invalid_configuration',
        DUPLICATE_VOICE_IDS: 'duplicate_voice_ids',
        STALE_SNAPSHOT: 'stale_snapshot',
        BUSY: 'busy'
    });

    function fetchCharacters() {
        return API.get(PATHS.characters);
    }

    /* The assignable voice catalogue. Voices V2 does not own this data: it is
     * assembled server-side from the manifests the application already keeps.
     */
    function fetchVoices() {
        return API.get(PATHS.voices);
    }

    /* One command, one character. The request describes an intention - who, and
     * which catalogue voice - and carries the two concurrency fields the
     * existing guarded save requires. It deliberately cannot describe a
     * configuration: the stored entry is read, merged and revalidated on the
     * server, so a client can neither drop a field it does not understand nor
     * write a path the engine could not resolve. */
    function sendCommand(command) {
        return API.post(PATHS.command, {
            command: command.command,
            character: command.character,
            voice_id: command.voiceId === undefined ? null : command.voiceId,
            revision: command.revision,
            book_token: command.bookToken
        });
    }

    /* Pull a refusal code out of an API error. The shared helper attaches
     * `detail`, which the V2 routes set to `{code, message}`; anything else
     * (a 500, a network failure, a shape from another router) has no code and
     * must not be guessed at. */
    function refusalCode(error) {
        var detail = error && error.detail;
        if (detail && typeof detail === 'object' && typeof detail.code === 'string') {
            return detail.code;
        }
        return null;
    }

    function refusalMessage(error, fallback) {
        var detail = error && error.detail;
        if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
            return detail.message;
        }
        if (typeof detail === 'string' && detail) { return detail; }
        return (error && error.message) || fallback || 'The request failed.';
    }

    namespace.api = Object.freeze({
        PATHS: PATHS,
        CODES: CODES,
        fetchCharacters: fetchCharacters,
        fetchVoices: fetchVoices,
        sendCommand: sendCommand,
        refusalCode: refusalCode,
        refusalMessage: refusalMessage
    });
}(window.VoicesV2 || (window.VoicesV2 = {})));