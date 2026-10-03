"""Voice Library v2-A: browsing & discovery.

Runs the REAL catalog/filter/sort/chip functions out of app-core.js against a
stub DOM, so search, combined filters, clearing, sorting, favourites filtering,
empty results, details and character/state context are all exercised as shipped.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)
JS = os.path.join(APP, 'static', 'js', 'app-core.js')

failures = []
checks = 0


def check(label, cond, extra=''):
    global checks
    checks += 1
    if not cond:
        failures.append(label)
    print(('  OK   ' if cond else '  FAIL ') + label + (('   ' + str(extra)) if extra else ''))


def extract_fn(text, sig):
    a = text.index(sig)
    i = text.index('{', a)
    d = 0
    q = None
    tp = False
    for j in range(i, len(text)):
        c = text[j]
        if q:
            if c == '\\':
                j += 1
                continue
            if c == q:
                q = None
            continue
        if not tp:
            if c in '"\'':
                q = c
            elif c == '`':
                tp = True
            elif c == '/' and text[j + 1:j + 2] == '/':
                j = text.index('\n', j)
            elif c == '{':
                d += 1
            elif c == '}':
                d -= 1
                if d == 0:
                    return text[a:j + 1]
        else:
            if c == '\\':
                j += 1
                continue
            if c == '`':
                tp = False
    raise ValueError('unbalanced ' + sig)


src = open(JS, encoding='utf-8').read()

# ---------------------------------------------------------------- test harness
LORA = [
    {"id": "builtin_watson", "name": "Watson", "builtin": True, "downloaded": False,
     "gender": "male", "inferred_gender": "male", "inferred_age": "adult",
     "description": "Warm, measured baritone for narration",
     "favorite": False, "preview_audio_url": None, "created": "2026-01-02T10:00:00"},
    {"id": "husky_alto_40s_f", "name": "Husky Alto", "builtin": True, "downloaded": True,
     "gender": None, "inferred_gender": "female", "inferred_age": "young_adult",
     "description": "Husky bright warm alto, expansive and luminous, cinematic",
     "favorite": False, "preview_audio_url": "/builtin_lora/husky_alto_40s_f/preview_sample.wav",
     "created": "2026-03-04T10:00:00"},
    {"id": "warm_tenor_m", "name": "Warm Tenor", "builtin": True, "downloaded": True,
     "gender": "male", "inferred_gender": "male", "inferred_age": "teen",
     "description": "Soft warm tenor for young heroes",
     "favorite": True, "preview_audio_url": None, "created": "2026-02-03T10:00:00"},
    {"id": "solo_f", "name": "Solo Female", "builtin": False, "downloaded": True,
     "gender": None, "inferred_gender": "female", "inferred_age": "adult",
     "description": "Neutral narrator voice",
     "favorite": False, "preview_audio_url": None, "created": "2026-05-06T10:00:00"},
]
CLONE = []
DESIGN = [
    {"id": "d1", "name": "Serena", "description": "Warm, soft, cinematic narrator",
     "filename": "serena.wav", "sample_text": "Hello. I wasn't expecting you here."},
]

def extract_const(text, name):
    """Grab a top-level `const NAME = <literal>;` (object or scalar)."""
    a = text.index('const ' + name + ' =')
    j = text.index(';', a)
    return text[a:j + 1]


tag_max = extract_const(src, 'VOICE_TAG_MAX')
parts = [extract_const(src, n) for n in
         ('VOICE_LIBRARY_AGE_LABELS', 'VOICE_LIBRARY_GENDER_LABELS',
          'VOICE_LIBRARY_TYPE_LABELS')]
parts.append(tag_max)
parts += [extract_fn(src, s) for s in
          ('function voiceLibraryAgeLabel(', 'function voiceLibraryGenderLabel(',
           'function normalizeVoiceAge(', 'function normalizeVoiceGender(',
           'function voiceTagsFrom(', 'function voiceSearchText(',
           'function buildVoiceLibraryCatalog(', 'function readVoiceLibraryFilters(',
           'function voiceLibraryMatches(', 'function sortVoiceLibrary(',
           'function renderVoiceLibraryActiveFilters(', 'function voiceLibraryCardMarkup(',
           'function renderVoiceLibrary(', 'function applyVoiceLibraryContextFilters(')]

harness = r'''
const LORA = __LORA__, CLONE = [], DESIGN = __DESIGN__;
const els = {};
['vl-search', 'vl-gender', 'vl-age', 'vl-type', 'vl-favorites', 'vl-sort',
 'voice-library-count', 'voice-library-context', 'voice-library-grid',
 'vl-active-filters', 'voice-library-audio', 'voice-library-card']
  .forEach(id => { els[id] = { id, value: '', style: {}, innerHTML: '', textContent: '',
                               options: [], classList: { add(){}, remove(){} } }; });
const sb = {
  console, window: {}, AVAILABLE_VOICES: ['Aiden', 'Ryan'],
  document: { getElementById: id => els[id] || null, querySelector: () => null,
              querySelectorAll: () => [], createElement: () => ({ set innerHTML(v){this._h=v;}, get firstElementChild(){return null;} }) },
  escapeHtml: s => String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'),
  showToast: () => {}, CSS: { escape: s => s },
  API: { get: async () => [], post: async () => ({}) },
  setTimeout: (fn) => fn(), clearTimeout: () => {},
};
sb.window.escapeHtml = sb.escapeHtml;
sb.window._loraModelsCache = LORA;
sb.window._cloneVoicesCache = CLONE;
sb.window._designedVoicesCache = DESIGN;
// NB: the browser state global is `window._voiceBrowser`, NOT
// `window._voiceLibrary` - the latter belongs to the Series Cast loader
// (loadCastLibrary) and would wipe the catalog if shared.
sb.window._voiceBrowser = { catalog: [], loaded: true, error: '', sort: 'relevance',
                            detailsKey: '', filterSource: 'user' };
sb.window._libraryContext = null;
vm.createContext(sb);
vm.runInContext(__PARTS__ + `
  ;globalThis.__t = { buildVoiceLibraryCatalog, readVoiceLibraryFilters,
      voiceLibraryMatches, sortVoiceLibrary, voiceLibraryCardMarkup,
      voiceSearchText, voiceLibraryAgeLabel, voiceLibraryGenderLabel,
      renderVoiceLibrary, renderVoiceLibraryActiveFilters, applyVoiceLibraryContextFilters,
      AGE: VOICE_LIBRARY_AGE_LABELS, GENDER: VOICE_LIBRARY_GENDER_LABELS };`, sb);
const T = sb.__t;
const L = sb.window._voiceBrowser;
L.catalog = T.buildVoiceLibraryCatalog();
const setF = (o) => { Object.keys(o).forEach(k => { els['vl-' + k].value = o[k] || ''; }); return T.readVoiceLibraryFilters(); };
const names = (f) => L.catalog.filter(v => T.voiceLibraryMatches(v, f)).map(v => v.name);
const sorted = (f, m) => T.sortVoiceLibrary(L.catalog.filter(v => T.voiceLibraryMatches(v, f)), m).map(v => v.name);
'''

parts_js = ';\n'.join(parts)
harness = (harness
           .replace('__LORA__', json.dumps(LORA))
           .replace('__DESIGN__', json.dumps(DESIGN))
           .replace('__PARTS__', json.dumps(parts_js)))

harness = 'const vm = require("vm");\n' + harness
harness += r'''
const KEYS = ['search', 'gender', 'age', 'type', 'favorites'];
const renderWith = (state) => {
  const savedCatalog = L.catalog, savedLoading = L.loading, savedError = L.error;
  if ('catalog' in state) { L.catalog = state.catalog; }
  if ('loading' in state) { L.loading = state.loading; }
  if ('error' in state) { L.error = state.error; }
  if (state.f) { KEYS.forEach(k => { els['vl-' + k].value = ''; });
                  Object.keys(state.f).forEach(k => { els['vl-' + k].value = state.f[k] || ''; }); }
  T.renderVoiceLibrary();
  const html = els['voice-library-grid'].innerHTML;
  const count = els['voice-library-count'].textContent;
  const chips = els['vl-active-filters'].innerHTML;
  const chipsShown = els['vl-active-filters'].style.display !== 'none';
  L.catalog = savedCatalog; L.loading = savedLoading; L.error = savedError;
  return { html, count, chips, chipsShown };
};
const F = o => { KEYS.forEach(k => { els['vl-' + k].value = ''; });
                 Object.keys(o).forEach(k => { if (k in o) { els['vl-' + k].value = o[k] || ''; } });
                 return T.readVoiceLibraryFilters(); };
const pick = (o, m) => T.sortVoiceLibrary(L.catalog.filter(v => T.voiceLibraryMatches(v, F(o))), m).map(v => v.name);
const one = k => L.catalog.find(v => v.key === k) || {};
const out = {
  catalogSize: L.catalog.length,
  hasSearchText: L.catalog.every(v => typeof v.searchText === 'string' && v.searchText.length > 0),
  sampleText: one('design:d1').sampleText,
  inferredAge: one('lora:husky_alto_40s_f').age,
  inferredGender: one('lora:husky_alto_40s_f').gender,
  createdAt: one('lora:solo_f').createdAt,
  customEntry: !!one('custom:Aiden'),
  source: one('lora:builtin_watson').source,
  ageLabel: T.voiceLibraryAgeLabel('young_adult'),
  genderLabel: T.voiceLibraryGenderLabel('female'),
  allNames: L.catalog.map(v => v.name),

  sWatson:    pick({search: 'watson'}, 'relevance'),
  sLuminous:  pick({search: 'luminous'}, 'relevance'),
  sFemale:    pick({search: 'female'}, 'relevance'),
  sTeen:      pick({search: 'teen'}, 'relevance'),
  sMulti:     pick({search: 'warm female young'}, 'relevance'),
  sNoMatch:   pick({search: 'warm zzz'}, 'relevance'),
  sUpper:     pick({search: 'WATSON'}, 'relevance'),

  fCombo:     pick({gender: 'female', age: 'young_adult', type: 'builtin_lora'}, 'relevance'),
  fFavYes:    pick({favorites: 'yes'}, 'relevance'),
  fFavNo:     pick({favorites: 'no'}, 'relevance'),
  fConflict:  pick({gender: 'male', age: 'young_adult'}, 'relevance'),

  sortName:   pick({}, 'name'),
  sortFav:    pick({}, 'favorites'),
  sortNewest: pick({}, 'newest'),
  sortOldest: pick({}, 'oldest'),
  sortRel:    pick({}, 'relevance'),
};
const card = k => T.voiceLibraryCardMarkup(one(k), null);
out.cardAlto = {
  name: card('lora:husky_alto_40s_f').includes('Husky Alto'),
  desc: card('lora:husky_alto_40s_f').includes('luminous'),
  gender: card('lora:husky_alto_40s_f').includes('Female'),
  age: card('lora:husky_alto_40s_f').includes('Young Adult'),
  tags: card('lora:husky_alto_40s_f').includes('Husky bright warm alto'),
  favorite: card('lora:husky_alto_40s_f').includes('toggleLibraryVoiceFavorite'),
  preview: card('lora:husky_alto_40s_f').includes('previewLibraryVoice'),
  select: card('lora:husky_alto_40s_f').includes('selectLibraryVoice'),
  details: card('lora:husky_alto_40s_f').includes('toggleVoiceLibraryDetails'),
};
out.cardWatson = { notDownloaded: card('lora:builtin_watson').includes('Not downloaded') };

// Contextual filter prefill: call the REAL function, seeded exactly as
// openVoiceLibrary builds the context (gender is the state enum, ageLabel is
// the display label from stateAgeLabel()).
const seed = (ctx) => {
  els['vl-gender'].value = ''; els['vl-age'].value = '';
  T.applyVoiceLibraryContextFilters(ctx);
  return T.readVoiceLibraryFilters();
};
out.ctxTeen = seed({ stateKey: 'MALE|TEEN', gender: 'MALE', ageLabel: 'Teen' });
out.ctxAdultFemale = seed({ stateKey: 'FEMALE|ADULT', gender: 'FEMALE', ageLabel: 'Adult' });
out.ctxMiddleAged = seed({ stateKey: 'MALE|MIDDLE_AGED', gender: 'MALE', ageLabel: 'Middle Aged' });
out.ctxNoState = seed({ stateKey: '', gender: '', ageLabel: '' });

// Error / loading / empty rendering paths.
out.renderError = renderWith({ error: 'Catalog unavailable', loading: false, catalog: [] });
out.renderLoading = renderWith({ error: '', loading: true, catalog: [] });
out.renderEmptyCatalog = renderWith({ error: '', loading: false, catalog: [] });
out.renderNoMatch = renderWith({ error: '', loading: false, catalog: L.catalog,
                                f: { search: 'zzzz', gender: '', age: '', type: '', favorites: '' } });
out.renderNormal = renderWith({ error: '', loading: false, catalog: L.catalog,
                                f: { search: '', gender: '', age: '', type: '', favorites: '' } });
console.log(JSON.stringify(out));
'''

tmp = os.path.join(ROOT, '_vl_probe.js')
open(tmp, 'w', encoding='utf-8').write(harness)
env = dict(os.environ, PYTHONIOENCODING='utf-8')
res = subprocess.run(['node', tmp], capture_output=True, env=env)
res = subprocess.CompletedProcess(res.args, res.returncode,
                                 res.stdout.decode('utf-8', 'replace'),
                                 res.stderr.decode('utf-8', 'replace'))
os.unlink(tmp)
if res.returncode != 0:
    print('NODE ERROR:', res.stderr[:1500])
    print('FAILURES: harness did not run')
    sys.exit(1)
R = json.loads(res.stdout.strip())

print('=== catalog ===')
check('catalog built', R['catalogSize'] == 7, R['catalogSize'])
check('every entry has a precomputed searchText', R['hasSearchText'])
check('inferred age used, not raw', R['inferredAge'] == 'young_adult')
check('inferred gender derived where raw was None', R['inferredGender'] == 'female')
check('custom presets included', R['customEntry'])
check('source label present', bool(R['source']), R['source'])
check('design sample_text carried for preview text', R['sampleText'].startswith('Hello.'))
check('created timestamp captured for date sorting', bool(R['createdAt']))
check('label helpers', R['ageLabel'] == 'Young Adult' and R['genderLabel'] == 'Female')

print()
print('=== search ===')
check('token finds by name', R['sWatson'] == ['Watson'], R['sWatson'])
check('token matches description', 'Husky Alto' in R['sLuminous'], R['sLuminous'])
check('token matches gender facet', 'Husky Alto' in R['sFemale'], R['sFemale'])
check('token matches age facet', 'Warm Tenor' in R['sTeen'], R['sTeen'])
check('multi-token AND narrows', R['sMulti'] == ['Husky Alto'], R['sMulti'])
check('multi-token no match -> empty', R['sNoMatch'] == [])
check('case-insensitive', R['sUpper'] == ['Watson'], R['sUpper'])

print()
print('=== combined filters (AND) ===')
check('gender+age+type combine', R['fCombo'] == ['Husky Alto'], R['fCombo'])
check('favorites=yes', R['fFavYes'] == ['Warm Tenor'], R['fFavYes'])
check('favorites=no excludes it', 'Warm Tenor' not in R['fFavNo'], R['fFavNo'])
check('conflicting filters -> empty', R['fConflict'] == [])

print()
print('=== sorting ===')
check('sort=name alphabetical', R['sortName'] == sorted(R['allNames'], key=str.lower),
      R['sortName'])
check('sort=favorites first', R['sortFav'][0] == 'Warm Tenor', R['sortFav'])
check('sort=newest (created desc)', R['sortNewest'][0] == 'Solo Female', R['sortNewest'])
check('sort=oldest (created asc)', R['sortOldest'][0] == 'Watson', R['sortOldest'])
check('relevance = catalog order', R['sortRel'] == R['allNames'])

print()
print('=== card markup ===')
C = R['cardAlto']
check('shows name', C['name'])
check('shows description', C['desc'])
check('shows gender label', C['gender'])
check('shows age label', C['age'])
check('shows tags', C['tags'])
check('has favorite control', C['favorite'])
check('has preview control', C['preview'])
check('has select control', C['select'])
check('has details control', C['details'])
check('marks not-downloaded', R['cardWatson']['notDownloaded'])

print()
print('=== contextual filter prefill (generic, from state) ===')
# Seeded with the state enums as openVoiceLibrary builds them (gender "MALE",
# ageLabel "Teen"); the select values are lower-case to match their options.
check('MALE / Teen seeds gender+age',
      R['ctxTeen']['gender'] == 'male' and R['ctxTeen']['age'] == 'teen', R['ctxTeen'])
check('FEMALE / Adult seeds gender+age',
      R['ctxAdultFemale']['gender'] == 'female' and R['ctxAdultFemale']['age'] == 'adult',
      R['ctxAdultFemale'])
check('multi-word age label maps to its key',
      R['ctxMiddleAged']['age'] == 'middle_aged', R['ctxMiddleAged'])
check('no state -> no seeded filters',
      R['ctxNoState']['gender'] == '' and R['ctxNoState']['age'] == '', R['ctxNoState'])

print()
print('=== states: loading / error / empty / no-match ===')
check('loading state shown', 'Loading voices' in R['renderLoading']['html'])
check('catalog error shown with Retry', 'Catalog unavailable' in R['renderError']['html']
      and 'Retry' in R['renderError']['html'])
check('error state says assignments unaffected',
      'unaffected' in R['renderError']['html'])
check('empty catalog offers upload', 'No voices available yet' in R['renderEmptyCatalog']['html']
      and 'vl-upload-input' in R['renderEmptyCatalog']['html'])
check('no-match explains and offers clear',
      'No voices match' in R['renderNoMatch']['html']
      and 'clearVoiceLibraryFilters' in R['renderNoMatch']['html'])
check('count reflects filters', R['renderNoMatch']['count'].startswith('0 of '),
      R['renderNoMatch']['count'])
check('count shows total when unfiltered',
      R['renderNormal']['count'] == '7 of 7 voices', R['renderNormal']['count'])

print()
print('=== active filter chips ===')
check('no chips when nothing filtered', R['renderNormal']['chipsShown'] is False)
check('chips shown + removable when searching',
      R['renderNoMatch']['chipsShown'] is True
      and 'clearVoiceLibraryFilter' in R['renderNoMatch']['chips'], R['renderNoMatch']['chips'][:90])
check('chip offers clear-all',
      'clearVoiceLibraryFilters' in R['renderNoMatch']['chips'])

print()
print('RESULT:', 'ALL %d CHECKS PASSED' % checks if not failures
      else '%d/%d FAILED: %s' % (len(failures), checks, failures))
sys.exit(1 if failures else 0)