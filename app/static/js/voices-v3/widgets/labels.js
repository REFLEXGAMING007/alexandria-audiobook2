/* Voices V3 — display vocabulary.
 *
 * Every list the original Voices tab hard-codes in markup or in a control lives
 * here, so the tab's own copy and its option lists cannot drift from each other.
 * Nothing here interprets meaning — a label is a label.
 */
(function (namespace) {
    'use strict';

    /* The Qwen3-TTS CustomVoice speaker names the engine accepts. A stored
     * `voice` outside this list is still offered, prepended, so a configuration
     * that names a voice the UI does not know about stays selectable. */
    var AVAILABLE_VOICES = Object.freeze([
        'Aiden', 'Dylan', 'Eric', 'Ono_anna', 'Ryan', 'Serena', 'Sohee', 'Uncle_fu', 'Vivian'
    ]);

    var VOICE_TYPES = Object.freeze(['custom', 'builtin_lora', 'clone', 'lora', 'design', 'ensemble']);

    var VOICE_TYPE_LABELS = Object.freeze({
        custom: 'Custom voice',
        builtin_lora: 'Built-in LoRA voice',
        clone: 'Clone voice',
        lora: 'LoRA voice',
        design: 'Voice Design',
        ensemble: 'Character ensemble'
    });

    var VOICE_TYPE_ARIA = Object.freeze({
        custom: 'Custom voice',
        builtin_lora: 'Built-in LoRA voice',
        clone: 'Clone voice',
        lora: 'LoRA voice',
        design: 'Voice Design',
        ensemble: 'Character ensemble'
    });

    /* Narrator selection. `focus` is scene focus, `character` is character focus;
     * the remaining entries match on traits, versions, or both. */
    var NARRATOR_STRATEGIES = Object.freeze([
        { value: 'global', label: 'Global' },
        { value: 'focus', label: 'Scene focus' },
        { value: 'chapter', label: 'Chapter' },
        { value: 'character', label: 'Character focus' },
        { value: 'gender', label: 'Gender' },
        { value: 'age', label: 'Age' },
        { value: 'gender_age', label: 'Gender + age' },
        { value: 'character_gender', label: 'Character + gender' },
        { value: 'character_age', label: 'Character + age' },
        { value: 'character_gender_age', label: 'Character + gender + age' }
    ]);

    var NARRATOR_HELP =
        'Global keeps the main narrator voice. Scene/Character focus uses the script’s focus character; ' +
        'Chapter uses its named narrator version. Gender and age modes use matching character traits or ' +
        'narrator versions. Missing matches keep the main narrator. Only the mode is saved: Preview focus ' +
        'and Preview version check a selection here and do not change the script or rendered audio.';

    var APPROVAL_ACTIONS = Object.freeze([
        { field: 'persona_status', status: 'approved', label: 'Approve persona', kind: 'btn-outline-success' },
        { field: 'persona_status', status: 'reviewed', label: 'Mark persona reviewed', kind: 'btn-outline-secondary' },
        { field: 'persona_status', status: 'rejected', label: 'Reject persona', kind: 'btn-outline-danger' },
        { field: 'voice_status', status: 'approved', label: 'Approve voice', kind: 'btn-outline-success' },
        { field: 'voice_status', status: 'reviewed', label: 'Mark voice reviewed', kind: 'btn-outline-secondary' },
        { field: 'voice_status', status: 'rejected', label: 'Reject voice', kind: 'btn-outline-danger' }
    ]);

    var APPROVAL_HELP =
        'Persona means the character description; Voice means the sound assigned to the character. ' +
        'Reviewed records that you checked it; Approved records that you accept it; Rejected records that ' +
        'it needs another choice. These are separate review states for the persona and the voice.';

    var PERSONA_CONTEXT_OPTIONS = Object.freeze([
        { value: '10', label: '10 lines' },
        { value: '25', label: '25 lines' },
        { value: '50', label: '50 lines' },
        { value: '100', label: '100 lines' },
        { value: 'custom', label: 'Custom' }
    ]);

    var PERSONA_GENERATION_HELP =
        'Generate Personas asks the configured LLM to describe the characters selected by Apply to, then uses ' +
        'TTS to generate voice-reference audio. Review the generated personas and references before generating the book.';

    var VOICES_SCOPE_HELP =
        'Apply to controls both Generate Personas and Suggest LoRA Voices. Context sets the number of sample ' +
        'spoken lines per character included in the persona prompt.';

    var SEED_REPAIR_HELP =
        'An original-file backup will be saved. Existing rendered audio is kept. Regenerated audio may sound ' +
        'different. Individual rendering uses character seeds; fast-batch rendering uses its separate batch seed.';

    var BUILTIN_HELP =
        'Grayed-out voices need to be downloaded first. Go to the Training tab to download them.';

    var ENSEMBLE_HELP =
        'Each character is voiced with whatever voice it already has, then mixed together. Clips are aligned ' +
        'to the longest, so this sounds like a chorus rather than exact unison.';

    var DESIGN_HELP =
        'Per-line instruct is appended to this description as delivery/emotion direction';

    var VERSION_HELP =
        'Selecting a saved version replaces the current voice settings. Save the current settings as a ' +
        'version first if you want to return to them later.';

    var CAST_HELP =
        'Save character voices to a named cast and reuse them across books in a series, so recurring ' +
        'characters sound the same. The narrator is shared across the whole series unless a cast saves its own.';

    var CAST_MEMBER_ACTIONS = Object.freeze([
        { action: 'cast-save', label: 'Save to cast', icon: 'fa-floppy-disk', kind: 'btn-outline-success' },
        { action: 'cast-apply', label: 'Apply cast', icon: 'fa-wand-magic-sparkles', kind: 'btn-success' },
        { action: 'cast-apply-bulk', label: 'Apply to multiple books', icon: 'fa-layer-group', kind: 'btn-outline-success' }
    ]);

    function voiceTypeLabel(type) {
        return VOICE_TYPE_LABELS[type] || VOICE_TYPE_LABELS.custom;
    }

    function strategyLabel(value) {
        var match = NARRATOR_STRATEGIES.find(function (entry) { return entry.value === value; });
        return match ? match.label : 'Global';
    }

    namespace.labels = {
        AVAILABLE_VOICES: AVAILABLE_VOICES,
        VOICE_TYPES: VOICE_TYPES,
        VOICE_TYPE_LABELS: VOICE_TYPE_LABELS,
        VOICE_TYPE_ARIA: VOICE_TYPE_ARIA,
        NARRATOR_STRATEGIES: NARRATOR_STRATEGIES,
        NARRATOR_HELP: NARRATOR_HELP,
        APPROVAL_ACTIONS: APPROVAL_ACTIONS,
        APPROVAL_HELP: APPROVAL_HELP,
        PERSONA_CONTEXT_OPTIONS: PERSONA_CONTEXT_OPTIONS,
        PERSONA_GENERATION_HELP: PERSONA_GENERATION_HELP,
        VOICES_SCOPE_HELP: VOICES_SCOPE_HELP,
        SEED_REPAIR_HELP: SEED_REPAIR_HELP,
        BUILTIN_HELP: BUILTIN_HELP,
        ENSEMBLE_HELP: ENSEMBLE_HELP,
        DESIGN_HELP: DESIGN_HELP,
        VERSION_HELP: VERSION_HELP,
        CAST_HELP: CAST_HELP,
        CAST_MEMBER_ACTIONS: CAST_MEMBER_ACTIONS,
        voiceTypeLabel: voiceTypeLabel,
        strategyLabel: strategyLabel
    };
}(window.VoicesV3 || (window.VoicesV3 = {})));