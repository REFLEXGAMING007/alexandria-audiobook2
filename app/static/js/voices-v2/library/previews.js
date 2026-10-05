/* Voices V2 — generated previews: selectors, polling and the generate action.
 *
 * Three responsibilities, kept apart so each is testable on its own:
 *
 *   selectors   pure reads of a voice's preview state. No DOM, no network.
 *   poll        watch one job until it reaches a terminal state.
 *   generate    the user action, which queues a job and never waits for it.
 *
 * Polling lives here rather than in the shared `_startPolling` helper because
 * that one is bound to app-core's task registry and to DOM containers outside
 * Voices V2. A local loop over an injectable timer is both smaller and directly
 * testable, and it is what guarantees the three properties this needs: one timer,
 * a terminal state that stops it, and a teardown that stops it when the library
 * closes.
 *
 * Nothing here may touch the draft or the assignment command. Generating and
 * auditioning a voice must leave the user's pending choice exactly as it was,
 * and a test asserts that.
 */
(function (namespace) {
    'use strict';

    var state = namespace.state;
    var api = namespace.api;
    /* Jobs arrive in the wire shape, like everything else from this API; the
     * conversion lives in selectors.js with the other adapters so no module
     * here has to know which side of the boundary it is on. */
    var selectors = namespace.selectors;

    var POLL_INTERVAL_MS = 700;
    var POLL_BACKOFF_MS = 2000;
    /* A stuck job must not be watched forever; the server's stale recovery is
     * what actually resolves an abandoned job. */
    var POLL_ATTEMPTS = 240;

    var timerHandle = null;
    var watchedJobId = null;
    var attempts = 0;
    var setTimerFn = function (fn, delay) { return setTimeout(fn, delay); };
    var clearTimerFn = function (handle) { return clearTimeout(handle); };

    /* ── Selectors ─────────────────────────────────────────────────── */

    function jobForVoice(current, voiceId) {
        var ids = Object.keys(current.preview.jobs);
        for (var index = ids.length - 1; index >= 0; index -= 1) {
            if (current.preview.jobs[ids[index]].voiceId === voiceId) { return current.preview.jobs[ids[index]]; }
        }
        return null;
    }

    /* The job that decides what the card shows: a live one from this session if
     * there is one, otherwise whatever the catalogue last reported. */
    function effectiveJob(current, voice) {
        var live = jobForVoice(current, voice.voiceId);
        if (live) {
            /* A completed job with audio supersedes the catalogue snapshot; any
             * other local record is the freshest word we have. */
            return live;
        }
        if (voice.previewJobId) {
            return {
                voiceId: voice.voiceId, jobId: voice.previewJobId,
                status: voice.previewState, terminal: false, progress: 0
            };
        }
        return null;
    }

    function isGenerating(voice) {
        var job = effectiveJob(state.getState(), voice);
        return !!job && (job.status === 'queued' || job.status === 'running');
    }

    function canGenerate(voice) {
        return !!voice.previewGeneratable && !!voice.available && !isGenerating(voice);
    }

    function canPlay(voice) {
        return !!voice.previewUrl && !isGenerating(voice);
    }

    function canRetry(voice) {
        var job = effectiveJob(state.getState(), voice);
        return canGenerate(voice) && !!job && job.status === 'failed';
    }

    /* The URL that would actually play right now: a freshly completed job wins
     * over the catalogue, because the catalogue is a snapshot from before it. */
    function playableUrl(voice) {
        var job = effectiveJob(state.getState(), voice);
        if (job && (job.status === 'queued' || job.status === 'running')) { return null; }
        if (job && job.status === 'completed' && job.previewUrl) { return job.previewUrl; }
        return voice.previewUrl || null;
    }

    function previewLabel(voice) {
        var job = effectiveJob(state.getState(), voice);
        if (job) {
            if (job.status === 'queued') { return 'Queued'; }
            if (job.status === 'running') { return 'Generating\u2026'; }
            if (job.status === 'failed') { return 'Preview failed'; }
            if (job.status === 'stale') { return 'Not generated'; }
        }
        if (voice.previewCapable) {
            return voice.previewKind === 'recorded' ? 'Recording' : 'Preview ready';
        }
        return 'No preview';
    }

    function previewDetail(voice) {
        var job = effectiveJob(state.getState(), voice);
        if (job && job.status === 'failed' && job.error) { return job.error; }
        if (job && job.status === 'stale') { return 'The previous preview is no longer available.'; }
        if (job && (job.status === 'queued' || job.status === 'running')) {
            return 'Rendering on the GPU. This can take a moment.';
        }
        if (voice.previewKind === 'recorded') { return 'An uploaded recording, played as saved.'; }
        if (voice.previewKind === 'generated') { return 'Rendered from this voice.'; }
        if (voice.previewGeneratable) { return 'Not generated yet.'; }
        return '';
    }

    function activeJob(current) {
        if (!current.preview.activeJob) { return null; }
        return current.preview.jobs[current.preview.activeJob] || null;
    }

    function jobProgress(job) {
        if (!job) { return null; }
        return typeof job.progress === 'number' ? job.progress : 0;
    }

    /* ── Polling ───────────────────────────────────────────────────── */

    function clearTimer() {
        if (timerHandle !== null) { clearTimerFn(timerHandle); }
        timerHandle = null;
    }

    function stopPolling() {
        clearTimer();
        watchedJobId = null;
        attempts = 0;
        state.dispatch({ type: 'preview/stopPolling' });
    }

    function finish(job) {
        state.dispatch({ type: 'preview/finish', jobId: job.jobId, job: job });
        clearTimer();
        watchedJobId = null;
        attempts = 0;
    }

    /* A status read that fails is not the job failing, so polling stops rather
     * than retrying a request that will keep failing. */
    function pollFailure(jobId, error) {
        var code = api.refusalCode(error);
        state.dispatch({
            type: 'preview/attach',
            job: {
                jobId: jobId, voiceId: voiceForJobId(jobId), status: 'failed',
                terminal: true, progress: 1, errorCode: code,
                error: api.refusalMessage(error, 'Lost track of that preview.')
            }
        });
        state.dispatch({ type: 'preview/finish', jobId: jobId, job: null });
        stopPolling();
    }

    function voiceForJobId(jobId) {
        var jobs = state.getState().preview.jobs;
        return jobs[jobId] ? jobs[jobId].voiceId : null;
    }

    function poll(jobId) {
        watchedJobId = jobId;
        return api.readPreview(jobId).then(function (raw) {
            var job = selectors.adaptPreviewJob(raw);
            state.dispatch({ type: 'preview/attach', job: job });
            if (job.terminal) { finish(job); return job; }
            attempts += 1;
            if (attempts > POLL_ATTEMPTS) {
                stopPolling();
                return job;
            }
            /* Back off once the first answer confirms real work is happening. */
            clearTimer();
            timerHandle = setTimerFn(function () { poll(jobId); },
                attempts === 1 ? POLL_INTERVAL_MS : POLL_BACKOFF_MS);
            return job;
        }, function (error) {
            pollFailure(jobId, error);
            return null;
        });
    }

    /* ── Generate ──────────────────────────────────────────────────── */

    function voiceOf(voiceId) {
        return namespace.libraryPanel.findVoice(voiceId);
    }

    function isGeneratingVoice(voiceId) {
        var voice = voiceOf(voiceId);
        return voice ? isGenerating(voice) : false;
    }

    /* Duplicate clicks are suppressed here as well as on the server: two layers,
     * because a browser and a network can each be slow, and the cheapest place
     * to stop a second request is before it is made. */
    function generate(voiceId, profile) {
        if (isGeneratingVoice(voiceId)) { return Promise.resolve(null); }
        var voice = voiceOf(voiceId);
        if (!voice || !canGenerate(voice)) { return Promise.resolve(null); }
        attempts = 0;
        return api.createPreview(voiceId, profile).then(function (raw) {
            var job = selectors.adaptPreviewJob(raw);
            state.dispatch({ type: 'preview/start', jobId: job.jobId });
            state.dispatch({ type: 'preview/attach', job: job });
            if (job.terminal) { finish(job); return job; }
            return poll(job.jobId);
        }, function (error) {
            /* A refusal is shown on the card, not thrown at the user. */
            state.dispatch({
                type: 'preview/attach',
                job: {
                    jobId: 'refused:' + voiceId, voiceId: voiceId, status: 'failed',
                    terminal: true, progress: 1,
                    errorCode: api.refusalCode(error),
                    error: api.refusalMessage(error, 'That preview could not be started.')
                }
            });
            return null;
        });
    }

    function cancel(jobId) {
        return api.cancelPreview(jobId).then(function (raw) {
            var job = selectors.adaptPreviewJob(raw);
            state.dispatch({ type: 'preview/finish', jobId: jobId, job: job });
            return job;
        }, function (error) {
            return {
                jobId: jobId, status: 'refused', terminal: true,
                error: api.refusalMessage(error, 'That preview could not be cancelled.')
            };
        });
    }

    /* ── Playback ───────────────────────────────────────────────────── */

    /* The one audio manager plays recorded and generated previews alike: the only
     * difference is where the URL came from. The record is passed on whole,
     * because the manager decides for itself whether a preview is playable.
     */
    function play(voiceId) {
        var voice = voiceOf(voiceId);
        if (!voice) { return Promise.resolve(false); }
        var url = playableUrl(voice);
        if (!url) { return Promise.resolve(false); }
        return namespace.libraryAudio.toggle({
            voiceId: voice.voiceId, previewUrl: url,
            previewCapable: true, previewKind: voice.previewKind
        });
    }

    namespace.libraryPreviews = {
        generate: generate,
        cancel: cancel,
        play: play,
        poll: poll,
        stopPolling: stopPolling,
        isGenerating: isGenerating,
        isGeneratingVoice: isGeneratingVoice,
        canGenerate: canGenerate,
        canPlay: canPlay,
        canRetry: canRetry,
        playableUrl: playableUrl,
        previewLabel: previewLabel,
        previewDetail: previewDetail,
        activeJob: activeJob,
        jobProgress: jobProgress,
        jobForVoice: jobForVoice,
        effectiveJob: effectiveJob,
        setTimers: function (setter, clearer) {
            setTimerFn = setter;
            clearTimerFn = clearer;
        },
        POLL_INTERVAL_MS: POLL_INTERVAL_MS,
        POLL_BACKOFF_MS: POLL_BACKOFF_MS,
        POLL_ATTEMPTS: POLL_ATTEMPTS
    };
}(window.VoicesV2 || (window.VoicesV2 = {})));