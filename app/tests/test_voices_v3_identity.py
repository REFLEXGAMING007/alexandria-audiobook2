"""Voices V3: the roster row key and the speaker are different strings.

A character has two names in this tab:

  row key  "MARO#adult" - one settled state. Unique per row, and the key the
                         store, the DOM and the save map use. Equal to the
                         character name for a character with no state split.
  speaker  "MARO"       - the character. What every speaker-scoped API call is
                         given, because `_require_script_speaker` validates it
                         against the script and rejects a row key outright.

Passing the wrong one is silent in both directions. Both are plain strings, so
nothing throws and the mistake lands somewhere plausible:

  - handed the speaker, a row-local function reads the character's BASE entry
    instead of the row's own. Three call sites shipped that way: play, delete
    and upload. Play reported "There is no reference audio for MARO" while the
    state row's own ref_audio field was visibly populated, and an upload was
    written to the base entry instead of versions[age_group] - a wrong write
    with no error at all, since nothing rejects a base-entry write.
  - handed a row key, an API call 404s with "Speaker is not present in the
    active script".

Four bugs in this tab were one of those two mistakes, so this file gates the
class rather than the instances:

  1. every roster call site declares which identity it passes, by calling
     `rowKeyFor(...)` or `speakerFor(...)` and nothing else;
  2. `onRosterClick` resolves no loose local that a case could grab by mistake;
  3. dispatching a real control really does hand over the identity declared
     above, checked against a roster where a character has THREE settled
     states, because a single-state character cannot tell the two names apart -
     `speakerOf` returns the row key unchanged when there is no `#`.

That last point is why this went unnoticed: every test and every manual check
that used a single-state character passed while the code was wrong.
"""
import re
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
STATIC = APP / "static"
V3_DIR = STATIC / "js" / "voices-v3"

# The load order, which index.html declares and voices-v3/index.js restates.
V3_FILES = (
    "core.js", "state.js", "selectors.js", "api.js", "save.js",
    "widgets/labels.js", "widgets/markup.js",
    "panels/toolbar.js", "panels/personas.js", "panels/card.js",
    "panels/states.js", "panels/suggestions.js", "panels/cast.js",
    "panels/roster.js",
    "events.js", "actions.js", "lifecycle.js", "index.js",
)

EVENTS = V3_DIR / "events.js"

#: What every action in the roster click switch must pass, and why.
#:
#: "speaker" - the call reaches an API that validates the name against the
#:             script. The row key is rejected there.
#: "row"     - the call reads or writes row-local state through
#:             selectors.workingOf / storedConfig, which are keyed by roster row.
#: None      - the action takes no name at all.
IDENTITY = {
    # speaker-scoped: every one of these reaches the server with the name.
    "style-point-remove": "speaker",
    "persona-regenerate": "speaker",
    "persona-audit-edit": "speaker",
    "approval": "speaker",
    "version-select": "speaker",
    "version-add": "speaker",
    "version-generate-age": "speaker",
    "suggestion-apply": "speaker",
    "candidate-select": "speaker",
    "candidate-delete": "speaker",
    "candidate-favorite": "speaker",
    # row-local: keyed by the roster row, so a state row's own values.
    "states-open": "row",
    "states-apply": "row",
    "states-clear": "row",
    "suggest-more": "row",
    "clone-upload": "row",
    "clone-play": "row",
    "clone-delete": "row",
    "design-open": "row",
    # no name.
    "seed-repair": None,
    "draft-recover": None,
    "draft-discard": None,
    "save-discard": None,
}

#: The two, and only two, ways a roster call site may obtain a name.
ROW_ACCESSOR = "rowKeyFor"
SPEAKER_ACCESSOR = "speakerFor"


def roster_click_switch():
    """Return {action: body} for every case in the roster click switch."""
    body = _function_body(EVENTS.read_text(encoding="utf-8"),
                          "function onRosterClick(event)")
    cases = {}
    for match in re.finditer(r"case '([^']+)':(.*?)(?=\n\s*case '|\n\s*default:)",
                             body, re.S):
        cases[match.group(1)] = match.group(2)
    return cases


def _function_body(source, signature):
    """The text of one function, up to the next top-level `function`."""
    start = source.index(signature)
    following = source.find("\n    function ", start + 1)
    return source[start:following if following != -1 else len(source)]


class IdentityDeclarationTests(unittest.TestCase):
    """Lints events.js. No runtime, so it runs even if the module cannot load."""

    def test_every_roster_action_is_classified(self):
        handled = set(roster_click_switch())
        self.assertEqual(set(IDENTITY), handled,
                         "the roster click switch and the identity oracle "
                         "disagree about which actions exist")

    def test_each_action_passes_exactly_the_identity_it_requires(self):
        for action, want in IDENTITY.items():
            body = roster_click_switch()[action]
            used_row = ROW_ACCESSOR + "(" in body
            used_speaker = SPEAKER_ACCESSOR + "(" in body
            got = ("row" if used_row else "speaker" if used_speaker else None)
            with self.subTest(action=action):
                self.assertEqual(
                    want, got,
                    f"'{action}' must be passed the {want} identity; it uses "
                    f"{got}. rowKeyFor() gives the roster row key "
                    f"('MARO#adult'), speakerFor() gives the character ('MARO'). "
                    f"Handed the speaker, a row-local call reads the base entry "
                    f"and a state row's own values become invisible; handed a row "
                    f"key, an API call 404s.")

    def test_no_action_passes_both_identities(self):
        for action, body in roster_click_switch().items():
            with self.subTest(action=action):
                self.assertFalse(ROW_ACCESSOR + "(" in body
                                 and SPEAKER_ACCESSOR + "(" in body,
                                 f"'{action}' resolves both names; each case "
                                 f"should ask for the one it needs")

    def test_on_roster_click_resolves_no_loose_name_or_speaker(self):
        """The locals are what let three cases take the wrong one.

        `var speaker = selectors.speakerOf(...)` sat in scope for the whole
        switch, so `playCloneVoice(speaker)` type-checked, ran, and silently
        read the wrong entry.
        """
        source = EVENTS.read_text(encoding="utf-8")
        body = _function_body(source, "function onRosterClick(event)")
        for pattern in (r"\bvar\s+name\s*=", r"\bvar\s+speaker\s*=",
                        r"\bspeakerOf\(", r"\bdata-voicesv3-name\b"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, body),
                    "onRosterClick must obtain names only through "
                    f"{ROW_ACCESSOR}() / {SPEAKER_ACCESSOR}(); found {pattern}")

    def test_the_clone_upload_input_uses_the_row_key(self):
        """The file input is not an action, so it never reaches the switch.

        Its handler read `storeState` before it was assigned - the var was
        hoisted, so it was undefined and `speakerOf` was handed no roster at
        all - and then collapsed the row key to the character, which put an
        uploaded reference on the base entry instead of versions[age_group].
        """
        body = _function_body(EVENTS.read_text(encoding="utf-8"),
                              "function onRosterChange(event)")
        self.assertIn("uploadCloneVoice(" + ROW_ACCESSOR + "(", body)
        self.assertNotIn("speakerOf(", body)
        # The state read must precede the use that needs it.
        read = body.index("state.getState()")
        use = body.index("uploadCloneVoice(")
        self.assertLess(read, use,
                        "storeState is read before it is used")

    def test_the_two_accessors_are_the_only_name_sources(self):
        """One reader, two accessors. Nothing else turns a node into a name.

        `nameOf` is the single place the attribute is read, so there is exactly
        one reader to get wrong. The two accessors on top of it are what make
        the identity visible at each call site.
        """
        source = EVENTS.read_text(encoding="utf-8")
        for accessor in (ROW_ACCESSOR, SPEAKER_ACCESSOR):
            with self.subTest(accessor=accessor):
                self.assertIn(f"function {accessor}(", source)
        readers = list(re.finditer(r"getAttribute\('data-voicesv3-name'\)", source))
        self.assertEqual(
            1, len(readers),
            "data-voicesv3-name is read at "
            f"{[source[:m.start()].count(chr(10)) + 1 for m in readers]}; it must "
            f"be read once, in nameOf(), and reached through {ROW_ACCESSOR}() / "
            f"{SPEAKER_ACCESSOR}() so the identity is visible at the call site")


_HARNESS = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const dir=process.argv[1];
const files=%(files)s;

function makeNode(tag,attrs){
  attrs=attrs||{};
  return {tag,attrs:Object.assign({},attrs),style:{display:'block'},innerHTML:'',
    textContent:'',value:'',disabled:false,checked:false,files:null,
    listeners:{},
    addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
    removeEventListener(){},
    getAttribute(name){return Object.prototype.hasOwnProperty.call(this.attrs,name)?this.attrs[name]:null;},
    setAttribute(name,value){this.attrs[name]=String(value);},
    querySelector(){return null;},
    querySelectorAll(){return [];},
    closest(sel){
      if(sel==='[data-voicesv3-action]'&&this.attrs['data-voicesv3-action']!=null)return this;
      if(sel==='[data-voice]'&&this.attrs['data-voice']!=null)return this;
      return null;
    }};
}

const root=makeNode('div',{'id':'voicesv3-tab'});
root.querySelector=function(sel){
  const m=/^\[data-voicesv3-region="([^"]+)"\]$/.exec(sel);
  if(m)return regions[m[1]]||null;
  return null;
};
root.querySelectorAll=function(){return [];};
root.contains=function(){return true;};

const regions={};
['toolbar','roster','personas','cast'].forEach(name=>{
  regions[name]=makeNode('div',{'data-voicesv3-region':name});
  regions[name].innerHTML='';
});

const toasts=[],errors=[],confirms=[],fetches=[];
function escapeHtml(value){return String(value).replace(/[&<>"']/g,
  ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}

const ctx={window:null,document:{getElementById:id=>id==='voicesv3-tab'?root:null,
    createElement:tag=>makeNode(tag,{})},console,
  escapeHtml,
  /* Array.prototype.sort mutates, so `sorted()` is a copy the caller owns. */
  sorted:values=>Array.prototype.slice.call(values).sort(),
  showToast:(m,t)=>{toasts.push({message:m,type:t});},
  showActionError:(a,e,r)=>{errors.push({action:a,error:e,recovery:r});},
  showConfirm:(m,o)=>{confirms.push({message:m,options:o});return Promise.resolve(false);},
  confirm:()=>false,alert:()=>{},prompt:()=>null,
  fetch:(path,init)=>{fetches.push({path,init});return Promise.resolve({ok:true,json:()=>Promise.resolve([])});},
  FormData:function(){this.append=function(){};},
  File:function(){},Blob:function(){},FileReader:function(){},
  setTimeout:setTimeout,clearTimeout:clearTimeout,setInterval:setInterval,
  Audio:function(){this.play=()=>Promise.resolve();this.pause=()=>{};},
  getComputedStyle:()=>({display:'block'}),
  __files:files,__dir:dir,__root:root,__regions:regions,
  __toasts:toasts,__errors:errors,__fetches:fetches};
ctx.window=ctx;
ctx.self=ctx;
vm.createContext(ctx);

function loadAll(){for(const name of files){vm.runInContext(fs.readFileSync(dir+'/'+name,'utf8'),ctx);}}
function ns(){return vm.runInContext('window.VoicesV3',ctx);}
/* Round-trip through JSON so assert compares plain values, not vm-realm ones. */
const plain=v=>JSON.parse(JSON.stringify(v));

/* A control that carries the attributes the delegated handlers read. */
function control(attrs){
  attrs=Object.assign({'data-voicesv3-action':'','data-voicesv3-name':''},attrs);
  const node=makeNode('button',attrs);
  node.closest=function(sel){
    if(sel==='[data-voicesv3-action]')return this;
    if(sel==='[data-voice]')return null;
    return null;
  };
  return node;
}

/* Record what an action was handed, replacing the real implementation so a
 * test observes the argument rather than the consequence.
 *
 * The owner is searched for, but `api` is deliberately NOT among the candidates:
 * several names exist on both layers - `api.deleteCloneVoice` takes a library
 * voice id while `actions.deleteCloneVoice` takes a roster row, and
 * `api.uploadCloneVoice` takes a File. api.js loads before actions.js, so a
 * naive search stubs the transport and the test silently observes nothing. */
function record(names){
  const calls=[];
  const target=ns();
  const panels=['actions','personasPanel','statesPanel','suggestionsPanel',
    'castPanel','toolbarPanel','rosterPanel'];
  names.forEach(name=>{
    const key=panels.find(k=>target[k]&&typeof target[k][name]==='function');
    if(!key)throw Error('no VoicesV3 panel exposes '+name);
    target[key][name]=function(){
      calls.push({name:name,args:Array.prototype.slice.call(arguments)});};
  });
  return calls;
}
"""


def _harness():
    return _HARNESS % {"files": repr(list(V3_FILES))}, str(V3_DIR)


#: A character with THREE settled states, each with its own saved voice, plus a
#: plain character and the narrator. This is the shape that distinguishes the two
#: identities: with one state, `speakerOf` returns the row key unchanged and a
#: wrong identity cannot be observed at all.
ROSTER_ROWS = r"""
add({name:'MARO',row_key:'MARO#teen',speaker:'MARO',age_group:'teen',
  from_entry:4,to_entry:50,has_version:true,
  config:{type:'clone',ref_audio:'designed_voices/teen.wav',ref_text:'teen line',
          description:'teen',character_style:'teen',seed:'111'},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',
    versions:{teen:{type:'clone',ref_audio:'designed_voices/teen.wav',seed:'111'}}},
  persona_status:'generated',voice_status:'assigned',ready:false});
add({name:'MARO',row_key:'MARO#adult',speaker:'MARO',age_group:'adult',
  from_entry:50,to_entry:100,has_version:true,
  config:{type:'clone',ref_audio:'designed_voices/adult.wav',ref_text:'adult line',
          description:'adult',character_style:'adult',seed:'222'},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',
    versions:{adult:{type:'clone',ref_audio:'designed_voices/adult.wav',seed:'222'}}},
  persona_status:'generated',voice_status:'assigned',ready:false});
add({name:'MARO',row_key:'MARO#elderly',speaker:'MARO',age_group:'elderly',
  from_entry:100,to_entry:null,has_version:true,
  config:{type:'clone',ref_audio:'designed_voices/elderly.wav',ref_text:'elderly line',
          description:'elderly',character_style:'elderly',seed:'333'},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',
    versions:{elderly:{type:'clone',ref_audio:'designed_voices/elderly.wav',seed:'333'}}},
  persona_status:'generated',voice_status:'assigned',ready:false});
add({name:'THE FOREMAN',row_key:'THE FOREMAN',speaker:'THE FOREMAN',age_group:'adult',
  from_entry:null,to_entry:null,has_version:false,config:{},base_config:{},
  persona_status:'unreviewed',voice_status:'unassigned',ready:false});
add({name:'NARRATOR',row_key:'NARRATOR',speaker:'NARRATOR',age_group:null,
  from_entry:null,to_entry:null,has_version:true,
  config:{type:'clone',ref_audio:'designed_voices/narrator.wav'},
  base_config:{type:'clone',ref_audio:'designed_voices/narrator.wav'},
  persona_status:'generated',voice_status:'assigned',ready:true});
"""


#: The same fixture, applied through `lifecycle.adoptRoster` rather than a bare
#: `roster/set`.
#:
#: That matters. `adoptRoster` (lifecycle.js:133-138) seeds a `working` entry per
#: row from its stored config, and `buildEntry` rebuilds the form-owned fields
#: from `working`. A fixture that only dispatches `roster/set` leaves every
#: `working` entry empty, so the save map drops ref_audio/ref_text/description for
#: every row - a data-loss bug that only a faithful fixture can tell apart from
#: the real thing. Going through adoptRoster is what production does on load.
ROSTER_SETUP = """
(function(){
  const rows=[];
  function add(row){rows.push(row);}
  %(rows)s
  ns().lifecycle.adoptRoster(rows);
})();
""" % {"rows": ROSTER_ROWS}


class _NodeTestCase(unittest.TestCase):
    """Runs the real V3 files in node against a DOM stub.

    `with_roster` is the default because almost nothing in this tab can be
    observed without one: `speakerFor` resolves through the roster, and a
    single-state character cannot tell the two identities apart at all.
    """

    with_roster = True

    def run_node(self, body, pre="", timeout=30):
        setup, directory = _harness()
        after_load = (ROSTER_SETUP + "\n") if self.with_roster else ""
        code = (setup
                + "\nlet done=false;process.on('beforeExit',()=>assert(done,'assertions must finish'));\n"
                + "(async()=>{\n" + pre + "\nloadAll();\n" + after_load + body
                + "\ndone=true;\n})().catch(e=>{console.error(e);process.exitCode=1;});")
        import subprocess
        result = subprocess.run(["node", "-e", code, directory],
                                capture_output=True, text=True, timeout=timeout)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def run_json(self, body, **kwargs):
        import json
        out = self.run_node(body, **kwargs)
        lines = [line for line in out.strip().splitlines() if line.strip()]
        self.assertTrue(lines, "the node run printed nothing")
        return json.loads(lines[-1])



class DispatchIdentityTests(_NodeTestCase):
    """Drives the real handlers over a roster where the two names differ.

    Every assertion here would pass on a single-state character, because
    `speakerOf` returns the row key unchanged when there is no `#`. MARO has
    three settled states, so passing the wrong identity is observable.
    """

    def test_row_local_actions_receive_the_row_key(self):
        """The regression that shipped three times.

        `clone-play` on a state row was handed the character, so playCloneVoice
        read the base entry, found no ref_audio and reported "There is no
        reference audio for MARO" - while that row's own field was visibly full.
        """
        calls = self.run_json("""
const calls=record(['playCloneVoice','deleteCloneVoice']);
const V=ns();
for(const band of ['teen','adult','elderly']){
  const node=control({'data-voicesv3-action':'clone-play',
    'data-voicesv3-name':'MARO#'+band});
  V.events.onRosterClick({target:node,preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'clone-delete',
    'data-voicesv3-name':'MARO#'+band}),preventDefault(){}});
}
console.log(JSON.stringify(plain(calls)));
""")
        self.assertEqual(6, len(calls))
        for call in calls:
            self.assertIn(call["args"][0],
                          {"MARO#teen", "MARO#adult", "MARO#elderly"},
                          f"{call['name']} must receive the roster row key, "
                          f"not the character")

    def test_a_plain_row_is_passed_its_own_name(self):
        calls = self.run_json("""
const calls=record(['playCloneVoice']);
const V=ns();
V.events.onRosterClick({target:control({'data-voicesv3-action':'clone-play',
  'data-voicesv3-name':'THE FOREMAN'}),preventDefault(){}});
console.log(JSON.stringify(plain(calls)));
""")
        self.assertEqual(["THE FOREMAN"], [c["args"][0] for c in calls])

    def test_speaker_scoped_actions_receive_the_character(self):
        """A row key here 404s: `_require_script_speaker` rejects it."""
        calls = self.run_json("""
const calls=record(['setApproval','addVersion','selectVersion','deleteCandidate',
  'favoriteCandidate','editPersonaVoiceAudit']);
const V=ns();
for(const band of ['teen','adult','elderly']){
  const key='MARO#'+band;
  V.events.onRosterClick({target:control({'data-voicesv3-action':'approval',
    'data-voicesv3-name':key,'data-voicesv3-field':'persona_status',
    'data-voicesv3-value':'approved'}),preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'version-add',
    'data-voicesv3-name':key}),preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'version-select',
    'data-voicesv3-name':key,value:'adult'}),preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'candidate-delete',
    'data-voicesv3-name':key,'data-voicesv3-id':'c1'}),preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'candidate-favorite',
    'data-voicesv3-name':key,'data-voicesv3-id':'c1',
    'data-voicesv3-value':'true'}),preventDefault(){}});
  V.events.onRosterClick({target:control({'data-voicesv3-action':'persona-audit-edit',
    'data-voicesv3-name':key}),preventDefault(){}});
}
console.log(JSON.stringify(plain(calls)));
""")
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual("MARO", call["args"][0],
                             f"{call['name']} must receive the character")

    def test_state_panel_actions_receive_the_row_key(self):
        calls = self.run_json("""
const calls=record(['open','apply','clear']);
const V=ns();
V.events.onRosterClick({target:control({'data-voicesv3-action':'states-open',
  'data-voicesv3-name':'MARO#elderly'}),preventDefault(){}});
V.events.onRosterClick({target:control({'data-voicesv3-action':'states-apply',
  'data-voicesv3-name':'MARO#elderly'}),preventDefault(){}});
V.events.onRosterClick({target:control({'data-voicesv3-action':'states-clear',
  'data-voicesv3-name':'MARO#teen'}),preventDefault(){}});
console.log(JSON.stringify(plain(calls)));
""")
        self.assertEqual(["MARO#elderly", "MARO#elderly", "MARO#teen"],
                         [c["args"][1] for c in calls])

    def test_per_state_persona_carries_the_band_and_entry_range(self):
        calls = self.run_json("""
const calls=record(['regenerateOne']);
const V=ns();
V.events.onRosterClick({target:control({'data-voicesv3-action':'persona-regenerate',
  'data-voicesv3-name':'MARO#adult','data-voicesv3-age':'adult',
  'data-voicesv3-from-entry':'50','data-voicesv3-to-entry':'100'}),
  preventDefault(){}});
console.log(JSON.stringify(plain(calls)));
""")
        self.assertEqual(1, len(calls))
        speaker, options = calls[0]["args"]
        self.assertEqual("MARO", speaker,
                         "the persona request filters by CHARACTER")
        self.assertEqual("adult", options.get("ageGroup"))
        self.assertEqual({"start": 50, "end": 100}, options.get("entryRange"))

    def test_a_state_with_no_end_sends_an_open_range(self):
        calls = self.run_json("""
const calls=record(['regenerateOne']);
const V=ns();
V.events.onRosterClick({target:control({'data-voicesv3-action':'persona-regenerate',
  'data-voicesv3-name':'MARO#elderly','data-voicesv3-age':'elderly',
  'data-voicesv3-from-entry':'100'}),preventDefault(){}});
console.log(JSON.stringify(plain(calls)));
""")
        speaker, options = calls[0]["args"]
        self.assertEqual("MARO", speaker)
        self.assertEqual({"start": 100}, options.get("entryRange"),
                         "the last band has no end; it must not be sent as 0")

    def test_a_plain_rows_persona_has_no_band_and_no_range(self):
        calls = self.run_json("""
const calls=record(['regenerateOne']);
const V=ns();
V.events.onRosterClick({target:control({'data-voicesv3-action':'persona-regenerate',
  'data-voicesv3-name':'THE FOREMAN'}),preventDefault(){}});
console.log(JSON.stringify(plain(calls)));
""")
        speaker, options = calls[0]["args"]
        self.assertEqual("THE FOREMAN", speaker)
        self.assertIsNone(options.get("ageGroup"))
        self.assertIsNone(options.get("entryRange"))

    def test_upload_lands_on_the_state_row_not_the_base(self):
        """The wrong write with no error at all.

        `triggerCloneFilePicker` used the row key, but the file-input change
        handler collapsed it, so an uploaded reference was dispatched as
        `working/set` for the CHARACTER and saved to the base entry instead of
        versions[age_group]. Nothing rejects a base-entry write, so it would
        have looked like it worked.
        """
        calls = self.run_json("""
const calls=record(['uploadCloneVoice']);
const V=ns();
const input=control({'data-voicesv3-name':'MARO#elderly'});
input.classList={contains:c=>c==='clone-voice-file-input'};
input.files=[{name:'take.wav'}];
V.events.onRosterChange({target:input});
console.log(JSON.stringify(plain(calls)));
""")
        self.assertEqual(1, len(calls))
        self.assertEqual("MARO#elderly", calls[0]["args"][0],
                         "the upload must be dispatched for the state row, "
                         "so it persists under versions[elderly]")


class MultiStateSaveTests(_NodeTestCase):
    """The save map, over a roster where a character has three settled states.

    `_apply_voice_save` merges each character shallowly
    (`{**existing, **config}`) and `versions` is a plain dict, so a payload
    carrying `versions` REPLACES the whole thing. A save that emitted only the
    edited band would destroy its siblings without error, which is why the
    rebuild in `buildVoiceDocument` exists.
    """

    def test_speaker_of_separates_the_two_names(self):
        got = self.run_json("""
const V=ns(),st=V.state.getState();
console.log(JSON.stringify(plain({
  teen:V.selectors.speakerOf(st,'MARO#teen'),
  adult:V.selectors.speakerOf(st,'MARO#adult'),
  foreman:V.selectors.speakerOf(st,'THE FOREMAN'),
  isStateTeen:V.selectors.isStateRow(st,'MARO#teen'),
  isStateForeman:V.selectors.isStateRow(st,'THE FOREMAN'),
  bandAdult:V.selectors.stateAgeGroup(st,'MARO#adult'),
  bandForeman:V.selectors.stateAgeGroup(st,'THE FOREMAN')
})));
""")
        self.assertEqual("MARO", got["teen"])
        self.assertEqual("MARO", got["adult"])
        self.assertEqual("THE FOREMAN", got["foreman"])
        self.assertTrue(got["isStateTeen"])
        self.assertFalse(got["isStateForeman"],
                         "a plain row is not a state row")
        self.assertEqual("adult", got["bandAdult"])
        self.assertIsNone(got["bandForeman"])

    def test_the_save_map_keys_states_by_band_under_one_character(self):
        document_ = self.run_json("""
const V=ns();
console.log(JSON.stringify(plain(
  V.selectors.buildVoiceDocument(V.state.getState()))));
""")
        self.assertNotIn("MARO#adult", document_,
                         "a state row must not become a top-level entry")
        self.assertNotIn("MARO#teen", document_)
        bands = sorted((document_.get("MARO") or {}).get("versions", {}))
        self.assertEqual(["adult", "elderly", "teen"], bands)

    def test_every_stored_sibling_survives_a_single_band_edit(self):
        got = self.run_json("""
const V=ns();
V.state.dispatch({type:'working/set',name:'MARO#adult',
  entry:{type:'clone',ref_text:'EDITED',
         ref_audio:'designed_voices/adult.wav'}});
const doc=V.selectors.buildVoiceDocument(V.state.getState());
console.log(JSON.stringify(plain({
  bands:Object.keys(doc.MARO.versions||{}).sort(),
  adultRefText:doc.MARO.versions.adult.ref_text,
  teenRef:doc.MARO.versions.teen.ref_audio,
  elderlyRef:doc.MARO.versions.elderly.ref_audio
})));
""")
        self.assertEqual(["adult", "elderly", "teen"], got["bands"],
                         "editing one band dropped its siblings from the save, "
                         "which _apply_voice_save would then persist as the "
                         "complete versions dict")
        self.assertEqual("EDITED", got["adultRefText"])
        self.assertEqual("designed_voices/teen.wav", got["teenRef"])
        self.assertEqual("designed_voices/elderly.wav", got["elderlyRef"])


class CloneDescriptionSaveTests(_NodeTestCase):
    """A saved persona must survive a save from this tab.

    `generate_personas.py` writes `description` and `character_style` onto the
    entry it creates (`_save_generated_preview`, generate_personas.py:709-717).
    The save map rebuilds the form-owned fields from `working`, and
    `FORM_OWNED_KEYS` includes `description` and `character_style` - so
    `preservedMetadata` strips both, and each type branch is then responsible for
    putting back the fields that belong to it.

    `buildTypeFields` does that for `custom` (character_style) and for `design`
    (description), but the `clone` branch emits only type/ref_text/ref_audio/seed.
    A persona voice IS a clone, so saving the tab silently dropped the very text
    the persona generation had just produced.
    """

    def test_a_clone_keeps_its_description_through_a_save(self):
        got = self.run_json("""
const V=ns();
const doc=V.selectors.buildVoiceDocument(V.state.getState());
console.log(JSON.stringify(plain({
  adult:doc.MARO.versions.adult,
  baseDescription:doc.MARO.description,
  baseStyle:doc.MARO.character_style
})));
""")
        adult = got["adult"]
        self.assertEqual("adult", adult.get("description"),
                         "a clone entry lost its persona description on save; "
                         "generate_personas.py writes it and FORM_OWNED_KEYS "
                         "strips it, so buildTypeFields' clone branch must "
                         "re-emit it")
        self.assertEqual("adult", adult.get("character_style"),
                         "a clone entry lost its character_style on save")

    def test_a_custom_entry_keeps_its_description_too(self):
        got = self.run_json("""
const roster=[{name:'MIRA',row_key:'MIRA',speaker:'MIRA',age_group:null,
  from_entry:null,to_entry:null,has_version:true,
  config:{type:'custom',voice:'Aiden',description:'a dry, level read',
          character_style:'measured',seed:'7'},
  base_config:{},persona_status:'generated',voice_status:'assigned',ready:false}];
const V=ns();
V.lifecycle.adoptRoster(roster);
console.log(JSON.stringify(plain(
  V.selectors.buildVoiceDocument(V.state.getState()).MIRA)));
""")
        self.assertEqual("a dry, level read", got.get("description"),
                         "a custom entry lost its persona description on save")
        self.assertEqual("measured", got.get("character_style"))
        self.assertEqual("Aiden", got.get("voice"))


class UnassignedStateSaveTests(_NodeTestCase):
    """A state row with no saved version must not be invented on save.

    Option C: an unassigned state row renders empty rather than falling back to
    the character's base config, because that base is usually the placeholder
    `voice: "Aiden"`. The save map has to honour that. Writing
    `{type:'custom', voice:'', seed:'-1'}` for every band would put a fabricated
    version on disk, flip `has_version` to true in the projection, and leave a
    row that looks assigned but has no voice at all.

    This is gated separately from the sibling-preservation test above because
    the two pull in opposite directions: one wants every band present, the other
    wants unassigned bands absent.
    """

    #: MARO with only `adult` saved. `teen` and `elderly` are roster rows with an
    #: empty config and `has_version: false`.
    with_roster = False

    def test_an_unassigned_band_is_absent_from_the_save(self):
        got = self.run_json("""
const rows=[];
function add(row){rows.push(row);}
add({name:'MARO',row_key:'MARO#teen',speaker:'MARO',age_group:'teen',
  from_entry:4,to_entry:50,has_version:false,config:{},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',versions:{}},
  persona_status:'unreviewed',voice_status:'unassigned',ready:false});
add({name:'MARO',row_key:'MARO#adult',speaker:'MARO',age_group:'adult',
  from_entry:50,to_entry:100,has_version:true,
  config:{type:'clone',ref_audio:'designed_voices/adult.wav',seed:'222'},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',
    versions:{adult:{type:'clone',ref_audio:'designed_voices/adult.wav',seed:'222'}}},
  persona_status:'generated',voice_status:'assigned',ready:false});
add({name:'MARO',row_key:'MARO#elderly',speaker:'MARO',age_group:'elderly',
  from_entry:100,to_entry:null,has_version:false,config:{},
  base_config:{type:'custom',voice:'Aiden',seed:'-1',versions:{}},
  persona_status:'unreviewed',voice_status:'unassigned',ready:false});
const V=ns();
V.lifecycle.adoptRoster(rows);
const doc=V.selectors.buildVoiceDocument(V.state.getState());
console.log(JSON.stringify(plain({
  bands:Object.keys(doc.MARO.versions||{}).sort(),
  baseType:doc.MARO.type,
  baseVoice:doc.MARO.voice
})));
""")
        self.assertEqual(["adult"], got["bands"],
                         "an unassigned state row must not produce a version; "
                         "`{type:'custom', voice:'', seed:'-1'}` is written to "
                         "disk, flips has_version true, and leaves a row that "
                         "looks assigned with no voice")
        self.assertEqual("custom", got["baseType"],
                         "the character's own entry must keep its own type")


if __name__ == "__main__":
    unittest.main()
