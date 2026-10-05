"""Voices V2 is a standalone feature domain beside Voices — enforce the boundary.

The Phase 0 deliverable is an isolation boundary, so these tests are the
deliverable's real product. Without them the boundary is a comment; with them
it is a gate that fails the build when someone reads the Voices tab's state,
borrows its markup, calls its loader, or routes a request at its endpoints.

Five properties are checked, at the level each one can actually break at:

  Namespace  the V2 files create exactly one global, and it is VoicesV2.
  DOM        the V2 tab root is a sibling of the Voices tab, shares no element
             id with it, and is never nested inside another tab.
  JS         no V2 file names a Voices-page symbol, and the only id V2 looks up
             is its own root.
  CSS        every V2 selector is scoped to #voicesv2-tab and uses only tokens
             the page already defines.
  Backend    the V2 router owns only /api/voices-v2/* paths, collides with no
             existing route, and changes no existing route.

Two boundaries are checked behaviourally, not by scanning: the store refuses
values that would put the DOM into application state, and lifecycle mount /
refresh / unmount actually behave as advertised under repeated navigation.
Those run the real files in node against a fake DOM that throws on any lookup
outside #voicesv2-tab.

Source scans run against comments stripped. A rule that forbids naming
collectVoiceConfig() would otherwise punish the file that documents why V2 must
not use it, and documentation is exactly what should be encouraged here.
"""
from html.parser import HTMLParser
from pathlib import Path
import re
import subprocess
import unittest


APP = Path(__file__).resolve().parent.parent
STATIC = APP / "static"
V2_DIR = STATIC / "js" / "voices-v2"
# Dependency order, which is also the order index.html must load them in. Kept as
# an explicit tuple rather than a glob so a new file cannot be added without
# deciding where it sits and what may depend on it.
V2_FILES = (
    "core.js", "state.js", "selectors.js", "api.js",
    "widgets/labels.js", "widgets/states.js",
    "panels/toolbar.js", "panels/characters.js", "panels/detail.js", "panels/assignment.js",
    "library/filters.js", "library/audio.js", "library/previews.js",
    "library/cards.js", "library/panel.js",
    "library/index.js",
    "lifecycle.js", "index.js",
)
INDEX = STATIC / "index.html"

V2_TAB = "voicesv2-tab"
V2_ID_PREFIX = "voicesv2-"
V2_CLASS_PREFIX = "vv2-"

# Symbols owned by the existing Voices page. A V2 file that *calls* any of
# these is coupled to that implementation. The list is deliberately wide: it
# includes read-only caches a future panel would be tempted to reuse.
VOICES_PAGE_SYMBOLS = (
    "createVoiceCard", "collectVoiceConfig", "renderVoiceSuggestions",
    "ensembleMembersMarkup", "refreshVoiceMetadata", "suggestVoices",
    "getVoiceCandidateMarkup", "getLibraryVoiceReference", "getTraitBadgeHtml",
    "selectVoiceVersion", "addVoiceVersion", "getVoiceStateDefault",
    "renderVoiceStateRows", "openVoiceStates", "applyVoiceStates",
    "onVoiceReadyChange", "onToggleHideReady", "voiceChangesHere",
    "saveVoicesDebounced", "flushVoiceSaves", "loadVoices", "loadCastLibrary",
    "AVAILABLE_VOICES", "voiceSaveQueue",
    "_voicesByName", "_voicesNames", "_voiceSuggestions", "_selectedCast",
    "_lineCounts", "_loraModelsCache", "_cloneVoicesCache", "_designedVoicesCache",
    "_voiceSaveSnapshot", "_voiceResourcesRefreshedAt",
)

# Voices-tab-only DOM targets. None may appear in a V2 file or the V2 tab.
VOICES_DOM_TARGETS = (
    "#voices-tab", "#voices-list", ".voice-card", "#cast-panel", "#cast-select",
    "#series-cast-card", "#voices-hide-ready", "#voices-ready-count",
    "#voice-save-status", "#voices-logs", "#voice-save-drafts",
)

# Stable app-wide helpers V2 may depend on. Only core.js may call them; every
# other file must go through core, so there is one place to change if a helper's
# contract ever moves. core.js is the designated boundary and is exempt.
SHARED_HELPERS = ("escapeHtml", "showToast", "showActionError")


def strip_js_comments(source):
    """Remove // and /* */ comments while leaving string literals intact."""
    out = []
    index = 0
    size = len(source)
    while index < size:
        char = source[index]
        if char in "'\"`":
            end = index + 1
            while end < size and source[end] != char:
                end += 2 if source[end] == "\\" else 1
            out.append(source[index:min(end + 1, size)])
            index = end + 1
        elif source.startswith("/*", index):
            close = source.find("*/", index + 2)
            index = size if close < 0 else close + 2
        elif source.startswith("//", index):
            close = source.find("\n", index)
            index = size if close < 0 else close
        else:
            out.append(char)
            index += 1
    return "".join(out)


def strip_css_comments(source):
    return re.sub(r"/\*.*?\*/", "", source, flags=re.S)


def css_rules(block):
    """Selector headers in source order, including those nested in @media."""
    rules, buffer = [], []
    for char in block:
        if char == "{":
            rules.append("".join(buffer).strip())
            buffer = []
        elif char == "}":
            buffer = []
        else:
            buffer.append(char)
    return [rule for rule in rules if rule and not rule.startswith("@")]


def read_index():
    return INDEX.read_text(encoding="utf-8")


def v2_css_block():
    html = read_index()
    start = html.index("Voices V2 (begin)")
    end = html.index("Voices V2 (end)")
    return strip_css_comments(html[html.rindex("/*", 0, start):end])


def tab_ids(root_id):
    """Ids declared between <div id="root_id"> and its matching close tag.

    Counts `div` AND `section`: the V2 browser wraps its list and detail in
    sections, and a div-only counter would run past the tab root and collect
    every id in the following tabs.
    """
    html = read_index()
    start = html.index(f'<div id="{root_id}"')
    depth = 0
    end = len(html)
    for match in re.finditer(r"<(div|section)\b|</(div|section)>", html[start:]):
        depth += 1 if match.group(1) else -1
        if depth == 0:
            end = start + match.end()
            break
    return re.findall(r'\bid="([^"]+)"', html[start:end])


class _Ancestors(HTMLParser):
    """Records the open-element chain at the moment #voicesv2-tab starts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.v2_ancestors = None

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == V2_TAB:
            self.v2_ancestors = [dict(frame[1]) for frame in self.stack]
        self.stack.append((tag, values))

    def handle_endtag(self, tag):
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                del self.stack[position:]
                break


def _v2_files_on_disk():
    """Every V2 source file actually present, so an unlisted file cannot escape
    the source scans below by simply not being named in V2_FILES."""
    return sorted(str(path.relative_to(V2_DIR)).replace("\\", "/")
                  for path in V2_DIR.rglob("*.js"))


def _node_harness():
    return _HARNESS % {"files": repr(list(V2_FILES))}, str(V2_DIR)


class _NodeTestCase(unittest.TestCase):
    """Runs the real V2 files in node against a DOM that throws outside its root."""

    def run_node(self, body, pre="", timeout=20):
        setup, directory = _node_harness()
        code = (setup
                + "\nlet done=false;process.on('beforeExit',()=>assert(done,'assertions must finish'));\n"
                + "(async()=>{\n" + pre + "\nloadAll();\n" + body + "\ndone=true;\n"
                + "})().catch(e=>{console.error(e);process.exitCode=1;});")
        result = subprocess.run(["node", "-e", code, directory],
                                capture_output=True, text=True, timeout=timeout)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout


class NamespaceIsolationTests(_NodeTestCase):
    def test_v2_files_exist_and_declare_nothing_at_top_level(self):
        self.assertEqual(sorted(V2_FILES), _v2_files_on_disk(),
                         "a Voices V2 file exists that is not in the load order")
        for name in V2_FILES:
            source = (V2_DIR / name).read_text(encoding="utf-8")
            with self.subTest(file=name):
                self.assertTrue(source.strip(), f"{name} is empty")
                leaked = [line for line in source.splitlines()
                          if re.match(r"(function\s|var\s|const\s|let\s|class\s)", line)]
                self.assertEqual([], leaked,
                                 f"{name} declares at top level; keep it inside the IIFE")
                lines = [line for line in strip_js_comments(source).splitlines() if line.strip()]
                self.assertTrue(lines[0].startswith("(function"),
                                f"{name} must open with a single IIFE")
                self.assertTrue(lines[-1].endswith(");"),
                                f"{name} must close that IIFE")

    def test_the_only_window_dot_identifier_v2_uses_is_its_own_namespace(self):
        for name in V2_FILES:
            code = strip_js_comments((V2_DIR / name).read_text(encoding="utf-8"))
            for identifier in re.findall(r"window\.([A-Za-z_$][\w$]*)", code):
                with self.subTest(file=name, identifier=identifier):
                    self.assertEqual("VoicesV2", identifier,
                                     f"{name} touches window.{identifier}")

    def test_evaluating_every_v2_file_creates_only_the_namespace_global(self):
        body = r"""
const added=Object.getOwnPropertyNames(vmGlobal).filter(key=>!baselineGlobals.includes(key));
assert.deepStrictEqual(added,['VoicesV2'],'Voices V2 may only add window.VoicesV2');
assert.strictEqual(ctx.window,ctx,'the sandbox models window === globalThis');
assert.strictEqual(Object.keys(ctx.window.VoicesV2).length>0,true);
"""
        self.run_node(body)

    def test_namespace_publishes_only_the_documented_phase_zero_surface(self):
        body = r"""
const ns=ctx.window.VoicesV2;
assert.deepStrictEqual(Object.keys(ns).sort(),['NAMESPACE','ROOT_DIR','api','canSaveVoice',
  'characterSummary','contains','core','describeError','dispatch','escape','getRoot','getState',
  'isMounted','labels','library','libraryFilters','libraryVoices','librarySummary','lifecycle',
  'mount','notify','notifyFailure','panels','phase','refresh','root','select','selectors',
  'selectedCharacter','state','states','subscribe','unmount','visibleCharacters','voiceDraft',
  'voiceSaveState']);
assert.strictEqual(ns.phase,4);
assert.strictEqual(ns.root,'voicesv2-tab');
assert.strictEqual(ns.core.ROOT_ID,'voicesv2-tab');
assert(Object.isFrozen(ns.api),'the API boundary must not be rewritable');
assert.deepStrictEqual(Object.keys(ns.api.PATHS),
  ['characters','favorite','voices','command','previews']);
for(const name of ['mount','refresh','unmount','isMounted','select','subscribe','dispatch',
  'visibleCharacters','characterSummary','selectedCharacter','voiceDraft','canSaveVoice',
  'voiceSaveState','libraryVoices','librarySummary']){
  assert.strictEqual(typeof ns[name],'function',name);
}
for(const panel of ['toolbar','charactersPanel','detailPanel','assignmentPanel','library']){
  assert(ns.panels[panel],'missing panel '+panel);
}
"""


class DomIsolationTests(unittest.TestCase):
    def test_v2_tab_is_a_sibling_of_the_voices_tab_not_a_child(self):
        parser = _Ancestors()
        parser.feed(read_index())
        self.assertIsNotNone(parser.v2_ancestors, "#voicesv2-tab is missing from index.html")
        classes = [set((frame.get("class") or "").split()) for frame in parser.v2_ancestors]
        self.assertFalse(any("tab-content" in group for group in classes),
                         f"the V2 tab must not live inside another tab body: {parser.v2_ancestors}")
        ids = [frame.get("id") for frame in parser.v2_ancestors]
        self.assertNotIn("voices-tab", ids, "the V2 tab must not be nested in the Voices tab")

    def test_v2_tab_declares_only_v2_owned_ids_and_shares_none_with_voices(self):
        v2_ids = tab_ids(V2_TAB)
        voices_ids = tab_ids("voices-tab")
        self.assertTrue(v2_ids, "the V2 tab must declare its regions")
        for element_id in v2_ids:
            with self.subTest(id=element_id):
                self.assertTrue(element_id.startswith(V2_ID_PREFIX),
                                f"{element_id} is not V2-owned; prefix it with {V2_ID_PREFIX}")
        self.assertEqual(set(), set(v2_ids) & set(voices_ids),
                         "the two tabs must not share an element id")

    def test_v2_tab_does_not_reuse_the_voices_card_markup(self):
        body = read_index()
        start = body.index(f'<div id="{V2_TAB}"')
        v2_markup = body[start:start + 4000]
        self.assertNotIn("voice-card", v2_markup)
        for target in VOICES_DOM_TARGETS:
            with self.subTest(target=target):
                self.assertNotIn(target, v2_markup)

    def test_v2_nav_item_exists_exactly_once(self):
        html = read_index()
        self.assertEqual(1, html.count('data-tab="voicesv2"'))
        self.assertEqual(1, html.count('href="#voicesv2"'))
        self.assertEqual(1, html.count(f'<div id="{V2_TAB}" class="tab-content"'))
        # setup owns aria-current; the new tab must not claim to be current.
        self.assertEqual(1, html.count('aria-current="page"'))
        self.assertNotRegex(html, r'data-tab="voicesv2"[^>]*aria-current')

    def test_navigation_calls_only_mount_and_leaves_the_voices_branch_alone(self):
        core = (STATIC / "js" / "app-core.js").read_text(encoding="utf-8")
        start = core.index("selectedLink.dataset.tab === 'voices'")
        block = core[start:core.index("selectedLink.dataset.tab === 'designer'", start)]
        self.assertIn("loadVoices(false);", block, "the Voices branch must be unchanged")
        self.assertIn("VoicesV2.mount();", block)
        self.assertEqual(1, core.count("VoicesV2."),
                         "navigation must reference Voices V2 exactly once")


class CssIsolationTests(unittest.TestCase):
    def test_every_v2_rule_is_scoped_to_the_v2_root(self):
        block = v2_css_block()
        rules = css_rules(block)
        self.assertTrue(rules, "the V2 CSS block should contain at least one rule")
        for selector in rules:
            with self.subTest(selector=selector):
                self.assertTrue(selector.startswith(f"#{V2_TAB}"),
                                f"unscoped V2 selector: {selector}")
        # A selector list wrapped over two lines would hide its first member from
        # the check above, so a V2 rule must keep its whole selector on one line.
        for line in block.splitlines():
            stripped = line.strip()
            with self.subTest(line=stripped):
                self.assertFalse(stripped.endswith(","),
                                 "keep a selector list on one line so its scope is checkable")

    def test_v2_css_declares_no_colour_of_its_own_and_no_theme_override(self):
        block = v2_css_block()
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
        self.assertNotIn("!important", block)
        self.assertNotIn("[data-theme", block)

    def test_v2_css_only_uses_tokens_the_page_defines(self):
        html = read_index()
        root_block = html[html.index(":root {"):html.index("\n        }", html.index(":root {"))]
        defined = set(re.findall(r"(--[\w-]+)\s*:", root_block))
        used = set(re.findall(r"var\((--[\w-]+)\)", v2_css_block()))
        self.assertTrue(used, "the V2 block should use the shared tokens")
        self.assertEqual(set(), used - defined, "undefined CSS custom property")

    def test_v2_css_block_is_balanced_and_bounded_by_its_markers(self):
        block = v2_css_block()
        self.assertEqual(block.count("{"), block.count("}"), "unbalanced braces")
        self.assertEqual(1, block.count(f"#{V2_TAB} .vv2-card"))
        self.assertNotIn("</style>", block, "the markers must not span the style element")


class JsIsolationTests(unittest.TestCase):
    def _code(self, name):
        return strip_js_comments((V2_DIR / name).read_text(encoding="utf-8"))

    def test_no_v2_file_calls_a_voices_page_symbol(self):
        for name in V2_FILES:
            code = self._code(name)
            for symbol in VOICES_PAGE_SYMBOLS:
                with self.subTest(file=name, symbol=symbol):
                    self.assertNotRegex(code, rf"\b{re.escape(symbol)}\b")

    def test_no_v2_file_names_a_voices_dom_target(self):
        for name in V2_FILES:
            code = self._code(name)
            for target in VOICES_DOM_TARGETS:
                with self.subTest(file=name, target=target):
                    self.assertNotIn(target, code)

    def test_the_only_id_v2_looks_up_is_its_own_root(self):
        for name in V2_FILES:
            code = self._code(name)
            for call in re.findall(r"getElementById\(([^)]*)\)", code):
                with self.subTest(file=name, call=call):
                    self.assertIn("ROOT_ID", call,
                                  f"{name} looks up an element by a literal id: {call}")

    def test_the_only_api_path_v2_uses_is_declared_in_its_boundary_table(self):
        for name in V2_FILES:
            code = self._code(name)
            with self.subTest(file=name):
                self.assertNotIn("/api/", code.replace("/api/voices-v2/", ""),
                                 "a V2 URL must be declared in api.js's PATHS table")
        self.assertIn("/api/voices-v2/", self._code("api.js"))

    def test_only_core_calls_shared_helpers_and_only_api_calls_the_http_client(self):
        for name in V2_FILES:
            code = self._code(name)
            if name != "core.js":
                for helper in SHARED_HELPERS:
                    with self.subTest(file=name, helper=helper):
                        self.assertNotRegex(code, rf"\b{helper}\(",
                                            f"{name} must reach {helper} through core.js")
            if name != "api.js":
                with self.subTest(file=name):
                    self.assertNotRegex(code, r"\bAPI\.",
                                        f"{name} must call namespace.api, not API, directly")

    def test_v2_adopts_the_existing_save_contract_rather_than_inventing_one(self):
        """Phase 2 writes, so this is no longer "V2 has no save tokens" - it is
        "V2 sends the tokens the existing contract defines, and does not compute
        its own or write through a second path".

        The three failure modes worth a gate:
        - computing a revision client-side, so V2's idea of staleness drifts from
          the server's;
        - posting straight to /api/voice_config/save with a rebuilt entry, which
          is exactly the field-stripping the Phase 0 design avoided;
        - renaming the tokens, which would silently disable the server's guard.
        """
        code = "".join(self._code(name) for name in V2_FILES)
        # The wire names come from the shared API helper's request shape.
        api = self._code("api.js")
        self.assertIn("revision: command.revision", api)
        self.assertIn("book_token: command.bookToken", api)
        self.assertIn("revision", code, "V2 must present the revision it was given")
        self.assertIn("bookToken", code, "V2 must present the book token it was given")
        # Nothing computes a revision, and nothing bypasses the V2 command route.
        # `scriptSha256` is a field name the projection hands over, not a hash V2
        # performs, so the ban is on the call forms rather than on the substring.
        for banned in ("createHash", "subtle.digest", "crypto.", "digest("):
            self.assertNotIn(banned, code)
        self.assertNotIn("/api/voice_config/save", code)
        self.assertNotIn("/api/voice_config/", code)

    def test_v2_scripts_load_after_core_and_before_reports(self):
        html = read_index()
        order = [html.index(f'src="/static/js/{path}?v=__APP_BUILD__"')
                 for path in ("app-core.js", "app-voicelab.js", "voices-v2/core.js",
                              "voices-v2/index.js", "app-reports.js")]
        self.assertEqual(sorted(order), order)

    def test_v2_bootstrap_is_the_last_v2_tag_and_no_tag_defers(self):
        html = read_index()
        positions = [(name, html.index(f'src="/static/js/voices-v2/{name}?v=__APP_BUILD__"'))
                     for name in V2_FILES]
        self.assertEqual("index.js", max(positions, key=lambda row: row[1])[0],
                         "the V2 bootstrap must be its last script")
        for name, position in positions:
            window = html[max(0, position - 45):position + 80]
            with self.subTest(file=name):
                for banned in ("defer", "async", 'type="module"'):
                    self.assertNotIn(banned, window)


class StoreIsolationTests(_NodeTestCase):
    def test_store_holds_only_data_and_never_a_dom_node(self):
        self.run_node(r"""
const state=ctx.window.VoicesV2.getState();
assert.deepStrictEqual(Object.keys(state).sort(),
  ['catalogue','characters','draft','filters','library','libraryContext','libraryFilters',
   'librarySearch','librarySelection','librarySort','meta','orphans','preview','save','selection',
   'ui']);
assert.deepStrictEqual(Object.keys(state.ui).sort(),['error','loadedAt','loading','mounted']);
assert.deepStrictEqual(Object.keys(state.selection).sort(),['blocked','key','pending']);
assert.deepStrictEqual(Object.keys(state.draft).sort(),
  ['characterKey','cleared','dirty','voiceId']);
assert.deepStrictEqual(Object.keys(state.save).sort(),['code','message','savedAt','state']);
assert.deepStrictEqual(Object.keys(state.preview).sort(),
  ['activeJob','jobs','playback','polling']);
assert.deepStrictEqual(Object.keys(state.libraryContext).sort(),
  ['ageGroup','ageless','gender','key','name']);
const walk=value=>{if(!value||typeof value!=='object')return;
  assert(!value.nodeType,'a DOM node reached the store');Object.values(value).forEach(walk);};
walk(state);
assert(!JSON.stringify(state).includes('voicesv2'),'state must not capture the tab root');
""")

    def test_dispatch_is_the_only_writer_and_notifies_the_changed_path(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2,seen=[];
const stop=V2.subscribe('*',(s,path)=>seen.push(path));
V2.dispatch({type:'characters/set',characters:[{name:'MIRA'}]});
assert.deepStrictEqual(plain(V2.getState().characters),[{name:'MIRA'}]);
assert.deepStrictEqual(seen,['characters']);
seen.length=0;V2.dispatch({type:'ui/error',error:'boom'});
assert.deepStrictEqual(seen,['ui.error']);
assert.strictEqual(V2.getState().ui.error,'boom');
V2.dispatch({type:'ui/error',error:null});
assert.strictEqual(V2.getState().ui.error,null);
seen.length=0;stop();V2.dispatch({type:'orphans/set',orphans:[{name:'GHOST'}]});
assert.deepStrictEqual(seen,[],'unsubscribe must stop notifications');
""")

    def test_a_slice_subscription_hears_about_its_subtree_only(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2,ui=[],chars=[];
V2.subscribe('ui',(s,p)=>ui.push(p));V2.subscribe('characters',(s,p)=>chars.push(p));
V2.dispatch({type:'characters/set',characters:[]});
V2.dispatch({type:'ui/loading',loading:true});
V2.dispatch({type:'ui/loaded'});
assert.deepStrictEqual(chars,['characters']);
assert.deepStrictEqual(ui,['ui.loading','ui.loadedAt']);
""")

    def test_commands_that_would_put_the_dom_or_a_wrong_type_in_state_are_refused(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
assert.throws(()=>V2.dispatch({type:'characters/set',characters:root}),/needs an array/);
assert.throws(()=>V2.dispatch({type:'characters/set',characters:{0:1,length:1}}),/needs an array/);
assert.throws(()=>V2.dispatch({type:'ui/loading',loading:'yes'}),/needs a boolean/);
assert.throws(()=>V2.dispatch({type:'characters/merge',characters:[]}),/does not implement/);
assert.throws(()=>V2.dispatch(null),/string type/);
assert.throws(()=>V2.dispatch({}),/string type/);
assert.deepStrictEqual(plain(V2.getState().characters),[],'a refused command must not mutate');
""")

    def test_reset_clears_projections_but_keeps_the_mount_flag_and_subscribers(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;let ticks=0;V2.subscribe('*',()=>ticks++);
V2.dispatch({type:'ui/mounted',mounted:true});
V2.dispatch({type:'characters/set',characters:[{name:'MIRA'}]});
V2.dispatch({type:'ui/error',error:'x'});
V2.state.reset();
assert.deepStrictEqual(plain(V2.getState().characters),[]);
assert.strictEqual(V2.getState().ui.error,null);
assert.strictEqual(V2.getState().ui.mounted,true,'reset must not tear down a mounted tab');
V2.dispatch({type:'orphans/set',orphans:[]});
assert.strictEqual(ticks,4,'reset must not orphan a subscriber');
""")

    def test_select_is_a_pure_read_and_rejects_a_non_function(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
V2.dispatch({type:'characters/set',characters:[{name:'A'},{name:'B'}]});
assert.deepStrictEqual(plain(V2.select(s=>s.characters.map(c=>c.name))),['A','B']);
/* select reads the live store; it does not copy. What keeps that safe is that
   dispatch is the only writer and rejects values that are not plain data. */
assert.strictEqual(V2.select(s=>s.characters),V2.getState().characters);
assert.throws(()=>V2.select('characters'),/selector function/);
""")


class LifecycleBehaviourTests(_NodeTestCase):
    def test_a_hidden_tab_does_nothing_at_page_load(self):
        """Nothing may run at load time while the tab is hidden, so the tab costs
        a page that never opens it nothing."""
        self.run_node(r"""
assert.strictEqual(ctx.window.VoicesV2.isMounted(),false);
assert.deepStrictEqual(apiCalls,[],'a hidden tab must not read anything at page load');
await turn();
assert.deepStrictEqual(apiCalls,[],'no deferred mount may fire for a hidden tab');
""")

    def test_a_tab_already_visible_when_the_scripts_run_still_mounts(self):
        """The fallback path. restoreTab() runs at the end of app-reports.js and
        normally mounts an already-visible tab, but if the script order ever
        changed this must degrade to a redundant mount() rather than a blank tab."""
        self.run_node(r"""
assert.strictEqual(ctx.window.VoicesV2.isMounted(),true);
assert.strictEqual((root.listeners.click||[]).length,1);
assert.strictEqual(characterCalls().length,1);
assert.strictEqual(catalogueCalls().length,1,'the catalogue is read once at load');
await turn();
assert.strictEqual(apiCalls.length,2,'the load-time guard must read neither twice');
""", pre="root.style.display='block';")

    def test_mount_runs_once_binds_one_listener_and_reads_through_the_api_boundary(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
assert.strictEqual(V2.isMounted(),false);
/* Concurrent activation, e.g. a double click on the nav link. */
await Promise.all([V2.mount(),V2.mount(),V2.mount()]);
assert.strictEqual(V2.isMounted(),true);
assert.strictEqual((root.listeners.click||[]).length,1,
  'repeated navigation must not stack listeners');
assert.deepStrictEqual(characterCalls(),['/api/voices-v2/characters'],
  'concurrent mounts must collapse into one read');
/* Sequential re-entry, e.g. leaving the tab and coming back. */
await V2.mount();
assert.strictEqual(characterCalls().length,2,'re-entering the tab re-reads the projection');
assert.strictEqual(catalogueCalls().length,1,'the catalogue is not re-read on re-entry');
assert.strictEqual((root.listeners.click||[]).length,1,'a re-read must not re-bind');
assert(apiCalls.every(p=>p.startsWith('/api/voices-v2/')),
  'V2 must not call a Voices endpoint');
""")

    def test_mount_without_its_tab_is_inert(self):
        self.run_node(r"""
document.getElementById=id=>{if(id!='voicesv2-tab')throw Error('unexpected lookup '+id);return null;};
const V2=ctx.window.VoicesV2;
assert.strictEqual(await V2.mount(),false);
assert.strictEqual(V2.isMounted(),false);
assert.deepStrictEqual(apiCalls,[]);
""")

    def test_a_failed_read_reports_inline_and_through_shared_error_reporting(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
const held=holdNext('/api/voices-v2/characters');
const pending=V2.mount();await turn();
held.reject(Object.assign(Error('backend unreachable'),{status:503,detail:'unavailable'}));
assert.strictEqual(await pending,false);
assert.strictEqual(V2.getState().ui.loading,false);
assert(V2.getState().ui.error.includes('backend unreachable'));
assert(status.innerHTML.includes('alert-danger'),
  'the error must be visible in the tab, not only as a toast');
assert(status.innerHTML.includes('data-voicesv2-action="retry"'),
  'a failed read must offer a retry');
assert.strictEqual(actionErrors.length,1);
assert(actionErrors[0].recovery.includes('Voices V2 is a separate workspace'));
assert.strictEqual(live.textContent,'Projection unavailable');
""")

    def test_unmount_removes_the_listener_and_discards_a_read_already_in_flight(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
const held=holdNext('/api/voices-v2/characters');
const pending=V2.mount();await turn();
assert.strictEqual(V2.unmount(),true);
assert.strictEqual((root.listeners.click||[]).length,0);
assert.strictEqual(root.removed.click,1);
const renders=status.renderCount;
held.resolve({schema_version:1,book:{script_present:true},traits_available:true,
  characters:[{name:'LATE'}],orphans:[]});
assert.strictEqual(await pending,false,'an unmounted read must not report success');
assert.strictEqual(status.renderCount,renders,'an unmounted read must not paint');
assert.deepStrictEqual(plain(V2.getState().characters),[]);
assert.strictEqual(V2.unmount(),false,'unmount is idempotent');
""")

    def test_a_reload_click_inside_the_root_re_reads_and_others_do_not(self):
        self.run_node(r"""
const V2=ctx.window.VoicesV2;
await V2.mount();await turn();
assert.strictEqual(characterCalls().length,1);
root.fire('click',{target:reload});
await turn();await turn();
assert.strictEqual(characterCalls().length,2,'a V2 action must re-read');
root.fire('click',{target:node('characters')});
root.fire('click',{target:makeNode('button',{})});
root.fire('click',{target:null});
await turn();await turn();
assert.strictEqual(characterCalls().length,2,'an unrecognised click must do nothing');
""")


class RouterIsolationTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI

        from routers import (benchmark, dataset_builder, editor, lora, preparer, script,
                            scripts_library, system, voice_design, voice_library, voices,
                            voices_v2, voicelab)

        self.FastAPI = FastAPI
        self.v2 = voices_v2
        self.existing = (system, script, voices, editor, scripts_library, voice_library,
                         voice_design, lora, dataset_builder, preparer, voicelab, benchmark)

    def _routes(self, module):
        return {(method, route.path)
                for route in module.router.routes
                for method in (getattr(route, "methods", []) or [])}

    def test_v2_router_owns_only_its_own_prefix(self):
        for method, path in self._routes(self.v2):
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/api/voices-v2/"),
                                f"Voices V2 registered {path} outside its prefix")
        self.assertEqual({("GET", "/api/voices-v2/characters"),
                          ("GET", "/api/voices-v2/voices"),
                          ("POST", "/api/voices-v2/favorite"),
                          ("POST", "/api/voices-v2/command"),
                          ("POST", "/api/voices-v2/previews"),
                          ("GET", "/api/voices-v2/previews/{job_id}"),
                          ("POST", "/api/voices-v2/previews/{job_id}/cancel")},
                         self._routes(self.v2))

    def test_v2_adds_no_route_to_any_existing_router(self):
        app = self.FastAPI()
        app.include_router(self.v2.router)
        for module in self.existing:
            for route in module.router.routes:
                with self.subTest(module=module.__name__, path=route.path):
                    self.assertNotIn(route.path,
                                     {path for _, path in self._routes(self.v2)})

    def test_v2_does_not_shadow_any_registered_route(self):
        existing = set()
        for module in self.existing:
            existing |= self._routes(module)
        self.assertEqual(set(), existing & self._routes(self.v2),
                         "including V2 must not shadow an existing route")

    def test_the_projection_read_writes_nothing_and_is_shaped_for_the_browser(self):
        """Replaces the Phase 0 placeholder check: the endpoint now returns a real
        projection, so the guarantee worth keeping is that reading it has no side
        effect and cannot hand the browser a write surface."""
        import tempfile
        from pathlib import Path

        from fastapi.testclient import TestClient

        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(Path(tmp).rglob("*"))
            app = self.FastAPI()
            app.include_router(self.v2.router)
            with TestClient(app) as client:
                response = client.get("/api/voices-v2/characters")
            self.assertEqual(200, response.status_code)
            payload = response.json()
            self.assertEqual(before, sorted(Path(tmp).rglob("*")),
                             "reading the projection must not write")
            for key in ("schema_version", "book", "traits_available", "vocabularies",
                        "characters", "orphans", "counts", "major_line_threshold"):
                self.assertIn(key, payload)
            self.assertEqual(payload["counts"],
                             {"characters": len(payload["characters"]),
                              "orphans": len(payload["orphans"])},
                             "counts must agree with the lists they describe")
            # The browser must never receive the stored configuration verbatim:
            # no ref_audio path, no seed, no style timeline, nothing it could
            # mistake for an editable field.
            for record in payload["characters"] + payload["orphans"]:
                self.assertNotIn("ref_audio", record)
                self.assertNotIn("seed", record)
                self.assertNotIn("style_timeline", record)
                self.assertNotIn("character_style", record)
                self.assertIn("problems", record)

    def test_the_registered_app_serves_the_v2_route_alongside_the_voices_routes(self):
        import app as app_module

        served = {(method, route.path) for route in app_module.app.routes
                  for method in (getattr(route, "methods", []) or [])}
        self.assertIn(("GET", "/api/voices-v2/characters"), served)
        self.assertIn(("GET", "/api/voices"), served)
        self.assertIn(("GET", "/api/voice_config/snapshot"), served)
        self.assertFalse({path for _, path in served if path.startswith("/api/voices-v2/")}
                         & {path for _, path in served if path.startswith("/api/voices/")})


# ---------------------------------------------------------------------------
# Node harness: the real V2 files, a DOM that throws on any id but its own root,
# and a controllable API stub.
# ---------------------------------------------------------------------------

_HARNESS = r"""
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const dir=process.argv[1];
const files=%(files)s;
function makeNode(tag,attrs){
  attrs=attrs||{};
  return {tag,attrs:Object.assign({},attrs),style:{display:'block'},innerHTML:'',textContent:'',
    listeners:{},removed:{},renderCount:0,
    addEventListener(type,fn){(this.listeners[type]=this.listeners[type]||[]).push(fn);},
    removeEventListener(type,fn){const l=this.listeners[type]||[];const i=l.indexOf(fn);
      if(i>=0){l.splice(i,1);}this.removed[type]=(this.removed[type]||0)+1;},
    fire(type,event){(this.listeners[type]||[]).slice().forEach(fn=>fn(event));},
    getAttribute(name){return Object.prototype.hasOwnProperty.call(this.attrs,name)?this.attrs[name]:null;},
    setAttribute(name,value){this.attrs[name]=String(value);},
    closest(sel){return sel==='[data-voicesv2-action]'&&this.attrs['data-voicesv2-action']!=null?this:null;}};
}
function trackText(node){Object.defineProperty(node,'textContent',{configurable:true,
  get(){return this._text||'';},set(v){this._text=v;this.renderCount++;}});}
const root=makeNode('div',{id:'voicesv2-tab'});
root.style.display='none';
/* Every V2 region the browser owns. The harness registers them all and throws on
   an unregistered selector, so a panel that reaches for an element V2 does not
   own fails the test instead of quietly returning null in production. */
const regionNames=['status','live','search','counts','characters','detail','voice-editor',
  'reset-filters','library','library-context','library-search','library-count',
  'library-position','library-previous','library-next','library-random',
  'library-chips','library-list','library-live',
  'filter-scope','filter-gender','filter-ageGroup','filter-assigned','filter-ready',
  'filter-personaStatus','filter-priority','filter-problems','filter-sort',
  'library-filter-gender','library-filter-ageGroup','library-filter-kind',
  'library-filter-availability','library-filter-favorite','library-filter-sort'];
const regions={};
const descendants=[];
regionNames.forEach(name=>{
  const node=makeNode(name==='search'?'input':'div',{'data-voicesv2-region':name});
  node.value='';node.disabled=false;
  regions['[data-voicesv2-region="'+name+'"]']=node;
  descendants.push(node);
});
const reload=makeNode('button',{'data-voicesv2-action':'reload'});
descendants.push(reload);
root.querySelector=function(sel){
  if(sel==='[data-voicesv2-action]')return null;
  const node=regions[sel];
  if(!node)throw Error('unregistered V2 selector: '+sel);
  return node;
};
root.contains=function(node){return descendants.indexOf(node)>=0;};
Object.defineProperty(regions['[data-voicesv2-region="status"]'],'innerHTML',{configurable:true,
  get(){return this._html||'';},set(v){this._html=v;this.renderCount++;}});
const status=regions['[data-voicesv2-region="status"]'];
const live=regions['[data-voicesv2-region="live"]'];
/* Region lookup by bare name, so a test reads `node('characters')` instead of
   repeating the attribute selector the production code uses. */
const node=name=>regions['[data-voicesv2-region="'+name+'"]'];
/* An action button that really lives inside the tab, so a delegated click on it
   is treated by core.contains() as being inside the root. */
function actionButton(action){
  const el=makeNode('button',{'data-voicesv2-action':action});
  descendants.push(el);
  return el;
}
['live','search','counts','characters','detail','voice-editor'].forEach(name=>{
  trackText(regions['[data-voicesv2-region="'+name+'"]']);
});
/* Any other element id throws, so a V2 lookup that leaves its own tab fails the
   test instead of quietly returning null in production. */
const byId={'voicesv2-tab':root};
const document={getElementById(id){
  if(!Object.prototype.hasOwnProperty.call(byId,id))throw Error('V2 must not look up #'+id);
  return byId[id];},createElement(tag){return makeNode(tag,{});}};
const apiCalls=[],toasts=[],actionErrors=[];
/* Phase 2 added a second read (the assignable voice catalogue), so tests that
   care about the projection count characters only. Asserting the total instead
   would make every lifecycle test depend on the catalogue's existence. */
const characterCalls=()=>apiCalls.filter(p=>p.startsWith('/api/voices-v2/characters'));
const catalogueCalls=()=>apiCalls.filter(p=>p.startsWith('/api/voices-v2/voices'));
let payload={schema_version:1,book:{book_id:'B',script_present:true},traits_available:true,
  characters:[],orphans:[],vocabularies:{genders:['male'],age_groups:[],problem_codes:[]},
  counts:{characters:0,orphans:0}};
let deferArmed=false,deferPrefix='',resolveNext=null,rejectNext=null;
const API={get(path){
  apiCalls.push(path);
  /* Deferring is armed explicitly and scoped to a prefix, so a test that means to
     hold the projection read cannot accidentally hold the catalogue read that
     mount() issues first - and no request is ever held by accident. */
  if(deferArmed&&(!deferPrefix||path.startsWith(deferPrefix))){
    deferArmed=false;
    return new Promise((res,rej)=>{resolveNext=res;rejectNext=rej;});
  }
  return Promise.resolve(JSON.parse(JSON.stringify(payload)));
}};
function escapeHtml(value){return String(value).replace(/[&<>"']/g,
  ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));}
const ctx={window:null,document,console,API,escapeHtml,
  showToast:(m,t,d)=>{toasts.push({message:m,type:t,duration:d});},
  showActionError:(a,e,r)=>{actionErrors.push({action:a,error:e,recovery:r});}};
ctx.window=ctx;
vm.createContext(ctx);
/* The vm's own global, for asserting which globals the V2 files created.
   Reading `globalThis` from this scope would return node's global instead. */
const vmGlobal=vm.runInContext('globalThis',ctx);
/* Captured before any V2 file runs, so the delta is attributable to V2. */
const baselineGlobals=Object.getOwnPropertyNames(vmGlobal).sort();
/* Round-trips a value out of the vm so assert.deepStrictEqual compares values
   rather than cross-realm prototypes. A value produced inside the vm (a
   selector's result, the store's arrays) is a vm-realm Array whose prototype
   differs from this script's; JSON gives both sides the prototype of the realm
   that wrote the expectation. A browser tab has one realm, so this is a harness
   artefact, not behaviour under test. */
const plain=value=>JSON.parse(JSON.stringify(value));
function holdNext(prefix){
  deferArmed=true;deferPrefix=prefix||'';
  return{resolve:v=>{const r=resolveNext;resolveNext=null;rejectNext=null;r(v);},
         reject:e=>{const r=rejectNext;resolveNext=null;rejectNext=null;r(e);}};
}
function loadAll(){for(const name of files){vm.runInContext(fs.readFileSync(dir+'/'+name,'utf8'),ctx);}}
function turn(){return new Promise(resolve=>setImmediate(resolve));}
"""


if __name__ == "__main__":
    unittest.main()
