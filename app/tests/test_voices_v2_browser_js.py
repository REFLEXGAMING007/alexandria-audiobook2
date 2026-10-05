"""The Voices V2 character browser: store, selectors and panels.

Split by layer, because each layer fails differently:

  Store tests     the only writer is dispatch; filter and sort values are
                   validated; a DOM node can never enter state.
  Selector tests  search, filters, sorting and the summary are pure; the stored
                   projection is never mutated by any of them; a stale trait
                   filter cannot hide every character on a book with no traits.
  Panel tests     rows render, selecting one updates the detail view, the four
                   empty/error states each say something, and retry works.

The selectors and panels run in the project's existing node + vm harness, against
a DOM that throws on any element id but `voicesv2-tab`. That harness is defined
once in `test_voices_v2_isolation.py` and imported here, so a change to the V2
region list cannot leave the two test modules disagreeing about what exists.
"""
import sys
import unittest
from pathlib import Path

from tests.test_voices_v2_isolation import _HARNESS, _NodeTestCase, V2_DIR, strip_js_comments


def _harness():
    return _HARNESS % {"files": repr([
        "core.js", "state.js", "selectors.js", "api.js",
        "widgets/labels.js", "widgets/states.js",
        "panels/toolbar.js", "panels/characters.js", "panels/detail.js",
        "lifecycle.js", "index.js"])}, str(V2_DIR)


class BrowserTestCase(_NodeTestCase):
    """Adds a small data builder to the shared node harness."""

    #: Three characters covering every filter axis, plus one orphan.
    PAYLOAD = r"""
payload={
  schema_version:1,
  book:{book_id:'Return of Mount Hua Sect',token:'tok',script_sha256:'sha',script_present:true},
  traits_available:true, traits_requested:true, aliases_registered:true, major_line_threshold:25,
  vocabularies:{genders:['male','female','genderless','unknown'],
    age_groups:[{value:'child',label:'6-11'},{value:'teen',label:'12-17'},{value:'adult',label:'30-39'}],
    problem_codes:['voice_unassigned','config_without_script_line']},
  characters:[
    {key:'mira',name:'MIRA',identity_key:'mira',library_key:'mira',present_in_script:true,
     generic:false,line_count:120,priority:'major',known_as:['Mira of the Vale'],aliases:['THE MIRA'],
     voice:{category:'lora',label:'baritone_deep',assigned:true,adapter_id:'baritone_deep',
       adapter_available:true,has_ref_audio:false,ref_audio_present:null,has_description:true,
       seed:null,alias_of:null,ensemble_members:0},
     voice_status:'assigned',persona_status:'generated',ready:true,
     persona_ref:'persona_refs/mira.json',persona_ref_resolves:true,active_version:'teen',
     versions:[{version_id:'teen',age_group:'teen',category:'lora',label:'baritone_deep',adapter_id:'baritone_deep'}],
     version_timeline:[],candidate_count:0,
     traits:{gender:'female',age_group:'adult',ageless:false,lines:120,
       current:{gender:'female',age_group:'adult'},states:[{gender:'female',age_group:'adult'}]},
     traits_available:true,states:[],possible_duplicate_of:[],problems:[]},
    {key:'ryan',name:'RYAN',identity_key:'ryan',library_key:'ryan',present_in_script:true,
     generic:false,line_count:4,priority:'minor',known_as:[],aliases:[],
     voice:{category:'custom',label:'Ryan',assigned:false,adapter_id:null,adapter_available:null,
       has_ref_audio:false,ref_audio_present:null,has_description:false,seed:null,alias_of:null,
       ensemble_members:0},
     voice_status:'unassigned',persona_status:'unreviewed',ready:false,
     persona_ref:null,persona_ref_resolves:null,active_version:null,versions:[],version_timeline:[],
     candidate_count:0,traits:{gender:'male',age_group:'child',ageless:false,lines:4,
       current:{gender:'male',age_group:'child'},states:[]},
     traits_available:true,states:[],possible_duplicate_of:[],problems:['voice_unassigned']},
    {key:'narrator',name:'NARRATOR',identity_key:'narrator',library_key:'narrator',
     present_in_script:true,generic:false,line_count:60,priority:'major',known_as:[],aliases:[],
     voice:{category:'clone',label:'Sohee',assigned:true,adapter_id:null,adapter_available:null,
       has_ref_audio:true,ref_audio_present:true,has_description:true,seed:null,alias_of:null,
       ensemble_members:0},
     voice_status:'unassigned',persona_status:'generated',ready:true,persona_ref:null,
     persona_ref_resolves:null,active_version:null,versions:[],version_timeline:[],candidate_count:0,
     traits:{gender:'unknown',age_group:'unknown',ageless:false,lines:60,
       current:{gender:'unknown',age_group:'unknown'},states:[]},
     traits_available:true,states:[],possible_duplicate_of:[],problems:['voice_status_conflict']}],
  orphans:[
    {key:'ghost',name:'GHOST',identity_key:'ghost',library_key:'ghost',present_in_script:false,
     generic:false,line_count:0,priority:null,known_as:[],aliases:[],
     voice:{category:'custom',label:'Aiden',assigned:false,adapter_id:null,adapter_available:null,
       has_ref_audio:false,ref_audio_present:null,has_description:false,seed:null,alias_of:null,
       ensemble_members:0},
     voice_status:'unassigned',persona_status:'unreviewed',ready:false,persona_ref:null,
     persona_ref_resolves:null,active_version:null,versions:[],version_timeline:[],candidate_count:0,
     traits:null,traits_available:false,states:[],possible_duplicate_of:['GH0ST'],
     problems:['config_without_script_line','voice_unassigned','possible_duplicate_identity']}],
  counts:{characters:3,orphans:1}};"""


class StoreCommandTests(BrowserTestCase):
    def test_the_store_exposes_the_schema_the_toolbar_binds_to(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
assert.deepStrictEqual(plain(V2.state.schema.filterKeys),
  ['query','scope','gender','ageGroup','assigned','ready','personaStatus','priority','problems']);
assert.deepStrictEqual(plain(V2.state.schema.sortKeys),
  ['name','lineCount','priority','voiceStatus','voice','ready','traitOrder']);
assert.deepStrictEqual(plain(V2.state.schema.scopes),['all','characters','orphans']);
assert.deepStrictEqual(plain(V2.state.schema.problemModes),['all','flagged','clean']);
/* The store owns which sorts are legal; the selector must be able to compare
   every one of them, and vice versa. Checked in both directions at load time by
   selectors.js, asserted here so the guarantee is visible. */
for(const key of V2.state.schema.sortKeys)assert(V2.selectors.comparator(key),'no comparator for '+key);
for(const key of V2.selectors.sortKeys)assert(V2.state.schema.sortKeys.includes(key),'stray sort key '+key);
""")

    def test_filters_start_at_a_documented_default(self):
        self.run_node(r"""
const filters=ctx.window.VoicesV2.getState().filters;
assert.deepStrictEqual(plain(filters),{query:'',scope:'all',gender:'all',ageGroup:'all',
  assigned:'all',ready:'all',personaStatus:'all',priority:'all',problems:'all',
  sort:{key:'name',direction:'asc'}});
""")

    def test_a_filter_patch_writes_only_the_named_keys(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
V2.dispatch({type:'filters/patch',patch:{query:'mi',assigned:'no'}});
assert.strictEqual(V2.getState().filters.query,'mi');
assert.strictEqual(V2.getState().filters.assigned,'no');
assert.strictEqual(V2.getState().filters.ready,'all','an unnamed filter must not move');
""")

    def test_an_unknown_filter_or_an_illegal_value_is_refused(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
assert.throws(()=>V2.dispatch({type:'filters/patch',patch:{colour:'red'}}),/no filter named/);
assert.throws(()=>V2.dispatch({type:'filters/patch',patch:{scope:'everything'}}),/does not accept/);
assert.throws(()=>V2.dispatch({type:'filters/patch',patch:{sort:{key:'vibes',direction:'asc'}}}),/cannot sort by/);
assert.throws(()=>V2.dispatch({type:'filters/patch',patch:{sort:{key:'name',direction:'sideways'}}}),/is not asc or desc/);
assert.throws(()=>V2.dispatch({type:'filters/patch',patch:[]}),/needs an object/);
assert.strictEqual(V2.getState().filters.scope,'all','a refused patch must not mutate');
""")

    def test_gender_and_age_accept_any_string_because_the_book_decides_the_values(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
V2.dispatch({type:'filters/patch',patch:{gender:'elderly-dragon',ageGroup:'ancient'}});
assert.strictEqual(V2.getState().filters.gender,'elderly-dragon');
assert.strictEqual(V2.getState().filters.ageGroup,'ancient');
""")

    def test_selection_is_a_key_and_reset_restores_the_defaults(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
V2.dispatch({type:'selection/set',key:'mira'});
assert.strictEqual(V2.getState().selection.key,'mira');
assert.throws(()=>V2.dispatch({type:'selection/set',key:7}),/string key or null/);
V2.dispatch({type:'selection/set',key:null});
assert.strictEqual(V2.getState().selection.key,null);
V2.dispatch({type:'filters/patch',patch:{query:'x',scope:'orphans'}});
V2.dispatch({type:'filters/reset'});
assert.strictEqual(V2.getState().filters.query,'');
assert.strictEqual(V2.getState().filters.scope,'all');
""")

    def test_filter_and_selection_writes_notify_the_path_that_changed(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2,seen=[];
V2.subscribe('*',(s,path)=>seen.push(path));
V2.dispatch({type:'filters/patch',patch:{query:'mira'}});
V2.dispatch({type:'selection/set',key:'mira'});
V2.dispatch({type:'filters/reset'});
assert.deepStrictEqual(seen,['filters','selection','filters']);
""")


class SelectorTests(BrowserTestCase):
    def test_the_wire_shape_is_adapted_to_camel_case_records(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
const data=V2.selectors.adaptProjection(payload);
assert.strictEqual(data.meta.schemaVersion,1);
assert.strictEqual(data.meta.book.bookId,'Return of Mount Hua Sect');
assert.strictEqual(data.meta.traitsAvailable,true);
assert.strictEqual(data.characters[0].lineCount,120);
assert.strictEqual(data.characters[0].voice.adapterId,'baritone_deep');
assert.strictEqual(data.characters[0].traits.ageGroup,'adult');
assert.strictEqual(data.characters[0].versions[0].versionId,'teen');
assert.strictEqual(data.orphans[0].presentInScript,false);
assert.strictEqual(data.orphans[0].traits,null);
""")

    def test_adaptation_is_total_so_a_malformed_row_cannot_reach_the_ui(self):
        self.run_node(r"""
const adapt=ctx.window.VoicesV2.selectors.adaptProjection;
const data=adapt({characters:[null,{},'nonsense',{name:'X',voice:'bad',traits:7,problems:'no'}],
  orphans:'not a list',book:7,vocabularies:null,traits_available:'yes'});
assert.strictEqual(data.characters.length,4);
const row=data.characters[3];
assert.strictEqual(row.name,'X');
assert.strictEqual(row.voice.category,'custom','a missing voice becomes a default');
assert.strictEqual(row.voice.label,'Unknown voice');
assert.deepStrictEqual(plain(row.problems),[]);
assert.strictEqual(row.traits,null);
assert.strictEqual(row.lineCount,0);
assert.strictEqual(data.orphans.length,0);
assert.deepStrictEqual(plain(data.characters[1].knownAs),[]);
""")

    def test_search_matches_name_alias_known_name_voice_and_adapter(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const names=q=>{V2.dispatch({type:'filters/patch',patch:{query:q}});
  return V2.visibleCharacters(V2.getState()).map(c=>c.name);};
assert.deepStrictEqual(plain(names('')),['GHOST','MIRA','NARRATOR','RYAN']);
assert.deepStrictEqual(plain(names('mira')),['MIRA']);
assert.deepStrictEqual(plain(names('THE MIRA')),['MIRA'],'a registered alias is searchable');
assert.deepStrictEqual(plain(names('vale')),['MIRA'],'a library known name is searchable');
assert.deepStrictEqual(plain(names('baritone')),['MIRA'],'the voice label is searchable');
assert.deepStrictEqual(plain(names('sohee')),['NARRATOR']);
assert.deepStrictEqual(plain(names('zzz')),[]);
""")

    def test_search_terms_are_and_not_or(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const names=q=>{V2.dispatch({type:'filters/patch',patch:{query:q}});
  return V2.visibleCharacters(V2.getState()).map(c=>c.name);};
assert.deepStrictEqual(plain(names('mira vale')),['MIRA']);
assert.deepStrictEqual(plain(names('mira sohee')),[],
  'two characters each matching one term is not a match');
assert.deepStrictEqual(plain(names('  MIRA  ')),['MIRA'],'query is trimmed and case-folded');
""")

    def test_every_filter_axis_narrows_the_list(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const names=()=>V2.visibleCharacters(V2.getState()).map(c=>c.name);
/* Each case starts from the defaults, so one axis is exercised at a time. */
const set=patch=>{V2.dispatch({type:'filters/reset'});
  V2.dispatch({type:'filters/patch',patch});return names();};
assert.deepStrictEqual(plain(set({gender:'female'})),['MIRA']);
assert.deepStrictEqual(plain(set({gender:'unavailable'})),['GHOST'],'the orphan has no traits');
assert.deepStrictEqual(plain(set({ageGroup:'child'})),['RYAN']);
assert.deepStrictEqual(plain(set({assigned:'no'})),['GHOST','RYAN']);
assert.deepStrictEqual(plain(set({ready:'yes'})),['MIRA','NARRATOR']);
assert.deepStrictEqual(plain(set({personaStatus:'unreviewed'})),['GHOST','RYAN']);
assert.deepStrictEqual(plain(set({personaStatus:'none'})),[],'nobody has no persona');
assert.deepStrictEqual(plain(set({priority:'minor'})),['RYAN']);
assert.deepStrictEqual(plain(set({priority:'none'})),['GHOST'],'an orphan has no lines');
assert.deepStrictEqual(plain(set({problems:'flagged'})),['GHOST','NARRATOR','RYAN']);
assert.deepStrictEqual(plain(set({problems:'clean'})),['MIRA']);
""")

    def test_scope_separates_characters_from_orphans(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const names=()=>V2.visibleCharacters(V2.getState()).map(c=>c.name);
V2.dispatch({type:'filters/patch',patch:{scope:'characters'}});
assert.deepStrictEqual(plain(names()),['MIRA','NARRATOR','RYAN']);
V2.dispatch({type:'filters/patch',patch:{scope:'orphans'}});
assert.deepStrictEqual(plain(names()),['GHOST']);
V2.dispatch({type:'filters/patch',patch:{scope:'all'}});
assert.strictEqual(names().length,4);
""")

    def test_a_stale_trait_filter_cannot_hide_everything_on_a_book_without_traits(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
const withoutTraits={schema_version:1,book:{script_present:true},traits_available:false,
  vocabularies:{genders:[],age_groups:[]},
  characters:[{key:'a',name:'A',line_count:3,traits:null},
              {key:'b',name:'B',line_count:2,traits:null}],orphans:[]};
V2.lifecycle.applyPayload(withoutTraits);
V2.dispatch({type:'filters/patch',patch:{gender:'female',ageGroup:'adult'}});
assert.strictEqual(V2.visibleCharacters(V2.getState()).length,2,
  'trait filters must be inert when the book records no traits');
""")

    def test_every_sort_key_orders_and_is_reversible(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const order=()=>V2.visibleCharacters(V2.getState()).map(c=>c.name);
const sorted=key=>{V2.dispatch({type:'filters/reset'});
  V2.dispatch({type:'filters/patch',patch:{sort:{key:key,direction:'asc'}}});return order();};
const at=names=>index=>names.indexOf(index);
assert.deepStrictEqual(plain(sorted('name')),['GHOST','MIRA','NARRATOR','RYAN']);
/* Line count: the orphan with no lines leads, the 120-line character trails. */
assert.deepStrictEqual(plain(sorted('lineCount')),['GHOST','RYAN','NARRATOR','MIRA']);
assert.deepStrictEqual(plain(sorted('priority')),['MIRA','NARRATOR','RYAN','GHOST'],
  'major before minor before no lines');
/* Unassigned first when ascending, which is the thing a user opens this for. */
assert.deepStrictEqual(plain(sorted('voiceStatus')).slice(0,2),['GHOST','RYAN']);
assert.deepStrictEqual(plain(sorted('ready')).slice(0,2),['MIRA','NARRATOR']);
assert.deepStrictEqual(plain(sorted('traitOrder')),['RYAN','MIRA','NARRATOR','GHOST'],
  'age bands ascend: child, adult, unknown; the character with no traits sorts last');
/* Reversing the direction reverses the comparator, not the tie-break. */
V2.dispatch({type:'filters/reset'});
V2.dispatch({type:'filters/patch',patch:{sort:{key:'name',direction:'desc'}}});
assert.deepStrictEqual(plain(order()),['RYAN','NARRATOR','MIRA','GHOST']);
V2.dispatch({type:'filters/patch',patch:{sort:{key:'lineCount',direction:'desc'}}});
assert.deepStrictEqual(plain(order()),['MIRA','NARRATOR','RYAN','GHOST']);
assert(at(order())('MIRA')<at(order())('GHOST'),'descending puts the most lines first');
""")

    def test_filtering_and_sorting_never_mutate_the_stored_projection(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
const state=V2.getState();
const characters=state.characters;
const orphans=state.orphans;
const before=JSON.stringify({characters:characters,orphans:orphans});
const reference=characters[0];
const frozenOrder=characters.map(c=>c.name);
for(const key of V2.state.schema.sortKeys){
  V2.dispatch({type:'filters/patch',patch:{sort:{key:key,direction:'desc'}}});
  V2.visibleCharacters(state);
}
for(const value of ['yes','no']){
  V2.dispatch({type:'filters/patch',patch:{assigned:value,ready:value}});
  V2.visibleCharacters(state);
}
V2.dispatch({type:'filters/patch',patch:{problems:'flagged',scope:'orphans'}});
V2.visibleCharacters(state);
assert.strictEqual(state.characters,characters,'the selector replaced the stored array');
assert.strictEqual(state.orphans,orphans);
assert.strictEqual(state.characters[0],reference,'the selector replaced a record');
assert.deepStrictEqual(plain(state.characters.map(c=>c.name)),frozenOrder,
  'sorting reordered the stored projection');
assert.strictEqual(JSON.stringify({characters:characters,orphans:orphans}),before);
""")

    def test_the_summary_reports_what_is_shown_out_of_what_is_there(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
let summary=V2.characterSummary(V2.getState());
assert.strictEqual(summary.total,4);assert.strictEqual(summary.shown,4);
assert.strictEqual(summary.characters,3);assert.strictEqual(summary.orphans,1);
assert.strictEqual(summary.flagged,3);
assert.strictEqual(summary.narrowed,false);
V2.dispatch({type:'filters/patch',patch:{query:'mira'}});
summary=V2.characterSummary(V2.getState());
assert.strictEqual(summary.shown,1);assert.strictEqual(summary.total,4);
assert.strictEqual(summary.narrowed,true);
V2.dispatch({type:'filters/patch',patch:{scope:'characters'}});
summary=V2.characterSummary(V2.getState());
assert.strictEqual(summary.scoped,3,'the scope is reported separately from the total');
""")

    def test_selection_survives_a_re_sort_and_is_dropped_when_the_character_goes(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
V2.lifecycle.applyPayload(payload);
V2.dispatch({type:'selection/set',key:'mira'});
assert.strictEqual(V2.selectedCharacter(V2.getState()).name,'MIRA');
V2.dispatch({type:'filters/patch',patch:{sort:{key:'lineCount',direction:'desc'}}});
assert.strictEqual(V2.selectedCharacter(V2.getState()).name,'MIRA',
  'a re-sort must not change who is selected');
V2.dispatch({type:'filters/patch',patch:{scope:'orphans'}});
assert.strictEqual(V2.selectedCharacter(V2.getState()).name,'MIRA',
  'filtering out a selected character must not silently clear the detail');
/* A fresh projection that no longer contains the key drops it, because an empty
   detail panel with no explanation is the failure mode worth avoiding. */
V2.lifecycle.applyPayload({schema_version:1,book:{script_present:true},traits_available:true,
  characters:[],orphans:[],vocabularies:{}});
assert.strictEqual(V2.getState().selection.key,null);
assert.strictEqual(V2.selectedCharacter(V2.getState()),null);
""")


class PanelTests(BrowserTestCase):
    """Panel assertions on markup follow a `turn()`.

    Renders are coalesced onto a microtask so that one read - which dispatches
    meta, characters, orphans and ui - paints the list once instead of four
    times. That makes a repaint asynchronous by design, so a test that inspects
    markup after a store change must yield first. Store-only assertions need not.
    """

    def test_rows_render_for_every_visible_character(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
await turn();
const html=node('characters').innerHTML;
assert(html.includes('<ul class="vv2-list" role="list">'));
for(const name of ['MIRA','RYAN','NARRATOR','GHOST'])assert(html.includes(name),'missing row '+name);
assert(html.includes('MIRA of the Vale')===false,'the row is a summary, not the detail');
assert(html.includes('Female'),'traits appear on the row when available');
assert(html.includes('Not available'),'the orphan shows an honest trait placeholder');
assert(html.includes('warning'),'a warning count is shown without listing every code');
assert.strictEqual(node('characters').innerHTML.includes('aria-current="false"'),true,
  'every row carries an accessible selected state');
""")

    def test_the_selected_row_is_marked_and_not_by_position(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
V2.dispatch({type:'selection/set',key:'narrator'});
await turn();
let html=node('characters').innerHTML;
const selected=html.match(/data-voicesv2-character="narrator"[^>]*aria-current="true"/);
assert(selected,'the selected row must be marked');
assert(html.includes('data-voicesv2-character="mira" class="vv2-row" aria-current="false"')||
       html.match(/data-voicesv2-character="mira"[^>]*aria-current="false"/),'mira is not selected');
/* Re-sorting must not move the selection onto a different character. */
V2.dispatch({type:'filters/patch',patch:{sort:{key:'lineCount',direction:'desc'}}});
await turn();
html=node('characters').innerHTML;
assert(html.match(/data-voicesv2-character="narrator"[^>]*aria-current="true"/),
  'selection is keyed, so a re-sort keeps it on NARRATOR');
""")

    def test_selecting_a_row_updates_the_detail_view(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
assert(node('detail').innerHTML.includes('Select a character'),'no selection shows a prompt');
V2.dispatch({type:'selection/set',key:'mira'});
await turn();
const html=node('detail').innerHTML;
for(const section of ['overview','voice','traits','versions','persona','warnings']){
  assert(html.includes('data-voicesv2-section="'+section+'"'),'missing section '+section);
}
assert(html.includes('LoRA voice'),'the voice category is named');
assert(html.includes('baritone_deep'),'the adapter is named');
assert(html.includes('Assigned'));
assert(html.includes('Ready'));
assert(html.includes('Adult'),'the age band comes from the vocabulary');
assert(html.includes('teen'),'the active version is named');
assert(html.includes('persona_refs/mira.json'));
assert(html.includes('(found)'));
assert(html.includes('No warnings for this character'));
""")

    def test_the_detail_view_explains_an_orphan_rather_than_hiding_it(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
V2.dispatch({type:'selection/set',key:'ghost'});
await turn();
const html=node('detail').innerHTML;
assert(html.includes('not in the active script'),'an orphan must say why it is listed');
assert(html.includes('config_without_script_line')===false,'codes stay out of the detail copy');
assert(html.includes('Possible duplicate of'));
assert(html.includes('GH0ST'));
assert(html.includes('No script line'),'the problem is explained by name');
assert(html.includes('Not recorded'),'a character with no traits says so');
""")

    def test_the_detail_view_states_a_missing_voice_rather_than_a_blank(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
V2.dispatch({type:'selection/set',key:'ryan'});
await turn();
const html=node('detail').innerHTML;
assert(html.includes('Unassigned'));
assert(html.includes('No voice'),'a problem is explained by name');
assert(html.includes('Unreviewed'));
""")

    def test_a_book_without_traits_says_so_in_the_detail_view(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
V2.lifecycle.applyPayload({schema_version:1,book:{script_present:true},traits_available:false,
  traits_requested:false,vocabularies:{genders:[],age_groups:[]},
  characters:[{key:'a',name:'A',line_count:3,traits:null}],orphans:[]});
await turn();
V2.dispatch({type:'selection/set',key:'a'});
await turn();
const html=node('detail').innerHTML;
assert(html.includes('data-voicesv2-section="traits"'));
assert(html.includes('Not available'),'absence is stated');
assert(html.includes('generated without per-line speaker traits'),
  'the explanation names the reason, not just the gap');
assert(html.includes('Male')===false,'nothing may be invented');
""")

    def test_the_result_count_reports_shown_of_total_and_the_orphan_split(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
assert(node('counts').innerHTML.includes('4 characters'));
assert(node('counts').innerHTML.includes('1 orphan'));
V2.dispatch({type:'filters/patch',patch:{query:'mi'}});
await turn();
const html=node('counts').innerHTML;
assert(html.includes('1 of 4 characters'),html);
assert(html.includes('Clear filters'),'narrowing offers a way back');
""")

    def test_the_toolbar_disables_the_trait_filters_when_traits_are_unavailable(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
assert.strictEqual(node('filter-gender').disabled,false);
assert.strictEqual(node('filter-ageGroup').disabled,false);
assert(status.innerHTML.includes('Speaker traits are not available')===false,
  'nothing is announced while traits are present');
V2.lifecycle.applyPayload({schema_version:1,book:{script_present:true},traits_available:false,
  traits_requested:false,aliases_registered:true,vocabularies:{genders:[],age_groups:[]},
  characters:[],orphans:[]});
await turn();
assert.strictEqual(node('filter-gender').disabled,true);
assert.strictEqual(node('filter-gender').getAttribute('aria-disabled'),'true');
assert(status.innerHTML.includes('Speaker traits are not available for this book'));
assert(status.innerHTML.includes('disabled'),'the notice says the controls are disabled');
""")

    def test_search_is_written_to_the_store_and_the_list_follows(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
node('search').value='nar';
node('search').fire('input',{target:{value:'nar'}});
await turn();
assert.strictEqual(V2.getState().filters.query,'nar');
assert(node('characters').innerHTML.includes('NARRATOR'));
assert(node('characters').innerHTML.includes('MIRA')===false,'the list must follow the store');
assert.strictEqual(node('search').value,'nar','the input is not clobbered while typing');
""")

    def test_the_search_input_is_never_rebuilt_so_focus_survives(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
const before=node('filter-gender').innerHTML;
for(const query of ['m','mi','mir','mira']){
  node('search').fire('input',{target:{value:query}});
  await turn();
}
assert.strictEqual(node('filter-gender').innerHTML,before,
  're-populating the option lists on every keystroke would break focus');
assert.strictEqual((node('search').listeners.input||[]).length,1,'one input listener only');
assert.strictEqual((node('filter-gender').listeners.change||[]).length,1,
  'a re-render must not re-bind the filter controls');
""")

    def test_a_filter_select_drives_the_store_and_the_list(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
node('filter-assigned').fire('change',{target:{value:'no'}});
await turn();
assert.strictEqual(V2.getState().filters.assigned,'no');
assert(node('characters').innerHTML.includes('RYAN'));
assert(node('characters').innerHTML.includes('GHOST'));
assert(node('characters').innerHTML.includes('NARRATOR')===false);
assert.strictEqual(node('filter-assigned').value,'no','the control reflects the store');
""")

    def test_the_sort_select_carries_both_the_key_and_the_direction(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
assert(node('filter-sort').innerHTML.includes('value="lineCount:desc"'),
  'both directions are offered in one control so the pair cannot half-update');
node('filter-sort').fire('change',{target:{value:'lineCount:desc'}});
await turn();
assert.deepStrictEqual(plain(V2.getState().filters.sort),{key:'lineCount',direction:'desc'});
assert(node('characters').innerHTML.indexOf('MIRA')<
  node('characters').innerHTML.indexOf('RYAN'),true,
  'descending line count puts the 120-line character before the 4-line one');
""")

    def test_reset_restores_every_control_from_the_store(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
node('search').fire('input',{target:{value:'x'}});
node('filter-ready').fire('change',{target:{value:'yes'}});
node('filter-sort').fire('change',{target:{value:'voice:desc'}});
await turn();
node('reset-filters').fire('click',{});
await turn();
assert.strictEqual(V2.getState().filters.query,'');
assert.strictEqual(node('search').value,'');
assert.strictEqual(node('filter-ready').value,'all');
assert.strictEqual(node('filter-sort').value,'name:asc');
""")

    def test_the_empty_state_explains_a_book_with_no_script(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
V2.lifecycle.applyPayload({schema_version:1,book:{script_present:false},traits_available:false,
  traits_requested:null,aliases_registered:false,vocabularies:{},characters:[],orphans:[]});
const html=node('characters').innerHTML;
assert(html.includes('No characters yet'));
assert(html.includes('generated or a saved book is opened'),'it says what to do');
""")

    def test_the_no_results_state_names_the_filters_and_offers_a_way_back(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
V2.dispatch({type:'filters/patch',patch:{query:'nobody-by-that-name'}});
await turn();
const html=node('characters').innerHTML;
assert(html.includes('No characters match'));
assert(html.includes('search or filters'));
assert(html.includes('data-voicesv2-action="clear-filters"'));
""")

    def test_clearing_the_filters_from_a_no_result_state_restores_the_list(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
V2.dispatch({type:'filters/patch',patch:{query:'zzz'}});
await turn();
assert(node('characters').innerHTML.includes('No characters match'));
const clear=actionButton('clear-filters');
root.fire('click',{target:clear});
await turn();
assert.strictEqual(V2.getState().filters.query,'');
assert(node('characters').innerHTML.includes('MIRA'));
""")

    def test_a_failed_read_offers_a_retry_that_recovers(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
const held=holdNext('/api/voices-v2/characters');
const pending=V2.mount();await turn();
held.reject(Object.assign(Error('backend down'),{status:503,detail:'down'}));
assert.strictEqual(await pending,false);
assert(status.innerHTML.includes('alert-danger'));
assert(status.innerHTML.includes('Retry'));
assert(node('detail').innerHTML.includes('Select a character'),
  'the detail panel must not be left blank after a failure');
const retry=actionButton('retry');
root.fire('click',{target:retry});
await turn();await turn();await turn();
assert.strictEqual(characterCalls().length,2,'retry re-reads');
assert.strictEqual(V2.getState().ui.error,null,'a successful retry clears the error');
assert(status.innerHTML.includes('alert-danger')===false);
""")

    def test_the_live_region_announces_the_result_count(self):
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
assert.strictEqual(node('live').textContent,'4 of 4 characters');
V2.dispatch({type:'filters/patch',patch:{query:'mira'}});
await turn();
assert.strictEqual(node('live').textContent,'1 of 4 characters');
""")

    def test_nothing_written_into_a_panel_markup_can_reach_the_store(self):
        """The DOM is an output. Reading a panel's HTML back must never become a
        write path, which is the failure mode collectVoiceConfig introduced."""
        self.run_node(self.PAYLOAD + r"""
const V2=ctx.window.VoicesV2;
await V2.mount();
const state=V2.getState();
const reference=state.characters[0];
const html=node('characters').innerHTML;
/* Scrape the rendered row the way the Voices tab does, and show that dispatching
   it changes nothing: the store has no command that accepts markup. */
const scraped=html.replace(/<[^>]*>/g,' ').split(/\s+/).filter(Boolean);
assert(scraped.length>0);
for(const command of ['characters/merge','characters/fromMarkup','characters/setRaw']){
  assert.throws(()=>V2.dispatch({type:command,characters:scraped}),/does not implement/);
}
assert.strictEqual(state.characters[0],reference);
""")


class ResponsiveMarkupTests(unittest.TestCase):
    """The layout must be mobile-first, and the CSS must stay scoped."""

    INDEX = Path(__file__).resolve().parent.parent / "static" / "index.html"

    def setUp(self):
        self.html = self.INDEX.read_text(encoding="utf-8")

    def test_the_browser_is_one_column_by_default_and_two_only_where_there_is_room(self):
        from tests.test_voices_v2_isolation import v2_css_block

        block = strip_js_comments(v2_css_block())
        self.assertIn("#voicesv2-tab .vv2-workspace { display: grid; gap: 1rem; grid-template-columns: minmax(0, 1fr); }",
                      block, "the default layout must be a single column")
        wide = block[block.index("@media (min-width: 992px)"):]
        self.assertIn("grid-template-columns: minmax(0, 22rem) minmax(0, 1fr)", wide,
                      "the two-column split belongs at lg and above")

    def test_the_mobile_breakpoint_widens_the_controls_and_drops_the_scroll_cap(self):
        from tests.test_voices_v2_isolation import v2_css_block

        block = strip_js_comments(v2_css_block())
        narrow = block[block.index("@media (max-width: 575.98px)"):]
        self.assertIn("width: 100%", narrow,
                      "controls must be full width on a phone")
        self.assertIn("max-height: none", narrow,
                      "a capped list inside a single column scrolls badly on a phone")

    def test_every_control_has_a_visible_label(self):
        for control_id in ("voicesv2-search", "voicesv2-filter-scope", "voicesv2-filter-gender",
                           "voicesv2-filter-age", "voicesv2-filter-assigned",
                           "voicesv2-filter-ready", "voicesv2-filter-persona",
                           "voicesv2-filter-priority", "voicesv2-filter-problems",
                           "voicesv2-filter-sort"):
            with self.subTest(control=control_id):
                self.assertIn(f'for="{control_id}"', self.html,
                              f"{control_id} has no label")

    def test_status_and_count_regions_are_live_and_atomic(self):
        self.assertIn('id="voicesv2-counts" class="small vv2-counts" role="status" '
                      'aria-live="polite"', self.html)
        self.assertIn('class="small text-muted vv2-live" role="status" aria-live="polite" '
                      'aria-atomic="true"', self.html)

    def test_the_workspace_uses_landmarks_so_it_is_navigable_by_keyboard(self):
        self.assertIn('aria-label="Characters"', self.html)
        self.assertIn('aria-label="Character detail"', self.html)
        self.assertIn('role="search"', self.html)

    def test_focus_is_visible_for_every_interactive_v2_control(self):
        from tests.test_voices_v2_isolation import v2_css_block

        block = strip_js_comments(v2_css_block())
        self.assertIn(":focus-visible", block)
        self.assertIn("outline: 2px solid var(--focus-ring)", block)
        for selector in (".vv2-row:focus-visible", ".vv2-toolbar :focus-visible",
                         ".vv2-detail-card :focus-visible", ".vv2-state :focus-visible"):
            self.assertIn(selector, block, f"{selector} has no visible focus ring")


if __name__ == "__main__":
    unittest.main()