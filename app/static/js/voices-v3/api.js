/* Voices V3 — the API boundary.
 *
 * This is the only file in Voices V3 that writes down a URL. Every request is a
 * delegation to the application's shared `API` client (app-core.js) rather than a
 * second fetch implementation.
 *
 * The endpoints are the legacy Voices tab's own. Voices V3 is a replica of that
 * tab's features, not a new backend contract: nothing here needs a server change
 * to exist, and nothing the legacy tab can do is unavailable here.
 */
(function (namespace) {
    'use strict';

    var PATHS = Object.freeze({
        roster: '/api/voices',
        snapshot: '/api/voice_config/snapshot',
        save: '/api/voice_config/save',
        seedUnseeded: '/api/voice_config/seed_unseeded',

        designedVoices: '/api/voice_design/list',
        cloneVoices: '/api/clone_voices/list',
        loraModels: '/api/lora/models',

        personaGenerate: '/api/generate_personas',
        personaStatus: '/api/status/persona',
        personaCancel: '/api/cancel_persona',

        narratorStrategy: '/api/narrator/strategy',
        narratorPreview: '/api/narrator/preview',

        versionSave: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/versions'; },
        versionSelect: function (speaker, versionId) {
            return '/api/voices/' + encodeURIComponent(speaker) + '/versions/' + encodeURIComponent(versionId) + '/select';
        },
        candidateAdd: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/candidates'; },
        candidateSelect: function (speaker, candidateId) {
            return '/api/voices/' + encodeURIComponent(speaker) + '/candidates/' + encodeURIComponent(candidateId) + '/select';
        },
        candidateDelete: function (speaker, candidateId) {
            return '/api/voices/' + encodeURIComponent(speaker) + '/candidates/' + encodeURIComponent(candidateId);
        },
        candidateFavorite: function (speaker, candidateId) {
            return '/api/voices/' + encodeURIComponent(speaker) + '/candidates/' + encodeURIComponent(candidateId) + '/favorite';
        },
        approval: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/approval'; },
        personaVoiceAudit: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/persona-voice-audit'; },
        stateTimeline: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/state_timeline'; },
        versionTimeline: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/version_timeline'; },
        styleTimeline: function (speaker) { return '/api/voices/' + encodeURIComponent(speaker) + '/style_timeline'; },
        stylePoint: function (speaker, fromIndex) {
            return '/api/voices/' + encodeURIComponent(speaker) + '/style_timeline/' + encodeURIComponent(fromIndex);
        },

        suggest: '/api/suggest_voices',
        suggestApply: '/api/suggest_voices/apply',
        suggestApplyBulk: '/api/suggest_voices/apply_bulk',

        voiceLibrary: '/api/voice_library',
        castCreate: '/api/voice_library/casts',
        castDelete: function (name) { return '/api/voice_library/casts/' + encodeURIComponent(name); },
        castMemberDelete: function (name, key) {
            return '/api/voice_library/casts/' + encodeURIComponent(name) + '/members/' + encodeURIComponent(key);
        },
        castSave: '/api/voice_library/save',
        castMatch: '/api/voice_library/match',
        castMatchBulk: '/api/voice_library/match_bulk',
        castApply: '/api/voice_library/apply',
        castApplyBulk: '/api/voice_library/apply_bulk',
        favoriteToggle: function (adapterId) { return '/api/voice_library/favorites/' + encodeURIComponent(adapterId); },

        cloneUpload: '/api/clone_voices/upload',
        cloneDelete: function (voiceId) { return '/api/clone_voices/' + encodeURIComponent(voiceId); },
        designPreview: '/api/voice_design/preview',
        designSave: '/api/voice_design/save',

        characterAliases: '/api/character_aliases'
    });

    /* ---- read surface ---- */

    function fetchRoster() {
        return API.get(PATHS.roster);
    }

    function fetchSnapshot() {
        return API.get(PATHS.snapshot);
    }

    function fetchDesignedVoices() {
        return API.get(PATHS.designedVoices);
    }

    function fetchCloneVoices() {
        return API.get(PATHS.cloneVoices);
    }

    function fetchLoraModels() {
        return API.get(PATHS.loraModels);
    }

    function fetchVoiceLibrary() {
        return API.get(PATHS.voiceLibrary);
    }

    function fetchStateTimeline(speaker) {
        return API.get(PATHS.stateTimeline(speaker));
    }

    function fetchCharacterAliases() {
        return API.get(PATHS.characterAliases);
    }

    function fetchPersonaStatus() {
        return API.get(PATHS.personaStatus);
    }

    /* ---- write surface ---- */

    function saveVoiceDocument(payload) {
        return API.post(PATHS.save, payload);
    }

    function applySeedRepair(payload) {
        return API.post(PATHS.seedUnseeded, payload);
    }

    function generatePersonas(payload) {
        return API.post(PATHS.personaGenerate, payload);
    }

    function cancelPersonas() {
        return API.post(PATHS.personaCancel, {});
    }

    function saveNarratorStrategy(payload) {
        return API.post(PATHS.narratorStrategy, payload);
    }

    function previewNarrator(payload) {
        return API.post(PATHS.narratorPreview, payload);
    }

    function selectVersion(speaker, versionId) {
        return API.post(PATHS.versionSelect(speaker, versionId), {});
    }

    function addVersion(speaker, payload) {
        return API.post(PATHS.versionSave(speaker), payload);
    }

    function selectCandidate(speaker, candidateId) {
        return API.post(PATHS.candidateSelect(speaker, candidateId), {});
    }

    function deleteCandidate(speaker, candidateId) {
        return API.del(PATHS.candidateDelete(speaker, candidateId));
    }

    function favoriteCandidate(speaker, candidateId, favorite) {
        return API.post(PATHS.candidateFavorite(speaker, candidateId), { favorite: !!favorite });
    }

    function setApproval(speaker, field, status) {
        return API.post(PATHS.approval(speaker), { field: field, status: status });
    }

    function setPersonaVoiceAudit(speaker, payload) {
        return API.post(PATHS.personaVoiceAudit(speaker), payload);
    }

    function saveVersionTimeline(speaker, points) {
        return API.post(PATHS.versionTimeline(speaker), { points: points });
    }

    function clearVersionTimeline(speaker) {
        return API.del(PATHS.versionTimeline(speaker));
    }

    function addStylePoint(speaker, payload) {
        return API.post(PATHS.styleTimeline(speaker), payload);
    }

    function removeStylePoint(speaker, fromIndex) {
        return API.del(PATHS.stylePoint(speaker, fromIndex));
    }

    function requestSuggestions(payload) {
        return API.post(PATHS.suggest, payload);
    }

    function applySuggestion(payload) {
        return API.post(PATHS.suggestApply, payload);
    }

    function applySuggestionsBulk(payload) {
        return API.post(PATHS.suggestApplyBulk, payload);
    }

    function createCast(name) {
        return API.post(PATHS.castCreate, { name: name });
    }

    function deleteCast(name) {
        return API.del(PATHS.castDelete(name));
    }

    function deleteCastMember(name, key) {
        return API.del(PATHS.castMemberDelete(name, key));
    }

    function saveCast(payload) {
        return API.post(PATHS.castSave, payload);
    }

    function matchCast(payload) {
        return API.post(PATHS.castMatch, payload);
    }

    function matchCastBulk(payload) {
        return API.post(PATHS.castMatchBulk, payload);
    }

    function applyCast(payload) {
        return API.post(PATHS.castApply, payload);
    }

    function applyCastBulk(payload) {
        return API.post(PATHS.castApplyBulk, payload);
    }

    function toggleFavorite(adapterId, favorite) {
        return API.post(PATHS.favoriteToggle(adapterId), { favorite: !!favorite });
    }

    function uploadCloneVoice(file) {
        var form = new FormData();
        form.append('file', file);
        return API.upload(PATHS.cloneUpload, form);
    }

    function deleteCloneVoice(voiceId) {
        return API.del(PATHS.cloneDelete(voiceId));
    }

    function saveDesignedVoice(payload) {
        return API.post(PATHS.designSave, payload);
    }

    /* ---- error interpretation ---- */

    var CONFLICT = 409;

    function isConflict(error) {
        return !!(error && error.status === CONFLICT);
    }

    function statusOf(error) {
        return error && typeof error.status === 'number' ? error.status : null;
    }

    function messageOf(error, fallback) {
        if (error && typeof error.message === 'string' && error.message) { return error.message; }
        return fallback || 'The request could not be completed.';
    }

    namespace.api = Object.freeze({
        PATHS: PATHS,
        fetchRoster: fetchRoster,
        fetchSnapshot: fetchSnapshot,
        fetchDesignedVoices: fetchDesignedVoices,
        fetchCloneVoices: fetchCloneVoices,
        fetchLoraModels: fetchLoraModels,
        fetchVoiceLibrary: fetchVoiceLibrary,
        fetchStateTimeline: fetchStateTimeline,
        fetchCharacterAliases: fetchCharacterAliases,
        fetchPersonaStatus: fetchPersonaStatus,
        saveVoiceDocument: saveVoiceDocument,
        applySeedRepair: applySeedRepair,
        generatePersonas: generatePersonas,
        cancelPersonas: cancelPersonas,
        saveNarratorStrategy: saveNarratorStrategy,
        previewNarrator: previewNarrator,
        selectVersion: selectVersion,
        addVersion: addVersion,
        selectCandidate: selectCandidate,
        deleteCandidate: deleteCandidate,
        favoriteCandidate: favoriteCandidate,
        setApproval: setApproval,
        setPersonaVoiceAudit: setPersonaVoiceAudit,
        saveVersionTimeline: saveVersionTimeline,
        clearVersionTimeline: clearVersionTimeline,
        addStylePoint: addStylePoint,
        removeStylePoint: removeStylePoint,
        requestSuggestions: requestSuggestions,
        applySuggestion: applySuggestion,
        applySuggestionsBulk: applySuggestionsBulk,
        createCast: createCast,
        deleteCast: deleteCast,
        deleteCastMember: deleteCastMember,
        saveCast: saveCast,
        matchCast: matchCast,
        matchCastBulk: matchCastBulk,
        applyCast: applyCast,
        applyCastBulk: applyCastBulk,
        toggleFavorite: toggleFavorite,
        uploadCloneVoice: uploadCloneVoice,
        deleteCloneVoice: deleteCloneVoice,
        saveDesignedVoice: saveDesignedVoice,
        isConflict: isConflict,
        statusOf: statusOf,
        messageOf: messageOf
    });
}(window.VoicesV3 || (window.VoicesV3 = {})));