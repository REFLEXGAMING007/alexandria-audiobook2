/* Voices V2 — the library's single audio manager.
 *
 * One `Audio` element for the whole Voice Library. Cards never create their own,
 * so "one preview at a time" is a property of the manager rather than something
 * each card has to remember, and a later phase can add a queue or a cache
 * without touching a single card.
 *
 * Phase 3 only plays recordings that already exist and are served by a static
 * mount the application already has. Nothing is generated here: a LoRA test or a
 * Voice Designer preview needs a GPU claim and a task lifecycle, and belongs to a
 * later phase. The state machine is nevertheless the real one - loading,
 * playing, error - because that is what generated previews will need too.
 *
 * `new Audio()` is injected so the manager can be exercised without a browser.
 */
(function (namespace) {
    'use strict';

    var state = namespace.state;

    var createAudio = null;
    var element = null;
    var loadingVoiceId = null;

    function audioElement() {
        if (element) { return element; }
        var factory = createAudio || (typeof Audio === 'function'
            ? function () { return new Audio(); }
            : null);
        if (!factory) { return null; }
        element = factory();
        element.preload = 'none';
        return element;
    }

    function isPlaying(voiceId) {
        return state.select(function (current) {
            return current.preview.playback.state === 'playing'
                && current.preview.playback.voiceId === voiceId;
        });
    }

    function isLoading(voiceId) {
        return state.select(function (current) {
            return current.preview.playback.state === 'loading'
                && current.preview.playback.voiceId === voiceId;
        });
    }

    /* Starting a preview replaces whatever was playing. One at a time, always. */
    function play(voice) {
        if (!voice || !voice.previewCapable || !voice.previewUrl) { return Promise.resolve(false); }
        var audio = audioElement();
        if (!audio) { return Promise.resolve(false); }
        stop();
        loadingVoiceId = voice.voiceId;
        state.dispatch({ type: 'preview/playback', voiceId: voice.voiceId,
            state: 'loading', error: null });

        return new Promise(function (resolve) {
            var settled = false;
            var finish = function (outcome) {
                if (settled) { return; }
                settled = true;
                if (loadingVoiceId === voice.voiceId) { loadingVoiceId = null; }
                resolve(outcome);
            };
            audio.onerror = function () {
                state.dispatch({
                    type: 'preview/playback',
                    voiceId: voice.voiceId,
                    state: 'error',
                    error: 'This preview could not be played.'
                });
                finish(false);
            };
            audio.onended = function () {
                stop();
                finish(true);
            };
            audio.src = voice.previewUrl;
            var started = audio.play();
            if (started && typeof started.then === 'function') {
                started.then(function () {
                    state.dispatch({ type: 'preview/playback', voiceId: voice.voiceId,
                        state: 'playing', error: null });
                    finish(true);
                }, function () {
                    state.dispatch({
                        type: 'preview/playback',
                        voiceId: voice.voiceId,
                        state: 'error',
                        error: 'This preview could not be played.'
                    });
                    finish(false);
                });
            } else {
                state.dispatch({ type: 'preview/playback', voiceId: voice.voiceId,
                    state: 'playing', error: null });
                finish(true);
            }
        });
    }

    function pause() {
        var audio = element;
        if (!audio || typeof audio.pause !== 'function') { return false; }
        audio.pause();
        state.dispatch({ type: 'preview/playback', voiceId: null, state: 'idle',
            error: null });
        return true;
    }

    function stop() {
        var audio = element;
        if (audio) {
            audio.onerror = null;
            audio.onended = null;
            if (typeof audio.pause === 'function') { audio.pause(); }
            audio.src = '';
        }
        state.dispatch({ type: 'preview/playback', voiceId: null, state: 'idle',
            error: null });
    }

    /* A rapid second click on the same card must not stack two requests. */
    function toggle(voice) {
        if (!voice || !voice.previewCapable) { return Promise.resolve(false); }
        if (isLoading(voice.voiceId)) { return Promise.resolve(false); }
        if (isPlaying(voice.voiceId)) { pause(); return Promise.resolve(false); }
        return play(voice);
    }

    function setAudioFactory(factory) {
        createAudio = factory;
        element = null;
    }

    namespace.libraryAudio = {
        play: play,
        pause: pause,
        stop: stop,
        toggle: toggle,
        isPlaying: isPlaying,
        isLoading: isLoading,
        setAudioFactory: setAudioFactory,
        current: function () { return element; }
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));