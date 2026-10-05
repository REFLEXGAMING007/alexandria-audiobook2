"""Voices V2 assignment editor: the draft, the save, and the refusals.

The behaviours worth gating are the ones where a mistake loses a user's work or
writes something they did not intend:

  - choosing a voice creates a draft and writes nothing;
  - the draft is compared against what is stored rather than remembered, so
    "unsaved changes" cannot drift from reality;
  - Save sends exactly one command carrying the revision and book token the
    projection was read with;
  - a second Save cannot be issued while one is in flight;
  - a conflict keeps the draft, says what happened, and offers a way forward that
    is not a silent retry;
  - switching characters with a dirty draft is refused, and the three ways out are
    all explicit.

These run through the same node + vm harness as the Phase 1 tests, so the two
modules cannot disagree about what exists.
"""
import sys
import unittest
from pathlib import Path

from tests.test_voices_v2_isolation import (_HARNESS, _NodeTestCase, V2_DIR,
                                             V2_FILES as V2_FILE_ORDER,
                                             strip_js_comments)


# Mirrors V2_FILES in test_voices_v2_isolation.py, which is the one place the
# load order is declared, so the harness cannot fall behind the page.
V2_FILES = list(V2_FILE_ORDER)

#: One character with a catalogue voice already saved, one with none, one orphan.
PAYLOAD = r"""
payload={
  schema_version:1, revision:'rev-1',
  book:{book_id:'Book',token:'tok-1',script_sha256:'sha',script_present:true},
  traits_available:true, traits_requested:true, aliases_registered:true, major_line_threshold:25,
  vocabularies:{genders:['male','female','unknown'],
    age_groups:[{value:'adult',label:'30-39'}],problem_codes:['voice_unassigned']},
  characters:[
    {key:'mira',name:'MIRA',identity_key:'mira',library_key:'mira',present_in_script:true,
     generic:false,line_count:40,priority:'major',known_as:[],aliases:[],ready:true,
     voice:{category:'lora',type:'lora',catalogue_voice_id:'lora:current',label:'current_voice',
       assigned:true,adapter_id:'current',adapter_available:true,has_ref_audio:false,
       ref_audio_present:null,has_description:false,seed:null,alias_of:null,ensemble_members:0},
     voice_status:'assigned',persona_status:'generated',persona_ref:null,persona_ref_resolves:null,
     active_version:null,versions:[],version_timeline:[],candidate_count:0,
     traits:{gender:'female',age_group:'adult',ageless:false,lines:40,
       current:{gender:'female',age_group:'adult'},states:[]},
     traits_available:true,states:[],possible_duplicate_of:[],problems:[]},
    {key:'ryan',name:'RYAN',identity_key:'ryan',library_key:'ryan',present_in_script:true,
     generic:false,line_count:4,priority:'minor',known_as:[],aliases:[],ready:false,
     voice:{category:'custom',type:'custom',catalogue_voice_id:null,label:'No voice',
       assigned:false,adapter_id:null,adapter_available:null,has_ref_audio:false,
       ref_audio_present:null,has_description:false,seed:null,alias_of:null,ensemble_members:0},
     voice_status:'unassigned',persona_status:'unreviewed',persona_ref:null,
     persona_ref_resolves:null,active_version:null,versions:[],version_timeline:[],
     candidate_count:0,traits:{gender:'male',age_group:'adult',ageless:false,lines:4,
       current:{gender:'male',age_group:'adult'},states:[]},
     traits_available:true,states:[],possible_duplicate_of:[],problems:['voice_unassigned']}],
  orphans:[],
  counts:{characters:2,orphans:0}};

const CATALOGUE={voices:[
    {voice_id:'lora:current',kind:'lora',name:'current_voice',description:'the saved one',
     gender:null,favorite:true,available:true,unavailable_reason:''},
    {voice_id:'lora:other',kind:'lora',name:'other_voice',description:'an alternative',
     gender:null,favorite:false,available:true,unavailable_reason:''},
    {voice_id:'design:narrator',kind:'design',name:'NARRATOR',description:'a calm narrator',
     gender:null,favorite:false,available:true,unavailable_reason:''},
    {voice_id:'lora:broken',kind:'lora',name:'broken_voice',description:'missing on disk',
     gender:null,favorite:false,available:false,unavailable_reason:'not on disk'}],
  counts:{total:4,available:3,unavailable:1},
  kinds:['lora','builtin_lora','clone','design'],unsupported_kinds:{}};
"""


class AssignmentBrowserTestCase(_NodeTestCase):
    """Mounts Voices V2 with a projection and a catalogue already in flight."""

    MOUNT = r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();await turn();"""

    def run_mounted(self, body, mount_extra=""):
        """Run `body` with Voices V2 mounted, a projection and a catalogue served.

        The shared harness stubs one `API.get`; this adds a command channel and a
        second payload so the editor's own requests can be observed and refused
        on demand, which is the only way to test a conflict without a backend.
        """
        import subprocess

        setup = _HARNESS % {"files": repr(V2_FILES)}
        # The payloads must sit at the top level of the eval script: the API
        # override is an outer-realm closure, so it cannot see anything declared
        # inside the async body.
        prologue = (
            PAYLOAD
            + "\nconst _v2get=API.get;"
            "\nAPI.get=function(path){"
            "  if(path==='/api/voices-v2/voices')"
            "    return Promise.resolve(JSON.parse(JSON.stringify(CATALOGUE)));"
            "  return _v2get(path);"
            "};"
            "\nconst commandCalls=[];"
            "\nlet commandMode='ok',commandPayload=null;"
            "\nAPI.post=function(path,body){"
            "  if(path!=='/api/voices-v2/command')"
            "    return Promise.reject(Error('unexpected '+path));"
            "  commandCalls.push(JSON.parse(JSON.stringify(body)));"
            "  if(commandMode==='reject')return Promise.reject(commandPayload);"
            "  if(commandMode==='hold')"
            "    return new Promise(function(res){commandPayload=function(){res({status:'saved'});};});"
            "  return Promise.resolve({status:'saved',character:body.character,"
            "    voice_id:body.voice_id,revision:'rev-2',book_token:body.book_token});"
            "};"
            "\nlet done=false;"
            "\nprocess.on('beforeExit',function(){assert(done,'assertions must finish');});"
            "\n(async()=>{\nloadAll();\n" + self.MOUNT + mount_extra
            + "\n" + body + "\ndone=true;\n})()"
            ".catch(function(e){console.error(e);process.exitCode=1;});"
        )
        result = subprocess.run(["node", "-e", setup + prologue, str(V2_DIR)],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout


class DraftTests(AssignmentBrowserTestCase):
    def test_the_editor_shows_the_voice_that_is_already_stored(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
const html=node('voice-editor').innerHTML;
assert(html.includes('Saved now: current_voice'),html);
assert(html.includes('current_voice'));
assert(html.includes('value="lora:current" selected'),'the saved voice is selected');
assert(html.includes('Choose a different voice to enable Save'),'nothing to save yet');
""")

    def test_a_character_with_no_voice_says_so(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
assert(node('voice-editor').innerHTML.includes('Saved now: no voice'));
""")

    def test_choosing_a_voice_creates_a_draft_and_writes_nothing(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
const state=V2.getState();
assert.strictEqual(state.draft.voiceId,'lora:other');
assert.strictEqual(state.draft.dirty,true);
assert.strictEqual(state.draft.characterKey,'mira');
assert.deepStrictEqual(commandCalls,[],'choosing a voice must not write');
const html=node('voice-editor').innerHTML;
assert(html.includes('Unsaved change. Nothing is written until you press Save'),html);
assert(html.includes('value="lora:other" selected'));
assert(html.includes('Saved now: current_voice'),'the stored voice stays visible');
""")

    def test_choosing_the_stored_voice_again_is_not_a_change(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:current'});
assert.strictEqual(V2.canSaveVoice(V2.getState()),false,
  'the draft equals what is stored, so there is nothing to save');
""")

    def test_clear_is_a_draft_and_needs_saving(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/clearVoice'});
await turn();
assert.strictEqual(V2.getState().draft.cleared,true);
assert.strictEqual(V2.getState().draft.voiceId,null);
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'idle');
assert.deepStrictEqual(commandCalls,[],'clearing must not write on its own');
assert(V2.canSaveVoice(V2.getState()));
""")

    def test_clearing_a_character_that_has_no_voice_is_not_a_change(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
V2.dispatch({type:'draft/clearVoice'});
assert.strictEqual(V2.canSaveVoice(V2.getState()),false);
""")

    def test_discard_returns_to_the_stored_voice(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'design:narrator'});
await turn();
assert.strictEqual(V2.getState().draft.dirty,true);
V2.dispatch({type:'draft/discard'});
await turn();
assert.strictEqual(V2.getState().draft.dirty,false);
assert.strictEqual(V2.voiceDraft(V2.getState()).voiceId,'lora:current',
  'the draft falls back to the character\'s own stored voice');
""")

    def test_the_draft_is_derived_from_the_character_not_remembered(self):
        """A draft left from another character is never shown for this one."""
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
V2.dispatch({type:'draft/discard'});
V2.dispatch({type:'selection/set',key:'ryan'});
const draft=V2.voiceDraft(V2.getState());
assert.strictEqual(draft.characterKey,'ryan');
assert.strictEqual(draft.dirty,false);
assert.strictEqual(draft.voiceId,null,'RYAN has no catalogue voice');
""")

    def test_a_draft_needs_a_selected_character(self):
        self.run_mounted(r"""
assert.throws(()=>V2.dispatch({type:'draft/choose',voiceId:'lora:other'}),
  /no character selected/);
""")

    def test_an_unavailable_voice_is_offered_but_cannot_be_chosen(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
const html=node('voice-editor').innerHTML;
assert(html.includes('value="lora:broken" disabled'),'an unavailable voice is disabled');
assert(html.includes('broken_voice'),'it is still listed, with its reason');
assert(html.includes('not on disk'));
""")

    def test_a_voice_not_in_the_catalogue_is_reported_not_silently_replaced(self):
        self.run_mounted(r"""
payload.characters[1].voice.catalogue_voice_id=null;
payload.characters[1].voice.label='vanished_voice';
payload.characters[1].voice.assigned=true;
V2.lifecycle.applyPayload(payload);
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
const html=node('voice-editor').innerHTML;
assert(html.includes('is not in the Voices V2 catalogue'),html);
assert(html.includes('vanished_voice'));
assert(html.includes('left exactly as stored'));
""")

    def test_the_editor_groups_the_catalogue_by_family(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
const html=node('voice-editor').innerHTML;
assert(html.includes('<optgroup label="Trained LoRA voices">'),html);
assert(html.includes('<optgroup label="Designed voices">'));
assert(html.indexOf('Trained LoRA voices')<html.indexOf('Designed voices'));
""")

    def test_a_catalogue_failure_is_reported_inside_the_editor_not_as_a_tab_error(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
API.get=()=>Promise.reject(Object.assign(Error('boom'),{status:500,detail:'gone'}));
await V2.lifecycle.loadCatalogue();
await turn();
assert.strictEqual(V2.getState().catalogue.error!==null,true);
assert.strictEqual(V2.getState().ui.error,null,
  'a missing voice list must not make the whole tab look broken');
assert(node('voice-editor').innerHTML.includes('alert-danger'));
""")


class SaveTests(AssignmentBrowserTestCase):
    def test_save_sends_the_revision_and_token_the_projection_was_read_with(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
await V2.panels.assignmentPanel.save();
assert.strictEqual(commandCalls.length,1,commandCalls);
assert.deepStrictEqual(Object.keys(commandCalls[0]).sort(),['book_token','character','command','revision','voice_id']);
assert.strictEqual(commandCalls[0].command,'assign');
assert.strictEqual(commandCalls[0].character,'mira');
assert.strictEqual(commandCalls[0].voice_id,'lora:other');
assert.strictEqual(commandCalls[0].revision,'rev-1');
assert.strictEqual(commandCalls[0].book_token,'tok-1');
""")

    def test_save_clears_the_draft_and_reports_success(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
await V2.panels.assignmentPanel.save();
await turn();
const state=V2.getState();
assert.strictEqual(state.save.state,'saved');
assert.strictEqual(state.draft.dirty,false,'the draft is forgotten after a successful save');
assert.strictEqual(state.selection.key,'mira','the selection survives');
const html=node('voice-editor').innerHTML;
assert(html.includes('Voice saved'),html);
assert.strictEqual(node('live').textContent,'2 of 2 characters, voice saved');
""")

    def test_a_successful_save_re_reads_the_projection(self):
        self.run_mounted(r"""
const before=characterCalls().length;
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await V2.panels.assignmentPanel.save();
assert.strictEqual(characterCalls().length,before+1,
  'the projection is re-read so the view shows what is stored');
""")

    def test_a_save_with_nothing_to_save_issues_no_request(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
assert.strictEqual(await V2.panels.assignmentPanel.save(),false);
assert.deepStrictEqual(commandCalls,[]);
""")

    def test_a_save_without_tokens_is_refused_rather_than_guessed(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.getState().meta.revision=null;
assert.strictEqual(await V2.panels.assignmentPanel.save(),false);
assert.deepStrictEqual(commandCalls,[]);
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'error');
assert(node('voice-editor').innerHTML.includes('has not loaded the save token'));
""")

    def test_a_second_save_cannot_be_issued_while_one_is_in_flight(self):
        self.run_mounted(r"""
commandMode='hold';
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
const first=V2.panels.assignmentPanel.save();
const second=V2.panels.assignmentPanel.save();
const third=V2.panels.assignmentPanel.save();
assert.strictEqual(first,second,'a save in flight is reused, not restarted');
assert.strictEqual(second,third);
assert.strictEqual(commandCalls.length,1,'duplicate clicks must not issue duplicate writes');
assert.strictEqual(V2.canSaveVoice(V2.getState()),false,'Save is disabled while saving');
await turn();
assert(node('voice-editor').innerHTML.includes('Saving the voice change'));
assert(node('voice-editor').innerHTML.includes('data-voicesv2-action="save-voice" disabled'),
  'the button is disabled while a save is in flight');
commandPayload();await first;
""")

    def test_a_clear_is_sent_as_a_clear_command(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/clearVoice'});
await turn();
await V2.panels.assignmentPanel.save();
assert.strictEqual(commandCalls.length,1);
assert.strictEqual(commandCalls[0].command,'clear');
assert.strictEqual(commandCalls[0].voice_id,null);
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'saved');
""")


class ConflictTests(AssignmentBrowserTestCase):
    def _conflict(self, code="stale_snapshot"):
        return r"""
commandMode='reject';
commandPayload=Object.assign(Error('Voice configuration changed; reload it before saving'),
  {status:409,detail:{code:'stale_snapshot',message:'Voice configuration changed; reload it before saving'}});
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
await V2.panels.assignmentPanel.save();
await turn();"""

    def test_a_conflict_is_reported_and_the_draft_is_kept(self):
        self.run_mounted(self._conflict() + r"""
const state=V2.getState();
assert.strictEqual(state.save.state,'conflict');
assert.strictEqual(state.save.code,'stale_snapshot');
assert.strictEqual(state.draft.dirty,true,'the draft survives a refusal');
assert.strictEqual(state.draft.voiceId,'lora:other');
const html=node('voice-editor').innerHTML;
assert(html.includes('This change was not saved'),html);
assert(html.includes('Your choice is still selected'),html);
assert(html.includes('value="lora:other" selected'),'the chosen voice is still shown');
assert.strictEqual(node('live').textContent,'2 of 2 characters, voice change not saved');
""")

    def test_a_conflict_offers_a_refresh_and_not_a_silent_retry(self):
        self.run_mounted(self._conflict() + r"""
const html=node('voice-editor').innerHTML;
assert(html.includes('data-voicesv2-action="reload-latest"'),html);
assert.strictEqual(commandCalls.length,1,'a conflict must not be retried automatically');
/* The button lives inside the editor region, which owns it; the root's delegated
   handler deliberately does not know this action. */
node('voice-editor').fire('click',{target:actionButton('reload-latest')});
await turn();await turn();await turn();
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'idle');
assert(characterCalls().length>=2,'refreshing re-reads the projection');
assert.strictEqual(commandCalls.length,1,'refreshing must not write');
""")

    def test_a_voice_refused_with_409_is_a_conflict_not_a_save_error(self):
        self.run_mounted(r"""
commandMode='reject';
commandPayload=Object.assign(Error('gone'),{status:409,
  detail:{code:'character_no_longer_present',message:'That character is no longer in this book.'}});
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await V2.panels.assignmentPanel.save();await turn();
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'conflict');
assert.strictEqual(V2.voiceSaveState(V2.getState()).code,'character_no_longer_present');
""")

    def test_a_non_conflict_refusal_is_an_error_with_its_own_message(self):
        self.run_mounted(r"""
commandMode='reject';
commandPayload=Object.assign(Error('bad'),{status:400,
  detail:{code:'voice_unavailable',message:'That voice cannot be assigned: not on disk.'}});
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await V2.panels.assignmentPanel.save();await turn();
const state=V2.voiceSaveState(V2.getState());
assert.strictEqual(state.state,'error');
assert.strictEqual(state.code,'voice_unavailable');
assert(node('voice-editor').innerHTML.includes('not on disk'),node('voice-editor').innerHTML);
""")

    def test_a_network_failure_is_reported_and_the_draft_is_kept(self):
        self.run_mounted(r"""
commandMode='reject';
commandPayload=Object.assign(Error('offline'),{status:0,message:'offline'});
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await V2.panels.assignmentPanel.save();await turn();
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'error');
assert.strictEqual(V2.getState().draft.dirty,true);
assert(node('voice-editor').innerHTML.includes('The voice could not be saved'));
""")


class NavigationGuardTests(AssignmentBrowserTestCase):
    def test_switching_characters_with_a_dirty_draft_is_refused(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
const state=V2.getState();
assert.strictEqual(state.selection.key,'mira','the selection did not move');
assert.strictEqual(state.selection.blocked,true);
assert.strictEqual(state.selection.pending,'ryan');
assert.strictEqual(state.draft.voiceId,'lora:other','the draft is intact');
const html=status.innerHTML;
assert(html.includes('unsaved voice change for MIRA'),html);
assert(html.includes('Switching to RYAN would discard it'));
""")

    def test_stay_leaves_the_draft_and_the_selection_alone(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
root.fire('click',{target:actionButton('cancel-switch')});
await turn();
const state=V2.getState();
assert.strictEqual(state.selection.key,'mira');
assert.strictEqual(state.selection.blocked,false);
assert.strictEqual(state.draft.voiceId,'lora:other','stay must not discard anything');
assert(!status.innerHTML.includes('would discard it'));
""")

    def test_discard_and_switch_accepts_the_switch_and_forgets_the_draft(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
root.fire('click',{target:actionButton('discard-and-switch')});
await turn();
const state=V2.getState();
assert.strictEqual(state.selection.key,'ryan');
assert.strictEqual(state.selection.blocked,false);
assert.strictEqual(state.draft.dirty,false);
assert.strictEqual(state.save.state,'idle');
assert.deepStrictEqual(commandCalls,[],'discarding writes nothing');
""")

    def test_save_and_switch_saves_first_and_switches_only_on_success(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
root.fire('click',{target:actionButton('save-and-switch')});
await turn();await turn();await turn();
assert.strictEqual(commandCalls.length,1);
assert.strictEqual(V2.getState().selection.key,'ryan',
  'the blocked switch completes once the write succeeded');
assert.strictEqual(V2.getState().draft.dirty,false);
""")

    def test_a_blocked_switch_stays_blocked_when_the_save_fails(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'draft/choose',voiceId:'lora:other'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
commandMode='reject';
commandPayload=Object.assign(Error('stale'),{status:409,detail:{code:'stale_snapshot',message:'stale'}});
root.fire('click',{target:actionButton('save-and-switch')});
await turn();await turn();await turn();
const state=V2.getState();
assert.strictEqual(state.selection.key,'mira','a failed save must not switch away');
assert.strictEqual(state.selection.blocked,true,'the choice is still pending');
assert.strictEqual(state.save.state,'conflict');
assert.strictEqual(state.draft.voiceId,'lora:other');
""")

    def test_switching_with_a_clean_draft_is_not_blocked(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
const state=V2.getState();
assert.strictEqual(state.selection.key,'ryan');
assert.strictEqual(state.selection.blocked,false);
assert(!status.innerHTML.includes('would discard it'));
""")


class EditorClickTests(AssignmentBrowserTestCase):
    def test_the_editor_binds_its_listeners_once_despite_repeated_renders(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
for(const query of ['lora:other','design:narrator','lora:current']){
  V2.dispatch({type:'draft/choose',voiceId:query});
  await turn();
}
assert.strictEqual((node('voice-editor').listeners.change||[]).length,1);
assert.strictEqual((node('voice-editor').listeners.click||[]).length,1);
""")

    def test_unmount_detaches_the_editor(self):
        self.run_mounted(r"""
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
assert.strictEqual(V2.panels.assignmentPanel.isSaving(),false);
V2.unmount();
V2.dispatch({type:'selection/set',key:'ryan'});
assert.strictEqual(V2.canSaveVoice(V2.getState()),false,'an unmounted editor does not save');
""", mount_extra="assert((node('voice-editor').listeners.click||[]).length===1);")


class SourceBoundaryTests(unittest.TestCase):
    """The write path goes through the V2 boundary and nowhere else."""

    def _code(self, name):
        return strip_js_comments((V2_DIR / name).read_text(encoding="utf-8"))

    def test_only_api_module_names_a_url_and_only_it_posts(self):
        for name in V2_FILES:
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("fetch(", code, f"{name} must use the shared API helper")
                self.assertNotIn("XMLHttpRequest", code)
                if name != "api.js":
                    self.assertNotIn("/api/", code,
                                     f"{name} must not name a Voices V2 URL")

    def test_the_assignment_panel_reads_the_save_tokens_and_never_derives_them(self):
        """The panel is allowed to present the revision it was given and nothing
        more: it must not compute one, hash anything, or reach for the file."""
        panel = self._code("panels/assignment.js")
        self.assertIn("current.meta.revision", panel,
                      "the panel presents the revision the projection carried")
        self.assertIn("current.meta.book.token", panel)
        # It must hand the tokens to api.sendCommand, so naming them is
        # required; what it must never do is derive, hash or persist them.
        self.assertIn("api.sendCommand(", panel,
                      "the panel must reach the server through the V2 boundary")
        for banned in ("file_lock", "createHash", "crypto", "sha256(", "digest(",
                       "localStorage", "atomic_json"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, panel,
                                 f"the panel must not produce {banned}")

    def test_the_store_validates_every_save_state_it_accepts(self):
        code = self._code("state.js")
        self.assertIn("SAVE_STATES", code)
        for command in ("draft/choose", "draft/clearVoice", "draft/discard", "save/start",
                        "save/succeeded", "save/failed", "save/conflict", "selection/set",
                        "selection/acceptPending", "selection/cancelPending"):
            with self.subTest(command=command):
                self.assertIn(f"'{command}'", code)


if __name__ == "__main__":
    unittest.main()