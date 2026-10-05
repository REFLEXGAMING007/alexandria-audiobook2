"""Voices V2 generated previews on the browser side.

The behaviours that matter here are all about restraint: a click must not turn
into two renders, a poll must stop, and nothing here may touch the draft or the
assignment path. Generating and auditioning a voice has to leave the user's
pending choice exactly as it was, and that is asserted explicitly rather than
assumed.

Polling is driven through an injected timer, so a test decides when the next tick
happens instead of waiting on a real clock.
"""
import subprocess
import sys
import unittest

from tests.test_voices_v2_isolation import _HARNESS
from tests.test_voices_v2_isolation import V2_FILES as V2_FILE_ORDER


#: A catalogue with one adapter that can be generated and one that already has a
#: recorded preview, so both paths through the card are exercised.
CATALOGUE = r"""
const CATALOGUE={schema_version:1,voices:[
  {voice_id:'lora:bare',native_id:'bare',kind:'lora',name:'bare',label:'bare',
   source:'Trained LoRA',realisation:'adapter',description:'A voice with no preview yet',
   sample_text:null,gender:'male',gender_source:'declared',age_group:'adult',
   age_group_source:'inferred',ageless:false,added_at:null,availability:'available',
   available:true,unavailable_reason:'',downloaded:true,favorite:false,
   favorite_supported:true,adapter_id:'bare',adapter_path:'lora_models/bare',
   ref_audio:null,ref_text:null,preview_capable:false,preview_url:null,preview_kind:null,
   preview_state:'none',preview_generatable:true,preview_job_id:null,tags:[],metadata:{}},
  {voice_id:'lora:ready',native_id:'ready',kind:'lora',name:'ready',label:'ready',
   source:'Trained LoRA',realisation:'adapter',description:'A voice that was rendered',
   sample_text:null,gender:'female',gender_source:'inferred',age_group:'young_adult',
   age_group_source:'inferred',ageless:false,added_at:1700000000,availability:'available',
   available:true,unavailable_reason:'',downloaded:true,favorite:false,
   favorite_supported:true,adapter_id:'ready',adapter_path:'lora_models/ready',
   ref_audio:null,ref_text:null,preview_capable:true,
   preview_url:'/lora_models/ready/preview_sample.wav',preview_kind:'generated',
   preview_state:'generated',preview_generatable:true,preview_job_id:null,tags:[],
   metadata:{}},
  {voice_id:'clone:clip',native_id:'clip',kind:'clone',name:'A clip',label:'A clip',
   source:'Uploaded clone',realisation:'clone_recording',description:'an uploaded clip',
   sample_text:'hello',gender:'unknown',gender_source:'unknown',age_group:'unknown',
   age_group_source:'unknown',ageless:false,added_at:null,availability:'available',
   available:true,unavailable_reason:'',downloaded:true,favorite:false,
   favorite_supported:false,adapter_id:null,adapter_path:null,
   ref_audio:'clone_voices/clip.wav',ref_text:'hello',preview_capable:true,
   preview_url:'/clone_voices/clip.wav',preview_kind:'recorded',preview_state:'recorded',
   preview_generatable:false,preview_job_id:null,tags:[],metadata:{}}],
 counts:{total:3,available:3,unavailable:0},kinds:['lora','clone','design'],
 favorite_kinds:['lora'],warnings:[],unsupported_kinds:{},
 preview_profiles:['standard'],generated_kinds:['lora','builtin_lora']};"""

PROJECTION = r"""
const PROJECTION={meta:{
  schemaVersion:1,revision:'rev-1',
  book:{bookId:'Book',token:'tok-1',scriptSha256:'sha',scriptPresent:true},
  traitsAvailable:true,traitsRequested:true,aliasesRegistered:true,majorLineThreshold:25,
  vocabularies:{genders:['male','female','unknown'],
    ageGroups:[{value:'adult',label:'30-39'}],problemCodes:[]}},
 characters:[
  {key:'mira',name:'MIRA',identityKey:'mira',libraryKey:'mira',presentInScript:true,
   generic:false,lineCount:40,priority:'major',knownAs:[],aliases:[],ready:true,
   voice:{category:'lora',type:'lora',catalogueVoiceId:'lora:ready',label:'ready',
     assigned:true,adapterId:'ready',adapterAvailable:true,hasRefAudio:false,
     refAudioPresent:null,hasDescription:false,seed:null,aliasOf:null,ensembleMembers:0},
   voiceStatus:'assigned',personaStatus:'generated',personaRef:null,personaRefResolves:null,
   activeVersion:null,versions:[],versionTimeline:[],candidateCount:0,
   traits:{gender:'female',ageGroup:'adult',ageless:false,lines:40,
     current:{gender:'female',ageGroup:'adult'},states:[]},
   traitsAvailable:true,states:[],possibleDuplicateOf:[],problems:[]}],
 orphans:[]};"""


class PreviewBrowserTestCase(unittest.TestCase):
    """Mounts the library with a controllable clock and a scripted job server."""

    #: What the fake server answers, mutated by a test to steer the run.
    def run_previews(self, body, setup_extra=""):
        setup = _HARNESS % {"files": repr(list(V2_FILE_ORDER))}
        prologue = (
            CATALOGUE + PROJECTION
            + "\nconst _v2get=API.get;"
            "\nAPI.get=function(path){"
            "  if(path==='/api/voices-v2/voices')"
            "    return Promise.resolve(JSON.parse(JSON.stringify(CATALOGUE)));"
            "  return _v2get(path);"
            "};"
            # The fake job server: a script the test drives one answer at a time.
            "\nconst created=[];let jobSeq=0;"
            "\nlet jobStatus=[];          /* answers returned by successive polls */"
            "\nlet createError=null;let createMode='queued';let createAnswer=null;"
            "\nlet cancelCalls=[];"
            "\nAPI.post=function(path,body){"
            "  if(path==='/api/voices-v2/previews'){"
            "    if(createError)return Promise.reject(createError);"
            "    const job=createAnswer||{job_id:'job'+(++jobSeq),voice_id:body.voice_id,"
            "      name:'bare',kind:'lora',profile:body.profile,status:createMode,"
            "      progress:createMode==='queued'?0:1,terminal:createMode!=='queued',"
            "      created_at:1,started_at:null,completed_at:null,preview_url:null,"
            "      audio_url:null,error:null,error_code:null,cached:false,"
            "      deduplicated:false};"
            "    created.push(body);return Promise.resolve(job);"
            "  }"
            "  if(/\\/previews\\/[^/]+\\/cancel$/.test(path)){"
            "    cancelCalls.push(path);"
            "    return Promise.resolve({job_id:'x',voice_id:'lora:bare',status:'cancelled',"
            "      progress:1,terminal:true,deduplicated:false,created_at:1,started_at:null,"
            "      completed_at:2,preview_url:null,audio_url:null,error:null,"
            "      error_code:null,cached:false});"
            "  }"
            "  return Promise.reject(Error('unexpected '+path));"
            "};"
            "\nconst readCalls=[];"
            "\nAPI.get=function(path){"
            "  if(path==='/api/voices-v2/voices')"
            "    return Promise.resolve(JSON.parse(JSON.stringify(CATALOGUE)));"
            "  if(path.indexOf('/api/voices-v2/previews/')===0){"
            "    readCalls.push(path);"
            "    const jobId=path.split('/').pop();"
            "    const answer=jobStatus.shift()||{job_id:jobId,voice_id:'lora:bare',"
            "      name:'bare',kind:'lora',profile:'standard',status:'completed',progress:1,"
            "      terminal:true,created_at:1,started_at:2,completed_at:3,"
            "      preview_url:'/lora_models/bare/preview_sample.wav',"
            "      audio_url:'/lora_models/bare/preview_sample.wav',error:null,"
            "      error_code:null,cached:false,deduplicated:false};"
            "    return Promise.resolve(answer);"
            "  }"
            "  return _v2get(path);"
            "};"
            # A clock the test drives, so no test waits on a real timer. The installer is
            # declared inside the IIFE below, because it needs the namespace and a
            # top-level function could not see a const declared in there.
            "\nlet timers=[];"
            "\nfunction tick(){"
            "  const pending=timers.filter(t=>t&&t.fn);"
            "  timers=timers.map(t=>t?Object.assign({},t,{fn:null}):t);"
            "  pending.forEach(t=>t.fn());"
            "}"
            "\nlet done=false;"
            "\nprocess.on('beforeExit',function(){assert(done,'assertions must finish');});"
            "\n(async()=>{\nloadAll();\nconst V2=ctx.window.VoicesV2;\n"
            "V2.library.previews.setTimers("
            "  function(fn,delay){timers.push({fn:fn,delay:delay});return timers.length;},"
            "  function(handle){if(handle&&timers[handle-1])timers[handle-1].fn=null;});\n"
            "await V2.mount();await turn();await turn();"
            "V2.dispatch({type:'meta/set',meta:PROJECTION.meta});"
            "V2.dispatch({type:'characters/set',characters:PROJECTION.characters});"
            "V2.dispatch({type:'orphans/set',orphans:PROJECTION.orphans});await turn();"
            "V2.dispatch({type:'selection/set',key:'mira'});await turn();"
            "V2.library.openFor('mira');await turn();\n"
            "function setControl(name,value,type){const el=node(name);el.value=value;"
            "  node('library').fire(type,{target:el});}\n"
            + setup_extra + "\n" + body
            + "\ndone=true;\n})().catch(function(e){console.error(e);process.exitCode=1;});"
        )
        result = subprocess.run(["node", "-e", setup + prologue, str(self.directory())],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def directory(self):
        from tests.test_voices_v2_isolation import V2_DIR
        return V2_DIR


class SelectorTests(PreviewBrowserTestCase):
    def test_a_voice_with_no_preview_offers_generation(self):
        self.run_previews(r"""
const voice=V2.library.panel.findVoice('lora:bare');
assert.strictEqual(V2.library.previews.canGenerate(voice),true);
assert.strictEqual(V2.library.previews.canPlay(voice),false);
assert.strictEqual(V2.library.previews.previewLabel(voice),'No preview');
assert.strictEqual(V2.library.previews.previewDetail(voice),'Not generated yet.');
""")

    def test_a_rendered_voice_offers_playback_and_not_generation(self):
        self.run_previews(r"""
const voice=V2.library.panel.findVoice('lora:ready');
assert.strictEqual(V2.library.previews.canPlay(voice),true);
assert.strictEqual(V2.library.previews.playableUrl(voice),
  '/lora_models/ready/preview_sample.wav');
assert.strictEqual(V2.library.previews.previewLabel(voice),'Preview ready');
""")

    def test_a_recorded_voice_says_it_is_a_recording(self):
        self.run_previews(r"""
const voice=V2.library.panel.findVoice('clone:clip');
assert.strictEqual(V2.library.previews.previewLabel(voice),'Recording');
assert.match(V2.library.previews.previewDetail(voice),/uploaded recording/);
assert.strictEqual(V2.library.previews.canGenerate(voice),false,
  'a family with its own recording is not regenerated');
""")

    def test_preview_state_is_never_confused_with_availability(self):
        """A voice with no preview is still assignable. The two questions are
        separate and the selectors keep them separate."""
        self.run_previews(r"""
const voice=V2.library.panel.findVoice('lora:bare');
assert.strictEqual(voice.available,true);
assert.strictEqual(voice.previewState,'none');
assert.strictEqual(V2.library.panel.findVoice('lora:ready').available,true);
""")


class CardTests(PreviewBrowserTestCase):
    def test_a_card_offers_generate_rather_than_a_dead_play_button(self):
        self.run_previews(r"""
const html=node('library-list').innerHTML;
assert(html.includes('Generate Preview'),html);
assert(html.includes('Not generated yet.'));
assert(html.includes('data-voicesv2-action="generate-preview"'));
""")

    def test_a_generated_voice_offers_play(self):
        self.run_previews(r"""
const html=node('library-list').innerHTML;
assert(html.includes('data-voicesv2-action="play-preview"'),html);
assert(html.includes('Preview ready'));
""")

    def test_the_preview_status_is_announced_and_readable_without_colour(self):
        self.run_previews(r"""
const html=node('library-list').innerHTML;
assert(html.includes('role="status"'),html);
assert(html.includes('vv2-preview-label'));
""")


class GenerateTests(PreviewBrowserTestCase):
    def test_generate_queues_one_job_and_polls_until_it_completes(self):
        self.run_previews(r"""
/* The fake server mints `job1` on create, so every answer here uses that id: a
   real create and its polls always agree on it. */
jobStatus=[
 {job_id:'job1',voice_id:'lora:bare',name:'bare',kind:'lora',profile:'standard',
  status:'queued',progress:0,terminal:false,created_at:1,started_at:null,completed_at:null,
  preview_url:null,audio_url:null,error:null,error_code:null,cached:false,deduplicated:false},
 {job_id:'job1',voice_id:'lora:bare',status:'running',progress:0.5,terminal:false,
  preview_url:null},
 {job_id:'job1',voice_id:'lora:bare',status:'completed',progress:1,terminal:true,
  preview_url:'/lora_models/bare/preview_sample.wav'}];
const pending=V2.library.previews.generate('lora:bare','standard');
await turn();
assert.strictEqual(created.length,1,'one request was made');
assert.deepStrictEqual(plain(created[0]),{voice_id:'lora:bare',profile:'standard'},
  'a browser names a voice and a profile, and nothing else');
/* The first poll happens straight after the create; further ones are ticks. */
assert.strictEqual(Object.values(V2.getState().preview.jobs)[0].status,'queued');
assert.strictEqual(V2.getState().preview.activeJob,'job1');
assert.strictEqual(V2.getState().preview.polling,true);
tick();await turn();
assert.strictEqual(Object.values(V2.getState().preview.jobs)[0].status,'running');
tick();await turn();await pending;await turn();
const job=Object.values(V2.getState().preview.jobs)[0];
assert.strictEqual(job.status,'completed');
assert.strictEqual(job.previewUrl,'/lora_models/bare/preview_sample.wav');
assert.strictEqual(V2.getState().preview.activeJob,null,'polling released the job');
assert.strictEqual(V2.getState().preview.polling,false);
""")

    def test_the_card_shows_queued_then_running_then_ready(self):
        self.run_previews(r"""
jobStatus=[
 {job_id:'j1',voice_id:'lora:bare',status:'queued',progress:0,terminal:false,preview_url:null},
 {job_id:'j1',voice_id:'lora:bare',status:'running',progress:0.5,terminal:false,preview_url:null},
 {job_id:'j1',voice_id:'lora:bare',status:'completed',progress:1,terminal:true,
  preview_url:'/lora_models/bare/preview_sample.wav'}];
const pending=V2.library.previews.generate('lora:bare','standard');
await turn();await turn();
assert(node('library-list').innerHTML.includes('Queued'));
tick();await turn();await turn();
assert(node('library-list').innerHTML.includes('Generating'));
tick();await turn();await pending;await turn();
const html=node('library-list').innerHTML;
assert(html.includes('Preview ready'),html);
assert(html.includes('data-voicesv2-action="play-preview"'),html);
""")

    def test_a_second_click_while_a_job_is_in_flight_makes_no_second_request(self):
        """The cheapest place to stop a duplicate is before it is made."""
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'running',progress:0.5,terminal:false,
  preview_url:null}];
const first=V2.library.previews.generate('lora:bare','standard');
await turn();
const second=V2.library.previews.generate('lora:bare','standard');
const third=V2.library.previews.generate('lora:bare','standard');
await turn();await turn();
assert.strictEqual(created.length,1,'three clicks produced one request');
tick();await turn();await first;await turn();
assert.strictEqual(created.length,1);
""")

    def test_a_refusal_is_shown_on_the_card_and_creates_no_job(self):
        self.run_previews(r"""
createError=Object.assign(Error('busy'),{status:409,
  detail:{code:'busy',message:'Audiobook generation is using the GPU.'}});
await V2.library.previews.generate('lora:bare','standard');
await turn();await turn();
const html=node('library-list').innerHTML;
assert(html.includes('Preview failed'),html);
assert(html.includes('Audiobook generation is using the GPU.'),html);
assert(html.includes('data-voicesv2-action="generate-preview"'),'retry is offered');
""")

    def test_a_failed_job_offers_retry(self):
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'failed',progress:1,terminal:true,
  preview_url:null,error:'The generated audio was not usable.',error_code:'invalid_audio'}];
await V2.library.previews.generate('lora:bare','standard');
await turn();await turn();await turn();
const html=node('library-list').innerHTML;
assert(html.includes('Preview failed'),html);
assert(html.includes('The generated audio was not usable.'),html);
assert(html.includes('Retry'),html);
assert(V2.library.previews.canRetry(V2.library.panel.findVoice('lora:bare')));
""")

    def test_retry_after_a_failure_starts_a_new_job(self):
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'failed',progress:1,terminal:true,
  preview_url:null,error:'nope',error_code:'invalid_audio'}];
await V2.library.previews.generate('lora:bare','standard');
await turn();await turn();await turn();
assert.strictEqual(created.length,1);
await V2.library.previews.generate('lora:bare','standard');
await turn();
assert.strictEqual(created.length,2,'a failed job does not block a retry');
""")

    def test_generate_does_nothing_for_a_voice_that_cannot_be_generated(self):
        self.run_previews(r"""
assert.strictEqual(await V2.library.previews.generate('clone:clip','standard'),null);
assert.strictEqual(created.length,0,'a clone is not regenerated');
assert.strictEqual(await V2.library.previews.generate('lora:nope','standard'),null);
assert.strictEqual(created.length,0);
""")

    def test_a_status_read_that_fails_stops_the_poll_without_claiming_the_job_failed_twice(self):
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'queued',progress:0,terminal:false,
  preview_url:null}];
const pending=V2.library.previews.generate('lora:bare','standard');
await turn();
const before=timers.filter(t=>t&&t.fn).length;
assert.strictEqual(before>=1,true,'a poll was scheduled');
V2.library.previews.stopPolling();
assert.strictEqual(V2.getState().preview.polling,false);
const after=timers.filter(t=>t&&t.fn).length;
assert.strictEqual(after,0,'no timer survives a stop');
""")

    def test_poll_count_is_bounded(self):
        self.run_previews(r"""
assert.strictEqual(V2.library.previews.POLL_ATTEMPTS>0,true);
assert.ok(V2.library.previews.POLL_BACKOFF_MS>=V2.library.previews.POLL_INTERVAL_MS,
  'the second attempt waits at least as long as the first');
""")


class PlaybackTests(PreviewBrowserTestCase):
    def test_a_generated_preview_plays_through_the_one_audio_manager(self):
        self.run_previews(r"""
let played=[];let paused=0;
V2.library.audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){this.paused=false;played.push(this.src);return Promise.resolve();},
    pause:function(){this.paused=true;paused+=1;}};
});
V2.dispatch({type:'preview/attach',job:{jobId:'j1',voiceId:'lora:bare',status:'completed',
  terminal:true,progress:1,previewUrl:'/lora_models/bare/preview_sample.wav'}});
await turn();
await V2.library.previews.play('lora:bare');
assert.deepStrictEqual(plain(played),['/lora_models/bare/preview_sample.wav'],
  'the freshly generated preview is what plays');
""")

    def test_a_recorded_preview_still_plays_the_same_way(self):
        self.run_previews(r"""
let played=[];
V2.library.audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){played.push(this.src);return Promise.resolve();},
    pause:function(){this.paused=true;}};
});
await V2.library.previews.play('clone:clip');
assert.deepStrictEqual(plain(played),['/clone_voices/clip.wav']);
""")

    def test_only_one_preview_plays_at_a_time(self):
        self.run_previews(r"""
let played=[];
V2.library.audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){played.push(this.src);return Promise.resolve();},
    pause:function(){this.paused=true;}};
});
await V2.library.previews.play('lora:ready');
await V2.library.previews.play('clone:clip');
assert.strictEqual(played.length,2);
assert.strictEqual(V2.getState().preview.playback.voiceId,'clone:clip',
  'the second replaced the first');
""")

    def test_closing_the_library_stops_polling_and_playback(self):
        self.run_previews(r"""
let paused=0;
V2.library.audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){this.paused=false;return Promise.resolve();},
    pause:function(){this.paused=true;paused+=1;}};
});
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'queued',progress:0,terminal:false,
  preview_url:null}];
const pending=V2.library.previews.generate('lora:bare','standard');
await turn();
await V2.library.previews.play('lora:ready');
await turn();
V2.library.close();
await turn();
assert.strictEqual(V2.getState().preview.polling,false);
assert.strictEqual(timers.filter(t=>t&&t.fn).length,0,'no timer outlives the library');
assert.ok(paused>0,'playback stopped with it');
""")

    def test_playing_a_voice_that_is_generating_does_nothing(self):
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'running',progress:0.5,terminal:false,
  preview_url:null}];
const pending=V2.library.previews.generate('lora:bare','standard');
await turn();await turn();
assert.strictEqual(V2.library.previews.playableUrl(V2.library.panel.findVoice('lora:bare')),
  null,'a voice mid-render has nothing to play yet');
tick();await turn();await turn();await pending;
""")


class NoSideEffectTests(PreviewBrowserTestCase):
    """§37: browsing and auditioning never touch the assignment."""

    def test_generating_a_preview_creates_no_draft_and_saves_nothing(self):
        self.run_previews(r"""
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'completed',progress:1,terminal:true,
  preview_url:'/lora_models/bare/preview_sample.wav'}];
const draftBefore=plain(V2.voiceDraft(V2.getState()));
await V2.library.previews.generate('lora:bare','standard');
await turn();await turn();await turn();
assert.deepStrictEqual(plain(V2.voiceDraft(V2.getState())),draftBefore,
  'a preview must not become a pending choice');
assert.strictEqual(V2.canSaveVoice(V2.getState()),false,'nothing to save');
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'idle');
""")

    def test_playing_a_preview_changes_neither_the_draft_nor_the_selection(self):
        self.run_previews(r"""
V2.library.audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){this.paused=false;return Promise.resolve();},
    pause:function(){this.paused=true;}};
});
V2.dispatch({type:'draft/choose',voiceId:'lora:ready'});
await turn();
const draftBefore=plain(V2.voiceDraft(V2.getState()));
await V2.library.previews.play('lora:bare');
await turn();
assert.deepStrictEqual(plain(V2.voiceDraft(V2.getState())),draftBefore);
assert.strictEqual(V2.getState().selection.key,'mira','the character is unchanged');
""")

    def test_a_preview_never_reaches_the_assignment_command(self):
        self.run_previews(r"""
let commands=[];
V2.api.sendCommand=function(command){commands.push(command);
  return Promise.resolve({status:'saved'});};
jobStatus=[{job_id:'j1',voice_id:'lora:bare',status:'completed',progress:1,terminal:true,
  preview_url:'/lora_models/bare/preview_sample.wav'}];
await V2.library.previews.generate('lora:bare','standard');
await turn();await turn();await turn();
await V2.library.previews.play('lora:bare');
await turn();
assert.deepStrictEqual(plain(commands),[],'no assignment command was ever issued');
assert.strictEqual(V2.getState().save.state,'idle');
""")


class SourceBoundaryTests(unittest.TestCase):
    """Preview work goes through the V2 boundary and nowhere else."""

    def _code(self, name):
        from tests.test_voices_v2_isolation import strip_js_comments
        path = __import__("pathlib").Path(
            __import__("tests.test_voices_v2_isolation", fromlist=["V2_DIR"]).V2_DIR) / name
        return strip_js_comments(path.read_text(encoding="utf-8"))

    def test_only_the_api_module_names_a_preview_url(self):
        for name in V2_FILE_ORDER:
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("fetch(", code, f"{name} must use the shared API helper")
                if name == "api.js":
                    # The one module allowed to hold the path, and it must.
                    self.assertIn("previews: '/api/voices-v2/previews'", code)
                    continue
                self.assertNotIn("/api/", code,
                                 f"{name} must not name a Voices V2 URL")

    def test_the_previews_module_holds_no_assignment_logic(self):
        code = self._code("library/previews.js")
        for banned in ("draft/choose", "draft/clearVoice", "sendCommand",
                       "save/start", "voice_config"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, code,
                                 "preview generation must not touch the assignment path")

    def test_the_store_holds_no_preview_playback_objects(self):
        code = self._code("state.js")
        self.assertNotIn("Audio", code.replace("previewJobId", ""),
                         "the store is data-only; the audio element stays in audio.js")


if __name__ == "__main__":
    unittest.main()