"""Voices V2 Voice Library: search, filters, sorting, navigation and handoff.

The behaviours gated here are the ones where a mistake is invisible until a user
loses work or misreads the data:

  - multi-term search is AND across fields, so "female warm" finds a voice whose
    terms sit in different fields;
  - a filter chip removes exactly one filter, and clear-all resets all of them;
  - Previous/Next and the dice stay inside the *filtered* set, so navigation can
    never land on something the user excluded;
  - provenance is visible on the card, so an inferred gender cannot be mistaken
    for a stated one;
  - choosing a voice writes a *draft* through Phase 2's command and never saves;
  - context is a suggestion that can be removed, and never hides a voice whose
    metadata is unknown;
  - favourites are not optimistic, so a refused write leaves the star put.
"""
import subprocess
import sys
import unittest

from tests.test_voices_v2_isolation import _HARNESS, _NodeTestCase, V2_DIR
from tests.test_voices_v2_isolation import V2_FILES as V2_FILE_ORDER
from tests.test_voices_v2_isolation import strip_js_comments


#: A catalogue covering every axis the library filters on, plus the awkward
#: cases: inferred metadata, unknown metadata, unavailable files, no preview, and
#: a voice with no stated date.
CATALOGUE = r"""
const CATALOGUE={schema_version:1,voices:[
  {voice_id:'lora:alto',native_id:'alto',kind:'lora',name:'alto',label:'alto',
   source:'Trained LoRA',realisation:'adapter',description:'A warm alto with plenty of breath',
   sample_text:null,gender:'female',gender_source:'inferred',age_group:'young_adult',
   age_group_source:'inferred',added_at:1700000000,availability:'unavailable',available:false,
   unavailable_reason:'The adapter files are not on disk.',downloaded:true,favorite:true,
   favorite_supported:true,adapter_id:'alto',adapter_path:'lora_models/alto',ref_audio:null,
   ref_text:null,preview_capable:false,preview_url:null,preview_kind:null,tags:[],
   metadata:{epochs:12}},
  {voice_id:'lora:baritone',native_id:'baritone',kind:'lora',name:'baritone',label:'baritone',
   source:'Trained LoRA',realisation:'adapter',description:'A dry baritone for older men',
   sample_text:null,gender:'male',gender_source:'declared',age_group:'middle_aged',
   age_group_source:'inferred',added_at:1600000000,availability:'available',available:true,
   unavailable_reason:'',downloaded:true,favorite:false,favorite_supported:true,
   adapter_id:'baritone',adapter_path:'lora_models/baritone',ref_audio:null,ref_text:null,
   preview_capable:true,preview_url:'/lora_models/baritone/preview_sample.wav',
   preview_kind:'recording',tags:[],metadata:{epochs:20}},
  {voice_id:'lora:mystery',native_id:'mystery',kind:'lora',name:'mystery',label:'mystery',
   source:'Trained LoRA',realisation:'adapter',description:'No useful description here',
   sample_text:null,gender:'unknown',gender_source:'unknown',age_group:'unknown',
   age_group_source:'unknown',added_at:null,availability:'available',available:true,
   unavailable_reason:'',downloaded:true,favorite:false,favorite_supported:true,
   adapter_id:'mystery',adapter_path:'lora_models/mystery',ref_audio:null,ref_text:null,
   preview_capable:false,preview_url:null,preview_kind:null,tags:[],metadata:{}},
  {voice_id:'builtin:watson',native_id:'watson',kind:'builtin_lora',name:'watson',
   label:'watson',source:'Built-in LoRA',realisation:'adapter',
   description:'A measured narrator voice',sample_text:null,gender:'male',
   gender_source:'declared',age_group:'adult',age_group_source:'unknown',added_at:null,
   availability:'unavailable',available:false,unavailable_reason:'Not downloaded.',
   downloaded:false,favorite:false,favorite_supported:true,adapter_id:'watson',
   adapter_path:'builtin_lora/watson',ref_audio:null,ref_text:null,preview_capable:false,
   preview_url:null,preview_kind:null,tags:[],metadata:{}},
  {voice_id:'clone:clip',native_id:'clip',kind:'clone',name:'A clip',label:'A clip',
   source:'Uploaded clone',realisation:'clone_recording',
   description:'the exact words spoken in the clip',sample_text:'the exact words spoken',
   gender:'unknown',gender_source:'unknown',age_group:'unknown',age_group_source:'unknown',
   added_at:1650000000,availability:'available',available:true,unavailable_reason:'',
   downloaded:true,favorite:false,favorite_supported:false,adapter_id:null,adapter_path:null,
   ref_audio:'clone_voices/clip.wav',ref_text:'the exact words',preview_capable:true,
   preview_url:'/clone_voices/clip.wav',preview_kind:'recording',tags:[],metadata:{}},
  {voice_id:'design:narrator',native_id:'narrator',kind:'design',name:'NARRATOR',
   label:'NARRATOR',source:'Designed voice',realisation:'description',
   description:'A calm measured narrator of unspecified gender',sample_text:'Once upon a time.',
   gender:'unknown',gender_source:'unknown',age_group:'unknown',age_group_source:'unknown',
   added_at:null,availability:'available',available:true,unavailable_reason:'',
   downloaded:true,favorite:false,favorite_supported:false,adapter_id:null,
   adapter_path:null,ref_audio:'designed_voices/narrator.wav',ref_text:null,
   preview_capable:true,preview_url:'/designed_voices/narrator.wav',preview_kind:'recording',
   tags:[],metadata:{}}],
 counts:{total:6,available:4,unavailable:2},kinds:['lora','builtin_lora','clone','design'],
 favorite_kinds:['lora','builtin_lora'],warnings:[],unsupported_kinds:{}};"""


PROJECTION = r"""
const PROJECTION={meta:{
  schemaVersion:1,revision:'rev-1',
  book:{bookId:'Book',token:'tok-1',scriptSha256:'sha',scriptPresent:true},
  traitsAvailable:true,traitsRequested:true,aliasesRegistered:true,majorLineThreshold:25,
  vocabularies:{genders:['male','female','unknown'],
    ageGroups:[{value:'adult',label:'30-39'},{value:'middle_aged',label:'40-59'}],
    problemCodes:['voice_unassigned']}},
 characters:[
    {key:'mira',name:'MIRA',identityKey:'mira',libraryKey:'mira',presentInScript:true,
     generic:false,lineCount:40,priority:'major',knownAs:[],aliases:[],ready:true,
     voice:{category:'lora',type:'lora',catalogueVoiceId:'lora:baritone',label:'baritone',
       assigned:true,adapterId:'baritone',adapterAvailable:true,hasRefAudio:false,
       refAudioPresent:null,hasDescription:false,seed:null,aliasOf:null,ensembleMembers:0},
     voiceStatus:'assigned',personaStatus:'generated',personaRef:null,personaRefResolves:null,
     activeVersion:null,versions:[],versionTimeline:[],candidateCount:0,
     traits:{gender:'female',ageGroup:'adult',ageless:false,lines:40,
       current:{gender:'female',ageGroup:'adult'},states:[]},
     traitsAvailable:true,states:[],possibleDuplicateOf:[],problems:[]},
    {key:'ryan',name:'RYAN',identityKey:'ryan',libraryKey:'ryan',presentInScript:true,
     generic:false,lineCount:4,priority:'minor',knownAs:[],aliases:[],ready:false,
     voice:{category:'custom',type:'custom',catalogueVoiceId:null,label:'No voice',
       assigned:false,adapterId:null,adapterAvailable:null,hasRefAudio:false,
       refAudioPresent:null,hasDescription:false,seed:null,aliasOf:null,ensembleMembers:0},
     voiceStatus:'unassigned',personaStatus:'unreviewed',personaRef:null,personaRefResolves:null,
     activeVersion:null,versions:[],versionTimeline:[],candidateCount:0,
     traits:{gender:'male',ageGroup:'middle_aged',ageless:false,lines:4,
       current:{gender:'male',ageGroup:'middle_aged'},states:[]},
     traitsAvailable:true,states:[],possibleDuplicateOf:[],problems:['voice_unassigned']}],
 orphans:[]};

/* A second projection for the one context case that needs different traits. */
const PROJECTION_MIRA_AGELESS=JSON.parse(JSON.stringify(PROJECTION));
PROJECTION_MIRA_AGELESS.characters[0].traits.ageless=true;"""


class LibraryTestCase(_NodeTestCase):
    """Mounts Voices V2 with a projection and a catalogue already loaded."""

    def run_library(self, setup, body="", projection="PROJECTION"):
        """Run `setup` then `body` in one node process.

        The two are separate because most tests need a little arranging (open
        the library, choose a voice) before they can assert, and the arranging is
        usually identical across a class.
        """
        harness = _HARNESS % {"files": repr(list(V2_FILE_ORDER))}
        prologue = (
            CATALOGUE + PROJECTION
            + "\nconst _v2get=API.get;"
            "\nAPI.get=function(path){"
            "  if(path==='/api/voices-v2/voices')"
            "    return Promise.resolve(JSON.parse(JSON.stringify(CATALOGUE)));"
            "  return _v2get(path);"
            "};"
            "\nconst favoriteCalls=[],commandCalls=[];let favoriteMode='ok',favoriteResult=null;"
            "\nAPI.post=function(path,body){"
            "  if(path==='/api/voices-v2/favorite'){"
            "    favoriteCalls.push(JSON.parse(JSON.stringify(body)));"
            "    if(favoriteMode==='reject')return Promise.reject(Object.assign(Error('no'),"
            "      {status:409,detail:{code:'favorite_unsupported',message:'nope'}}));"
            "    const next=Object.assign({},CATALOGUE,{favorites:(favoriteResult||[])});"
            "    return Promise.resolve({voice_id:body.voice_id,favorite:body.favorite,"
            "      favorites:(favoriteResult||[])});"
            "  }"
            "  if(path!=='/api/voices-v2/command')"
            "    return Promise.reject(Error('unexpected '+path));"
            "  commandCalls.push(JSON.parse(JSON.stringify(body)));"
            "  return Promise.resolve({status:'saved',character:body.character,"
            "    voice_id:body.voice_id});"
            "};"
            "\nlet done=false;"
            "\nprocess.on('beforeExit',function(){assert(done,'assertions must finish');});"
            "\n(async()=>{\nloadAll();\n"
            "const V2=ctx.window.VoicesV2;\n"
            "await V2.mount();await turn();await turn();\n"
            "V2.dispatch({type:'meta/set',meta:%s.meta});\n"
            "V2.dispatch({type:'characters/set',characters:%s.characters});\n"
            "V2.dispatch({type:'orphans/set',orphans:%s.orphans});await turn();\n"
            % (projection, projection, projection) +
            "V2.dispatch({type:'selection/set',key:'mira'});await turn();\n"
            "function setControl(name,value,type){const el=node(name);el.value=value;"
            "  node('library').fire(type,{target:el});}\n"
            + setup + "\n" + body
            + "\ndone=true;\n})().catch(function(e){console.error(e);process.exitCode=1;});"
        )
        result = subprocess.run(["node", "-e", harness + prologue, str(V2_DIR)],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    # In a real DOM the controls are descendants of the panel, so their events
    # bubble to the delegated listener. The fake nodes are detached, so the same
    # thing is modelled by firing on the panel with the control as the target.
    FIRED = ("node('library').fire(%s,{target:%s});")

    def lib(self, setup, body=""):
        return self.run_library("V2.library." + setup + ";\n" + body)


class SearchTests(LibraryTestCase):
    def test_an_empty_query_shows_every_voice(self):
        self.lib("open(null)", "assert.strictEqual(V2.libraryVoices(V2.getState()).length,6);")

    def test_search_matches_the_name(self):
        self.lib("open(null);V2.library.panel.setSearch('baritone');",
                 "assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),"
                 "['lora:baritone']);")

    def test_search_matches_a_description_phrase(self):
        self.lib("open(null);V2.library.panel.setSearch('plenty of breath');",
                 "assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),"
                 "['lora:alto']);")

    def test_search_matches_the_family_and_gender(self):
        self.lib("open(null);V2.library.panel.setSearch('built-in lora');",
                 "assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),"
                 "['builtin:watson']);")
        self.lib("open(null);V2.library.panel.setSearch('unknown');",
                 "assert(V2.libraryVoices(V2.getState()).length>=1);")

    def test_search_is_multi_term_and_across_field_boundaries(self):
        """'female warm' has to find the voice whose gender is one word and whose
        description holds the other."""
        self.lib("open(null);V2.library.panel.setSearch('female warm');",
                 "assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),"
                 "['lora:alto']);")

    def test_every_term_must_match_somewhere(self):
        self.lib("open(null);V2.library.panel.setSearch('female baritone');",
                 "assert.strictEqual(V2.libraryVoices(V2.getState()).length,0,"
                 "'two characters each holding one term is not a match');")

    def test_search_is_case_and_whitespace_insensitive(self):
        self.lib("open(null);V2.library.panel.setSearch('   BARITONE   ');",
                 "assert.strictEqual(V2.libraryVoices(V2.getState()).length,1);")

    def test_search_terms_do_not_need_to_respect_word_boundaries(self):
        self.lib("open(null);V2.library.panel.setSearch('ariton');",
                 "assert.strictEqual(V2.libraryVoices(V2.getState()).length,1);")


class FilterTests(LibraryTestCase):
    def open_library(self, extra=""):
        return "V2.library.open(null);await turn();" + extra

    def test_each_filter_narrows_the_result_set(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const one=(patch)=>{V2.dispatch({type:'library/resetFilters'});
  V2.dispatch({type:'library/filters',patch:patch});
  return plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));};
assert.deepStrictEqual(one({gender:'male'}).sort(),['builtin:watson','lora:baritone']);
assert.deepStrictEqual(one({ageGroup:'middle_aged'}).sort(),['lora:baritone']);
assert.deepStrictEqual(one({kind:'clone'}),['clone:clip']);
assert.deepStrictEqual(one({kind:'design'}),['design:narrator']);
assert.deepStrictEqual(one({availability:'available'}).sort(),
  ['clone:clip','design:narrator','lora:baritone','lora:mystery']);
assert.deepStrictEqual(one({availability:'unavailable'}).sort(),
  ['builtin:watson','lora:alto']);
assert.deepStrictEqual(one({favorite:true}),['lora:alto']);
""")

    def test_unknown_gender_and_age_are_selectable_filters(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.dispatch({type:'library/filters',patch:{gender:'unknown',ageGroup:'unknown'}});
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert.deepStrictEqual(shown.sort(),['clone:clip','design:narrator','lora:mystery'],
  'a voice with no stated traits must be reachable, not hidden');
""")

    def test_filters_combine(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.dispatch({type:'library/filters',patch:{gender:'male',availability:'available'}});
assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),
  ['lora:baritone']);
""")

    def test_a_chip_appears_for_each_active_filter_and_removes_only_itself(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.dispatch({type:'library/filters',patch:{gender:'male',favorite:true}});
let chips=V2.library.filters.selectChips(V2.getState());
assert.strictEqual(chips.length,2,JSON.stringify(chips));
assert.deepStrictEqual(plain(chips.map(c=>c.key).sort()),['favorite','gender']);
assert(chips.some(c=>c.label.indexOf('Male')>=0),'a chip names its own value');
V2.library.panel.removeFilter('gender');
chips=V2.library.filters.selectChips(V2.getState());
assert.deepStrictEqual(plain(chips.map(c=>c.key)),['favorite']);
assert.strictEqual(V2.getState().libraryFilters.gender,'all','only that filter moved');
assert.strictEqual(V2.getState().libraryFilters.favorite,true,'the other survived');
""")

    def test_clearing_the_filters_resets_the_search_too(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.library.panel.setSearch('alto');
V2.dispatch({type:'library/filters',patch:{kind:'clone'}});
V2.library.panel.clearFilters();
const filters=V2.getState().libraryFilters;
assert.strictEqual(filters.kind,'all');
assert.strictEqual(filters.gender,'all');
assert.strictEqual(filters.favorite,false);
assert.strictEqual(V2.getState().librarySearch,'');
assert.strictEqual(V2.libraryVoices(V2.getState()).length,6);
""")

    def test_an_unknown_filter_or_value_is_refused(self):
        self.run_library("V2.library.open(null);await turn();", r"""
assert.throws(()=>V2.dispatch({type:'library/filters',patch:{colour:'red'}}),
  /no library filter named/);
assert.throws(()=>V2.dispatch({type:'library/filters',patch:{availability:'maybe'}}),
  /does not accept/);
assert.throws(()=>V2.dispatch({type:'library/filters',patch:{favorite:'yes'}}),
  /needs a boolean/);
assert.strictEqual(V2.getState().libraryFilters.availability,'all','a refusal changes nothing');
""")

    def test_the_chips_are_rendered_with_a_removable_control(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.dispatch({type:'library/filters',patch:{kind:'clone'}});
await turn();
const chips=node('library-chips').innerHTML;
assert(chips.includes('data-voicesv2-action="remove-filter"'),chips);
assert(chips.includes('data-voicesv2-filter="kind"'),chips);
assert(chips.includes('Remove filter'),'the control names what it removes');
assert(chips.includes('Clear all'));
""")


class ContextTests(LibraryTestCase):
    def test_opening_for_a_character_prefills_the_context_from_its_traits(self):
        self.lib("openFor('mira')", r"""
const context=V2.getState().libraryContext;
assert.deepStrictEqual(plain(context),{key:'mira',name:'MIRA',gender:'female',
  ageGroup:'adult',ageless:false});
""")

    def test_the_context_banner_says_who_and_what_and_how_many_match(self):
        self.lib("openFor('mira');await turn();", r"""
const banner=node('library-context').innerHTML;
assert(banner.includes('Choosing a voice for'),banner);
assert(banner.includes('MIRA'));
assert(banner.includes('Female'),banner);
const compatible=V2.library.filters.selectContextCompatible(V2.getState());
assert(banner.includes(compatible.total+' of 6 voices match'),
  'the banner counts what the selector counts: '+banner);
assert(banner.includes(compatible.inferred+' of them by inferred traits'),
  'how many matches rest on a guess is said out loud: '+banner);
assert.ok(compatible.inferred>0,'this fixture is meant to have inferred matches');
""")

    def test_context_narrowing_is_off_until_the_user_asks_for_it(self):
        self.lib("openFor('mira')", r"""
assert.strictEqual(V2.getState().libraryFilters.context,'off');
assert.strictEqual(V2.libraryVoices(V2.getState()).length,6);
""")

    def test_context_narrowing_never_excludes_a_voice_with_unknown_metadata(self):
        """A voice whose traits are unknown is not a mismatch; excluding it would
        hide exactly the voices the user is looking for."""
        self.lib("openFor('ryan');V2.library.panel.toggleContextFilter();", r"""
V2.dispatch({type:'library/filters',patch:{context:'suggested'}});
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert(shown.indexOf('clone:clip')>=0,
  'an unknown-gender clone must survive a male character');
assert(shown.indexOf('design:narrator')>=0);
assert(shown.indexOf('lora:mystery')>=0,
  'a voice that states no traits at all must survive any character');
""")

    def test_context_narrowing_excludes_a_voice_that_contradicts_the_character(self):
        self.lib("openFor('ryan');V2.library.panel.toggleContextFilter();", r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert(shown.indexOf('lora:baritone')>=0,
  'a male voice of the same age band matches: '+shown);
assert(shown.indexOf('lora:alto')<0,'a stated female voice contradicts a male character');
assert(shown.indexOf('builtin:watson')<0,
  'watson is male but adult, and the character is middle_aged');
""")

    def test_an_ageless_character_does_not_narrow_by_age(self):
        self.run_library(r"""
V2.library.openFor('mira');
V2.library.panel.toggleContextFilter();
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert(shown.indexOf('lora:alto')>=0,
  'alto is the wrong age band for MIRA and only ageless admits it: '+shown);
assert(shown.indexOf('clone:clip')>=0);
""", projection="PROJECTION_MIRA_AGELESS")

    def test_the_context_can_be_removed_and_the_result_set_restored(self):
        self.lib("openFor('mira');V2.library.panel.toggleContextFilter();", r"""
assert(V2.libraryVoices(V2.getState()).length<6,'narrowing did something');
V2.library.panel.toggleContextFilter();
assert.strictEqual(V2.getState().libraryFilters.context,'off');
assert.strictEqual(V2.libraryVoices(V2.getState()).length,6);
""")

    def test_opening_without_a_character_leaves_no_context(self):
        self.lib("open(null)", r"""
assert.strictEqual(V2.getState().libraryContext.key,null);
assert.strictEqual(node('library-context').innerHTML,'',
  'no subject means no banner, not an empty one');
""")

    def test_closing_drops_the_context_so_the_next_open_is_not_silently_narrowed(self):
        self.lib("openFor('mira');V2.library.close();", r"""
assert.strictEqual(V2.getState().library.open,false);
assert.strictEqual(V2.getState().libraryContext.key,null);
""")


class SortTests(LibraryTestCase):
    def names(self, key, direction):
        return ("V2.library.open(null);"
                "V2.dispatch({type:'library/sort',key:'%s',direction:'%s'});" % (key, direction))

    def test_name_sorting_is_alphabetical_and_reversible(self):
        self.run_library("", self.names("name", "asc") + r"""
assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.name)),
  ['A clip','alto','baritone','mystery','NARRATOR','watson']);
V2.dispatch({type:'library/sort',key:'name',direction:'desc'});
assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.name)),
  ['watson','NARRATOR','mystery','baritone','alto','A clip']);
""")

    def test_favorites_sort_first(self):
        self.run_library("", self.names("favorite", "asc") + r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert.strictEqual(shown[0],'lora:alto');
""")

    def test_available_sorts_before_unavailable(self):
        self.run_library("", self.names("availability", "asc") + r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.available));
assert.deepStrictEqual(plain(shown),[true,true,true,true,false,false],
  'available voices first, in every direction of the sort');
V2.dispatch({type:'library/sort',key:'availability',direction:'desc'});
assert.deepStrictEqual(
  plain(V2.libraryVoices(V2.getState()).map(v=>v.available)),
  [false,false,true,true,true,true]);
""")

    def test_gender_and_age_use_the_shared_band_order(self):
        self.run_library("", self.names("age", "asc") + r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.ageGroup));
assert.deepStrictEqual(shown,
  ['young_adult','adult','middle_aged','unknown','unknown','unknown'],
  'the band order comes from speaker_traits, youngest first');
""")
        self.run_library("", self.names("gender", "asc") + r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.gender));
assert.deepStrictEqual(shown,['female','male','male','unknown','unknown','unknown']);
""")

    def test_recent_puts_undated_voices_last_rather_than_treating_them_as_new(self):
        self.run_library("", self.names("recent", "asc") + r"""
const shown=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert.deepStrictEqual(shown,
  ['lora:baritone','clone:clip','lora:alto','lora:mystery','design:narrator','builtin:watson'],
  'ascending is chronological and a voice with no stated date is not treated as new');
V2.dispatch({type:'library/sort',key:'recent',direction:'desc'});
assert.deepStrictEqual(
  plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),
  ['lora:alto','clone:clip','lora:baritone','lora:mystery','design:narrator','builtin:watson'],
  'descending puts the newest first; undated still last and still alphabetical');
""")

    def test_an_illegal_sort_is_refused(self):
        self.run_library("V2.library.open(null);", r"""
assert.throws(()=>V2.dispatch({type:'library/sort',key:'vibes',direction:'asc'}),
  /cannot sort the library by/);
assert.throws(()=>V2.dispatch({type:'library/sort',key:'name',direction:'sideways'}),
  /must be asc or desc/);
""")


class NavigationTests(LibraryTestCase):
    def test_previous_and_next_walk_the_filtered_set_in_order(self):
        self.run_library("V2.library.open(null);await turn();"
                         "V2.dispatch({type:'library/sort',key:'name',direction:'asc'});"
                         "await turn();", r"""
assert.strictEqual(node('library-previous').disabled,true,'previous is off at the first');
node('library-position').textContent='';
V2.dispatch({type:'library/cursor',voiceId:'NARRATOR'.length?V2.libraryVoices(V2.getState())[0].voiceId:null});
await turn();
const info=V2.library.filters.selectNeighbours(V2.getState());
assert.strictEqual(info.position,1);
assert.strictEqual(info.previous,null);
assert.ok(info.next,'there is a next voice');
V2.library.panel.step(1);
const moved=V2.library.filters.selectNeighbours(V2.getState());
assert.strictEqual(moved.position,2);
assert.ok(moved.previous);
""")

    def test_navigation_cannot_leave_the_filtered_set(self):
        self.run_library("V2.library.open(null);"
                         "V2.dispatch({type:'library/filters',patch:{kind:'clone'}});"
                         "await turn();", r"""
const only=plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId));
assert.deepStrictEqual(only,['clone:clip']);
const info=V2.library.filters.selectNeighbours(V2.getState());
assert.strictEqual(info.total,1);
assert.strictEqual(info.previous,null,'nothing before the only result');
assert.strictEqual(info.next,null,'nothing after the only result');
assert.strictEqual(V2.library.panel.step(1),false);
assert.strictEqual(V2.library.panel.step(-1),false);
""")

    def test_next_is_disabled_at_the_end_and_previous_at_the_start(self):
        self.run_library("V2.library.open(null);await turn();", r"""
V2.dispatch({type:'library/sort',key:'name',direction:'asc'});await turn();
const last=V2.libraryVoices(V2.getState()).slice(-1)[0].voiceId;
V2.dispatch({type:'library/cursor',voiceId:last});
await turn();
assert.strictEqual(node('library-next').disabled,true);
V2.dispatch({type:'library/cursor',voiceId:V2.libraryVoices(V2.getState())[0].voiceId});
await turn();
assert.strictEqual(node('library-previous').disabled,true);
""")

    def test_the_position_reads_as_voice_x_of_y(self):
        self.run_library("V2.library.open(null);await turn();", r"""
assert.strictEqual(node('library-position').textContent,'Voice 1 of 6');
V2.library.panel.step(1);await turn();
assert.strictEqual(node('library-position').textContent,'Voice 2 of 6');
""")

    def test_the_dice_chooses_only_from_the_filtered_set(self):
        self.run_library("V2.library.open(null);"
                         "V2.dispatch({type:'library/filters',patch:{kind:'clone'}});", r"""
for(const roll of [0,0.5,0.99]){
  assert.strictEqual(V2.library.panel.random(function(){return roll;}),true);
  const picked=V2.getState().librarySelection.cursor;
  assert.strictEqual(picked,'clone:clip',
    'a dice roll inside a narrowed set must not escape it');
}
""")

    def test_the_dice_is_disabled_with_no_eligible_voices(self):
        self.run_library("V2.library.open(null);"
                         "V2.library.panel.setSearch('nothing matches this');", r"""
await turn();
assert.strictEqual(node('library-random').disabled,true);
assert.strictEqual(V2.library.panel.random(),false);
assert.strictEqual(V2.getState().librarySelection.cursor,null);
""")

    def test_the_dice_only_moves_the_cursor_and_never_saves(self):
        self.run_library("V2.library.open(null);", r"""
V2.library.panel.random(function(){return 0;});
assert.ok(V2.getState().librarySelection.cursor,'the cursor moved');
assert.strictEqual(V2.getState().draft.dirty,false,
  'a dice roll is navigation, not a choice');
""")


class RenderingTests(LibraryTestCase):
    def test_a_card_states_gender_and_age_with_their_provenance(self):
        self.lib("open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('Female (inferred)'),html);
assert(html.includes('Male (declared)'),html);
assert(html.includes('Unknown (unknown)'),'an unknown value says so');
""")

    def test_a_card_states_availability_and_the_reason_when_it_is_not(self):
        self.lib("open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('Available'),html);
assert(html.includes('Not available'),html);
assert(html.includes('The adapter files are not on disk.'),html);
""")

    def test_a_voice_with_no_preview_says_so_instead_of_offering_a_dead_control(self):
        self.lib("open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('No preview recorded'),html);
assert(html.includes('data-voicesv2-action="preview-voice"'),'the capable ones still offer one');
""")

    def test_the_selected_voice_is_marked_and_readable_without_colour(self):
        self.run_library("V2.library.openFor('mira');await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('Selected for this character'),html);
assert(html.includes('Chosen'),'the chosen button says so in words');
assert(html.includes('vv2-voice-card is-selected'),html);
""")

    def test_a_voice_with_no_favourite_support_explains_itself(self):
        self.lib("open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('Favourites are for LoRA voices'),html);
""")

    def test_the_favourite_button_is_a_pressed_toggle_with_a_readable_label(self):
        self.lib("open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('data-voicesv2-action="toggle-favorite"'),html);
assert(html.includes('aria-pressed="true"'),'a favourite is pressed');
assert(html.includes('Remove from favourites'),'the action is named');
""")

    def test_the_result_count_is_announced(self):
        self.lib("open(null);await turn();", r"""
assert.strictEqual(node('library-count').textContent,'6 voices');
V2.library.panel.setSearch('clone');
await turn();
assert.strictEqual(node('library-count').textContent,'1 of 6 voices');
""")

    def test_the_no_results_state_explains_and_offers_a_way_back(self):
        self.run_library("V2.library.open(null);"
                         "V2.library.panel.setSearch('nothing at all');", r"""
await turn();
const html=node('library-list').innerHTML;
assert(html.includes('No voices match the current search and filters'),html);
assert(html.includes('Clear filters'),html);
""")

    def test_the_empty_catalogue_state_explains_what_to_do(self):
        self.run_library("V2.dispatch({type:'catalogue/set',catalogue:"
                         "{voices:[],counts:{total:0,available:0,unavailable:0},kinds:[],"
                         "favoriteKinds:[],warnings:[],unsupportedKinds:{},schemaVersion:1,"
                         "loaded:true,error:null}});V2.library.open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('No voices are available'),html);
assert(html.includes('Train a LoRA'),html);
""")

    def test_a_catalogue_failure_is_offered_a_retry(self):
        self.run_library("V2.dispatch({type:'catalogue/error',error:'the server said no'});"
                         "V2.library.open(null);await turn();", r"""
const html=node('library-list').innerHTML;
assert(html.includes('Unable to load the voice library'),html);
assert(html.includes('data-voicesv2-action="reload-catalogue"'),html);
""")

    def test_the_loading_state_is_shown_before_the_catalogue_arrives(self):
        self.run_library("", r"""
/* state.reset() restores the initial catalogue, which is the honest
   not-yet-loaded state a panel sees before its first read lands. */
V2.state.reset();
V2.library.open(null);await turn();
assert(node('library-list').innerHTML.includes('Loading voices'),node('library-list').innerHTML);
""")

    def test_the_library_is_hidden_until_it_is_opened(self):
        self.run_library("", r"""
assert.strictEqual(V2.library.isOpen(),false);
assert.strictEqual(node('library').hidden,true);
V2.library.open(null);await turn();
assert.strictEqual(node('library').hidden,false);
V2.library.close();await turn();
assert.strictEqual(node('library').hidden,true);
""")

    def test_the_search_input_is_never_rebuilt_so_the_caret_survives(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const options=node('library-filter-kind').innerHTML;
for(const query of ['a','al','alt','alto']){
  setControl('library-search',query,'input');
  await turn();
}
assert.strictEqual(node('library-filter-kind').innerHTML,options,
  're-populating the option lists per keystroke would break focus');
assert.strictEqual(node('library-search').value,'alto');
assert.strictEqual((node('library').listeners.change||[]).length,1);
assert.strictEqual((node('library').listeners.click||[]).length,1,
  'one delegated listener per panel, bound once');
""")

    def test_a_filter_select_drives_the_store_and_the_list(self):
        self.run_library("V2.library.open(null);await turn();", r"""
setControl('library-filter-kind','clone','change');
await turn();
assert.strictEqual(V2.getState().libraryFilters.kind,'clone');
assert.deepStrictEqual(plain(V2.libraryVoices(V2.getState()).map(v=>v.voiceId)),['clone:clip']);
assert.strictEqual(node('library-filter-kind').value,'clone');
""")

    def test_the_sort_select_carries_both_halves_together(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const options=node('library-filter-sort').innerHTML;
assert(options.includes('value="name:desc"'),'both directions are offered in one control');
setControl('library-filter-sort','favorite:asc','change');
await turn();
assert.deepStrictEqual(plain(V2.getState().librarySort),{key:'favorite',direction:'asc'});
assert.strictEqual(node('library-filter-sort').value,'favorite:asc');
""")

    def test_typing_updates_the_list_without_a_request(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const before=characterCalls().length+catalogueCalls().length;
setControl('library-search','clip','input');
await turn();
assert.strictEqual(V2.getState().librarySearch,'clip');
assert(node('library-list').innerHTML.includes('A clip'));
assert(node('library-list').innerHTML.includes('NARRATOR')===false);
assert.strictEqual(characterCalls().length+catalogueCalls().length,before,
  'searching must not hit the network');
""")


class HandoffTests(LibraryTestCase):
    def test_choosing_a_voice_creates_a_draft_and_saves_nothing(self):
        self.run_library("V2.library.openFor('mira');await turn();", r"""
assert.strictEqual(V2.library.panel.choose('clone:clip'),true);
await turn();
const draft=V2.voiceDraft(V2.getState());
assert.strictEqual(draft.voiceId,'clone:clip');
assert.strictEqual(draft.dirty,true);
assert.strictEqual(V2.getState().draft.dirty,true);
assert.strictEqual(V2.canSaveVoice(V2.getState()),true);
""")

    def test_the_detail_editor_shows_the_chosen_voice_without_saving(self):
        self.run_library("V2.library.openFor('mira');"
                         "V2.library.panel.choose('clone:clip');await turn();", r"""
const editor=node('voice-editor').innerHTML;
assert(editor.includes('value="clone:clip" selected'),editor);
assert(editor.includes('Unsaved change'),editor);
assert(editor.includes('Saved now: baritone'),'the stored voice is still shown as stored');
""")

    def test_an_unavailable_voice_cannot_be_chosen(self):
        self.lib("open(null);await turn();", r"""
assert.strictEqual(V2.library.panel.choose('lora:alto'),false,
  'a voice whose files are gone must not be assignable');
assert.strictEqual(V2.getState().draft.dirty,false);
""")

    def test_closing_the_library_leaves_the_draft_intact(self):
        self.run_library("V2.library.openFor('mira');"
                         "V2.library.panel.choose('clone:clip');await turn();"
                         "V2.library.close();await turn();", r"""
assert.strictEqual(V2.getState().library.open,false);
assert.strictEqual(V2.getState().draft.dirty,true,
  'backing out of the library must not lose the choice');
assert.strictEqual(V2.voiceDraft(V2.getState()).voiceId,'clone:clip');
assert.strictEqual(V2.getState().selection.key,'mira','the character is still selected');
""")

    def test_the_library_never_writes_voice_config(self):
        self.run_library("V2.library.openFor('mira');await turn();"
                         "V2.library.panel.choose('clone:clip');"
                         "V2.library.panel.random();await turn();", r"""
assert.deepStrictEqual(commandCalls,[],
  'the library writes a draft; Phase 2 owns the only save path');
assert.strictEqual(V2.getState().save.state,'idle');
""")


class FavoriteTests(LibraryTestCase):
    def test_a_toggle_sends_the_voice_and_the_wanted_state(self):
        self.lib("open(null);await turn();", r"""
favoriteResult=['baritone','mystery'];
await V2.library.panel.toggleFavorite('lora:baritone');
assert.deepStrictEqual(plain(favoriteCalls),[{voice_id:'lora:baritone',favorite:true}]);
assert.strictEqual(V2.library.panel.findVoice('lora:baritone').favorite,true);
assert.strictEqual(V2.library.panel.findVoice('lora:alto').favorite,false,
  'a voice the server did not list must not stay starred');
""")

    def test_unfavouriting_sends_the_opposite_state(self):
        self.lib("open(null);await turn();", r"""
/* alto starts favourited in the fixture; the server's answer is an empty list. */
favoriteResult=[];
await V2.library.panel.toggleFavorite('lora:alto');
assert.deepStrictEqual(plain(favoriteCalls),[{voice_id:'lora:alto',favorite:false}]);
assert.strictEqual(V2.library.panel.findVoice('lora:alto').favorite,false,
  'the star follows the server, not the click');
""")

    def test_a_refused_write_leaves_the_star_exactly_where_it_was(self):
        self.lib("open(null);await turn();", r"""
favoriteMode='reject';
const before=V2.library.panel.findVoice('lora:baritone').favorite;
const outcome=await V2.library.panel.toggleFavorite('lora:baritone');
assert.strictEqual(outcome,false);
assert.strictEqual(V2.library.panel.findVoice('lora:baritone').favorite,before,
  'a write that failed must not be shown as if it succeeded');
""")

    def test_a_voice_without_favourite_support_is_never_sent(self):
        self.lib("open(null);await turn();", r"""
assert.strictEqual(await V2.library.panel.toggleFavorite('clone:clip'),false);
assert.deepStrictEqual(favoriteCalls,[]);
""")


class PreviewTests(LibraryTestCase):
    def test_one_preview_plays_at_a_time_through_one_manager(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const played=[];
const audio=ctx.window.VoicesV2.library.audio;
audio.setAudioFactory(function(){
  return {src:'',preload:'none',paused:true,
    play:function(){this.paused=false;return Promise.resolve();},
    pause:function(){this.paused=true;}};
});
assert.strictEqual(await audio.play(V2.library.panel.findVoice('lora:baritone')),true);
assert.strictEqual(V2.voiceSaveState(V2.getState()).state,'idle');
assert.strictEqual(V2.getState().preview.state,'playing');
assert.strictEqual(V2.getState().preview.voiceId,'lora:baritone');
await audio.play(V2.library.panel.findVoice('clone:clip'));
assert.strictEqual(V2.getState().preview.voiceId,'clone:clip','the second replaces the first');
""")

    def test_a_voice_with_no_preview_is_refused_rather_than_silently_doing_nothing(self):
        self.lib("open(null);await turn();", r"""
const audio=ctx.window.VoicesV2.library.audio;
audio.setAudioFactory(function(){
  return {src:'',preload:'none',play:function(){return Promise.resolve();},pause:function(){}};
});
assert.strictEqual(await audio.play(V2.library.panel.findVoice('lora:mystery')),false);
assert.strictEqual(V2.getState().preview.state,'idle');
""")

    def test_a_failed_play_reports_an_error_and_clears_the_loading_state(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const audio=ctx.window.VoicesV2.library.audio;
audio.setAudioFactory(function(){
  return {src:'',preload:'none',play:function(){return Promise.reject(Error('no'));},
    pause:function(){}};
});
await audio.play(V2.library.panel.findVoice('lora:baritone'));
const preview=V2.getState().preview;
assert.strictEqual(preview.state,'error');
assert(preview.error);
assert.notStrictEqual(preview.state,'loading','a failed play must not stay loading');
""")

    def test_closing_the_library_stops_any_preview(self):
        self.run_library("V2.library.open(null);await turn();", r"""
const audio=ctx.window.VoicesV2.library.audio;
let paused=0;
audio.setAudioFactory(function(){
  return {src:'',preload:'none',play:function(){return Promise.resolve();},
    pause:function(){paused+=1;}};
});
await audio.play(V2.library.panel.findVoice('lora:baritone'));
V2.library.close();
assert.ok(paused>0,'the preview was stopped');
assert.strictEqual(V2.getState().preview.state,'idle');
""")


class SourceBoundaryTests(unittest.TestCase):
    """The library goes through the V2 boundary and nowhere else."""

    def _code(self, name):
        return strip_js_comments((V2_DIR / name).read_text(encoding="utf-8"))

    def test_only_the_api_module_names_a_url(self):
        for name in V2_FILE_ORDER:
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("fetch(", code, f"{name} must use the shared API helper")
                self.assertNotIn("XMLHttpRequest", code)
                if name != "api.js":
                    self.assertNotIn("/api/", code, f"{name} must not name a Voices V2 URL")

    def test_the_library_never_names_the_legacy_voice_config_routes(self):
        for name in V2_FILE_ORDER:
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("/api/voice_config/", code)
                self.assertNotIn("/api/voice_library/", code,
                                 "favourites go through the V2 route, which delegates")

    def test_the_library_holds_no_save_logic(self):
        for name in ("library/filters.js", "library/cards.js", "library/index.js"):
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("api.sendCommand", code)
                self.assertNotIn("revision", code,
                                 "only the assignment panel presents a save token")
                self.assertNotIn("bookToken", code)

    def test_the_selectors_do_not_mutate_what_they_are_given(self):
        code = self._code("library/filters.js")
        self.assertIn("voices.slice().sort(", code,
                      "sorting must copy, never reorder the catalogue in place")
        self.assertNotIn("state.catalogue.voices.sort(", code)
        self.assertNotIn("state.catalogue.voices =", code)

    def test_every_library_selector_is_exported_and_pure(self):
        code = self._code("library/filters.js")
        for name in ("selectFiltered", "selectSummary", "selectChips", "selectSelectedVoice",
                     "selectNeighbours", "selectRandomEligible", "selectContextCompatible",
                     "selectPreviewState", "selectAll"):
            with self.subTest(selector=name):
                self.assertIn(name + ":", code)


if __name__ == "__main__":
    unittest.main()