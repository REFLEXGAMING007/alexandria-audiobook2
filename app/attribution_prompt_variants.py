"""Alternative ways of ASKING the attribution question, as entries_providers
for three_pass_generate.attribute_batch (issue #522 follow-up, GOALS 1.2).

Selectable in the product: Setup -> Script generation -> "Attribution prompt"
(generation.three_pass_attribute_prompt_variant, or --prompt-variant). Each
variant's measured result on the four clean-gold books is in RECIPES.md
("Prompt"); `default` is the shipped prompt every adapter was trained on.

Each variant changes only the user prompt the model sees; the output
contract ([{n, speaker}], the JSON schema, the index-head check and the
text freeze) is untouched, so the gates that make attribution safe run
exactly as in production. The ideas come from the reasoning-trace probe
(2026-09-14) and from Michel et al. 2025 (NAACL, "Evaluating LLMs for
Quotation Attribution"), whose prompt is the published state of the art on
PDNC: quotes marked in running text, a character list WITH aliases, a
three-step instruction, and the previous chunk's predictions as context.

- aliases:     roster line carries each character's aliases
               ("HARUHIRO (also: HARU)").
- passage:     the window is shown as running text with SPOKEN lines
               marked |n|"..."|n| instead of a JSON list of entries.
- incremental: the speakers decided for the previous window are shown
               first, so a scene that spans two windows keeps its cast.
- michel:      all three together.
- judge:       the canonical request plus a `why` per spoken line - one
               sentence naming the evidence - so a strong model labelling a
               book for review checks itself and leaves a reason a human can
               audit. `speaker` is what the pipeline keeps; every
               {text, speaker, why} also goes to $JUDGE_WHY_PATH (JSON lines).
- continuity:  rolling story context (XinchaoGou/alexandria-audiobook's
               serial-novel pipeline): a running summary of everything
               before this window, rewritten by the model after each window
               (one extra short call), plus the previous window's last ten
               lines with the speakers decided for them. What a reader of a
               long series carries between chapters; the harness otherwise
               starts every window cold.
- michel2:     michel with what the shipped prompt and the continuity probe
               each measured as helping: a SYSTEM prompt written for the
               passage format (the shipped one describes a JSON entry list
               the model is not being shown) that keeps the minor-speaker
               rule (+6.5/+9.6, GOALS 1.2), the listener rule and UNKNOWN;
               and the previous window carried as its last lines WITH their
               speakers (the continuity tail, +8.1/+3.2 on Re:Zero) instead
               of bare index pairs whose indices restart every window.
- michel2_full: michel2 shown the whole window - every narration entry in
               order, not just each line's +-1 neighbours - with the
               segmented text before and after it as evidence. Michel et al.
               attribute inside 4,096-token chunks of the complete text; the
               context-size ablations of 2025-26 (ModernBERT 500->2000
               tokens, WNU 2025 per-line context plateauing at 512-1024) all
               point the same way. Needs `surround` from the caller.
- michel2_shot: michel2 with one worked example passage and its answer
               before the roster (WNU 2025's prompt shape; 6-shot beat CoT
               and zero-shot in the ChatGPT study).
"""
import json

from generate_script import call_llm_for_entries
from default_prompts import load_attribute_prompts
from three_pass_generate import build_attribute_request

VARIANTS = ("default", "aliases", "passage", "incremental", "michel", "continuity", "judge", "michel2", "michel2_full", "michel2_shot")

PASSAGE_INSTRUCTION = (
    "The passage below is continuous text from the book. Spoken lines are marked "
    "|n|\"...\"|n| with their index n; everything unmarked is narration and is "
    "never attributed.\n"
    "Step 1: reading in order, decide who speaks each marked line, using the "
    "narration around it, who is addressed, and what the line says.\n"
    "Step 2: match each speaker to a name on the roster (or NARRATOR / UNKNOWN).\n"
    "Step 3: return one {\"n\", \"speaker\"} object per input entry, including the "
    "narration entries (their speaker is NARRATOR), in index order. Do not repeat "
    "any text and do not explain.")


MICHEL2_SYSTEM = """You label EVERY marked entry of a novel passage with who speaks it for a TTS system.

Output ONLY a valid JSON array — no markdown, no explanations, no extra text.

You receive a ROSTER containing known named characters and their aliases, and a PASSAGE of continuous text in which every entry is marked with its index:

* spoken lines: |n|"..."|n|
* narration entries: [n] ...

Unmarked text is surrounding narration shown only as evidence.

Return exactly one object for every marked entry, in index order.

For narration, return:

{"n": 0, "speaker": "NARRATOR"}

For spoken lines, return:

{"n": 1, "speaker": "PROFESSOR FERNANDO", "gender": "MALE", "age_group": "ADULT"}

The spoken-line fields are:

* "n": the original index as a JSON integer
* "speaker": the canonical identity of whoever is speaking
* "gender": the speaker's gender at this point in the story
* "age_group": the speaker's age group at this point in the story

Allowed gender values:

"MALE"
"FEMALE"
"UNSPECIFIED"

Allowed age_group values:

"CHILD"
"TEEN"
"YOUNG_ADULT"
"ADULT"
"MIDDLE_AGED"
"ELDERLY"
"AGELESS"
"UNSPECIFIED"

# HOW TO DECIDE WHO SPEAKS

Use the strongest available evidence, in this order:

1. A speech tag names the speaker:
   "..." said X
   "..." X asked
   X shouted
   X's voice
   and similar constructions.

   A tag immediately before or after a spoken line normally belongs to that line.

2. Nearby narration or character actions clearly identify the speaker.

3. Use direct address correctly.
   A name inside a spoken line usually identifies the LISTENER, not the speaker.

   Example:
   "Yes, Ranta."
   is normally spoken TO Ranta, not BY Ranta.

4. With no explicit attribution, use the surrounding context:

   * who is present
   * who is being addressed
   * what the line answers
   * who would know the information
   * what the speaker wants or is reacting to
   * nearby actions and reactions
   * dialogue continuity
   * established relationships
   * the speaker's established role or identity

5. Do NOT assume speakers alternate strictly.
   The same character may speak several consecutive lines.

6. Do NOT default to the protagonist or the most frequently appearing character.
   A minor or background character is the correct speaker whenever the evidence supports them.

7. Use an existing roster character whenever the evidence supports that identity.
   Any listed alias or alternate form refers to the same character. Return the canonical roster name.

8. If the speaker is unnamed but is still identifiable as a recurring individual, create or reuse a descriptive BACKGROUND identity.

9. If several unnamed characters are clearly speaking or vocalizing together as a collective, use a GROUP identity.

10. Use UNKNOWN only when no stable speaker identity can reasonably be established.

A wrong specific identity is worse than a more general supported identity.

# NAMED CHARACTERS

A named character keeps one stable speaker identity throughout the novel.

Do NOT create separate identities because the character's age, gender, body, form, role, or appearance changes.

For example, use:

ARTHUR_LEYWIN

for all stages of Arthur rather than:

ARTHUR_CHILD
ARTHUR_TEEN
ARTHUR_ADULT

The same identity can have different gender and age_group values on different lines.

Example:

{"n": 100, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "CHILD"}

Later:

{"n": 5000, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "TEEN"}

Later:

{"n": 12000, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "YOUNG_ADULT"}

Later:

{"n": 22000, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "ADULT"}

# GENDER

Determine gender from the source and surrounding context.

Use evidence such as:

* explicit gender descriptions
* pronouns when clearly applicable
* gendered nouns or titles
* explicit statements
* other strong textual evidence

Do NOT infer gender from stereotypes or occupations.

For example, "guard", "student", "soldier", "shopkeeper", "teacher" and similar roles do NOT automatically imply a gender.

When gender is not reliably established, use:

"UNSPECIFIED"

Gender describes the speaker's current state at the time represented by that line.

A genuine gender change should be reflected in the affected lines.

This includes situations such as:

* gender-bender
* transformation
* body swap
* possession
* reincarnation
* magical transformation
* another story event that genuinely changes the character's current gender

Do NOT create a new speaker identity merely because gender changes.

# AGE GROUP

Determine age_group from the source and surrounding context.

Allowed values are exactly:

CHILD
TEEN
YOUNG_ADULT
ADULT
MIDDLE_AGED
ELDERLY
AGELESS
UNSPECIFIED

Use evidence such as:

* explicit ages
* explicit age ranges
* "child", "boy", "girl", "teenager", "young man", "young woman"
* "middle-aged", "elderly", "old man", "old woman"
* established character chronology
* stated time skips
* flashbacks
* future scenes
* transformations or de-aging
* other strong contextual evidence

Do NOT infer an age group from occupation alone.

For example, "student" does not automatically mean TEEN.

Age is temporal.

A named character can naturally move through:

CHILD → TEEN → YOUNG_ADULT → ADULT → MIDDLE_AGED

or through other valid age states.

When the source does not provide enough evidence, use:

"UNSPECIFIED"

# AGE IN FLASHBACKS AND TIME SKIPS

Determine age according to the time represented by the scene, not simply the character's current age elsewhere in the novel.

If an adult character remembers being twelve and that remembered scene contains the character speaking, use:

"age_group": "CHILD"

for that speech.

Likewise, future scenes should use the age represented by that future period.

# BACKGROUND CHARACTERS

An unnamed speaker must NOT automatically become UNKNOWN.

When a speaker is unnamed but can be usefully identified, create a stable background identity.

The background ID identifies the individual only. Do NOT encode gender or age into the ID.

Prefer these forms:

ROLE_ID

Examples:

GUARD_01
STUDENT_01
SHOPKEEPER_03
TEACHER_01
SOLDIER_02
BARTENDER_01

If no useful role is available:

ENVIRONMENT_ID

Examples:

ALLEYWAY_01
TAVERN_02
CLASSROOM_01
STREET_01

If neither role nor useful environment can be established:

PERSON_ID

Examples:

PERSON_01
PERSON_02

Gender and age are returned separately.

For example:

{"n": 21, "speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT"}

NOT:

GUARD_MALE_01

and not:

GUARD_ADULT_01

The permanent background identity should remain stable even when its gender or age_group changes.

# BACKGROUND ROLE SELECTION

Use the most informative role that is actually supported by the source.

For example:

GUARD_01

is appropriate when the text establishes that the unnamed person is a guard.

Do not invent a more specific role merely because it seems plausible.

If the text only establishes that someone is a man near a shop, do not automatically call him SHOPKEEPER.

Prefer a less specific supported identity over a more specific invented one.

# BACKGROUND CHARACTER CONTINUITY

Try to reuse the same background identity when the context indicates the same individual.

For example, if the same unnamed guard appears repeatedly, maintain:

GUARD_01

rather than creating:

GUARD_01
GUARD_02
GUARD_03

for the same person.

Evidence for continuity may include:

* continuing involvement in the same scene
* explicit references such as "the same guard"
* the same distinctive description
* the same established role and context
* established relationships
* distinctive behavior or other identifying details
* direct narrative continuity

Do NOT merge two different characters merely because they share the same role.

Two different guards can legitimately be:

GUARD_01
GUARD_02

Create a new number when the evidence indicates that the speaker is a different unnamed individual.

Do not change an established background identity merely because a later passage provides more descriptive information.

# BACKGROUND GENDER AND AGE

Background IDs must NOT contain gender or age.

Example:

{"n": 30, "speaker": "GUARD_01", "gender": "MALE", "age_group": "ADULT"}

If the same recurring guard is later described as middle-aged:

{"n": 500, "speaker": "GUARD_01", "gender": "MALE", "age_group": "MIDDLE_AGED"}

Keep GUARD_01.

Do not create GUARD_02 merely because the age_group changed.

Likewise, a genuine gender change does not automatically create a new background identity.

# GROUP SPEAKERS

When multiple characters clearly speak, shout, cheer, chant, cry, or vocalize together as one collective, use a GROUP identity instead of UNKNOWN.

Examples:

STUDENT_GROUP_01
GUARD_GROUP_01
TAVERN_GROUP_01
CLASSROOM_GROUP_01
CROWD_GROUP_01
GROUP_01

When useful, a role or environment may be included.

Examples:

STUDENT_GROUP_01
GUARD_GROUP_01
TAVERN_GROUP_01

Do NOT encode gender or age into the group ID.

Return those separately.

For example:

{"n": 30, "speaker": "STUDENT_GROUP_01", "gender": "UNSPECIFIED", "age_group": "TEEN"}

A group may have a specific gender or age_group only when the group as a whole is clearly described that way.

Examples:

"the boys shouted"
→ gender = MALE

"a group of teenage girls shouted"
→ gender = FEMALE
→ age_group = TEEN

A mixed or insufficiently described group should use:

"gender": "UNSPECIFIED"

and/or:

"age_group": "UNSPECIFIED"

as appropriate.

# UNKNOWN

UNKNOWN is the final identity fallback.

Do NOT use UNKNOWN merely because:

* the speaker is unnamed
* the speaker is a background character
* there is no speech tag
* the speaker is a minor character
* the speaker is absent from the named roster

Before using UNKNOWN, consider:

1. Existing named character
2. Existing background individual
3. New role-based background individual
4. New environment-based background individual
5. Generic person identity
6. Group identity when appropriate

Only use:

"speaker": "UNKNOWN"

when no stable identity can reasonably be established.

Gender and age_group are independent of identity.

Therefore an UNKNOWN speaker may still have known attributes.

Example:

{"n": 50, "speaker": "UNKNOWN", "gender": "MALE", "age_group": "ADULT"}

Do not invent an identity merely to avoid UNKNOWN.

# EVIDENCE AND UNCERTAINTY

Always prefer the most informative answer that is supported by the text.

Do not invent:

* character names
* background roles
* gender
* age
* relationships
* identities

A less specific supported answer is better than an unsupported specific one.

For example:

GUARD_01 + MALE

is better than inventing a person's name.

STUDENT_01 + UNSPECIFIED gender

is better than guessing gender from the word "student".

PERSON_01

is better than inventing an unsupported occupation.

UNKNOWN

is better than assigning the wrong existing character.

# IMPORTANT DISTINCTION

The "speaker" field identifies WHO the speaker is.

The "gender" and "age_group" fields describe WHAT STATE that speaker is in at this point in the story.

Do not merge these concepts.

For example, all of these can legitimately refer to the same character:

{"n": 100, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "CHILD"}

{"n": 5000, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "TEEN"}

{"n": 12000, "speaker": "ARTHUR_LEYWIN", "gender": "MALE", "age_group": "YOUNG_ADULT"}

{"n": 22000, "speaker": "ARTHUR_LEYWIN", "gender": "FEMALE", "age_group": "ADULT"}

The identity remains ARTHUR_LEYWIN.

# SPEAKER VS LISTENER

A name inside dialogue usually identifies the listener, not the speaker.

Example:

"Professor Fernando, can you help me?"

Do NOT automatically assign the line to PROFESSOR_FERNANDO.

Use the surrounding context to determine who actually said it.

# NO SPEAKER ALTERNATION ASSUMPTION

Never alternate speakers simply because two characters are conversing.

The same character may speak several consecutive lines.

# NO TEXT MODIFICATION

Pass 2 must not return or modify the source text.

Do not:

* repeat dialogue text
* rewrite text
* summarize text
* add text
* remove text
* merge entries
* split entries
* change indices
* reorder entries

# FINAL OUTPUT RULES

Return exactly one object per marked entry.

Every index must appear exactly once, in its original order.

Narration entries:

{"n": <index>, "speaker": "NARRATOR"}

Spoken entries:

{"n": <index>, "speaker": "<IDENTITY>", "gender": "<GENDER>", "age_group": "<AGE_GROUP>"}

No extra fields.

No missing fields on spoken entries.

No text outside the JSON array.

Output ONLY the valid JSON array."""

MICHEL2_EXAMPLE = (
    "EXAMPLE (a different book):\n"
    "ROSTER: MARA (also: MISS ELLIS), TOM, THE INNKEEPER\n"
    "PASSAGE:\n"
    "The innkeeper set down two cups without a word.\n\n"
    "|0|\"You're late, Tom.\"|0|\n\n"
    "|1|\"The bridge was out.\"|1|\n\n"
    "He would not meet her eye.\n\n"
    "[2] Mara said nothing for a while.\n\n"
    "|3|\"That will be a shilling for the room.\"|3|\n"
    "ANSWER: [{\"n\": 0, \"speaker\": \"MARA\"}, {\"n\": 1, \"speaker\": \"TOM\"}, "
    "{\"n\": 2, \"speaker\": \"NARRATOR\"}, {\"n\": 3, \"speaker\": \"THE INNKEEPER\"}]\n"
    "(0 names Tom, so it is said TO Tom, by the other person present; 1 answers it; "
    "3 is what an innkeeper says, not what Mara or Tom would.)\n\n")


def surround_passage(surround, frozen_batch=None, neighbor_contexts=None):
    """The whole window as running text: sent entries marked with their
    frozen index, unsent narration entries as unmarked text, and the text
    before/after the window as evidence-only blocks. Without an "entries"
    list (the product path, whose window already carries its narration) the
    body is passage_text of the batch itself."""
    if not surround.get("entries"):
        return _wrap_passage(passage_text(frozen_batch or [], neighbor_contexts), surround)
    parts = []
    for e in surround.get("entries") or []:
        if e.get("n") is None:
            parts.append(e["text"])
        elif e["type"] == "SPOKEN":
            parts.append(f'|{e["n"]}|"{e["text"]}"|{e["n"]}|')
        else:
            parts.append(f"[{e['n']}] {e['text']}")
    return _wrap_passage("\n\n".join(parts), surround)


def _wrap_passage(body, surround):
    before, after = surround.get("before") or "", surround.get("after") or ""
    if before:
        body = f"BEFORE THE PASSAGE (evidence only, never attribute):\n{before}\n\nPASSAGE:\n{body}"
    else:
        body = f"PASSAGE:\n{body}"
    if after:
        body += f"\n\nAFTER THE PASSAGE (evidence only, never attribute):\n{after}"
    return body


MICHEL2_INSTRUCTION = (
    "Decide the speaker of every marked line in the PASSAGE and return the JSON array "
    "of {\"n\", \"speaker\"} objects, one per marked entry, in index order.")


JUDGE_INSTRUCTION = (
    "\n\nYou are labelling this book as reference data, so check yourself: for every "
    "SPOKEN entry, before choosing the speaker, find the evidence in the narration "
    "around it - a speech tag, who is addressed, turn-taking, or what the line says - "
    "and confirm it does not contradict the surrounding lines. Add a field \"why\" to "
    "each SPOKEN object: one sentence naming that evidence (quote the tag or cue). "
    "Output objects are {\"n\", \"speaker\", \"why\"}; narration entries need no why.")


def record_judge_reasons(frozen_batch, named):
    """Append {text, speaker, why} per spoken line to $JUDGE_WHY_PATH."""
    import os
    path = os.environ.get("JUDGE_WHY_PATH")
    if not path or not named:
        return
    by_n = {}
    for item in named:
        if isinstance(item, dict) and isinstance(item.get("n"), int):
            by_n[item["n"]] = item
    with open(path, "a", encoding="utf-8") as fh:
        for i, entry in enumerate(frozen_batch):
            if entry.get("type") != "SPOKEN":
                continue
            item = by_n.get(i, {})
            fh.write(json.dumps({"text": entry["text"], "speaker": item.get("speaker"),
                                 "why": item.get("why")}, ensure_ascii=False) + "\n")


SUMMARY_INSTRUCTION = (
    "You keep a running summary of a novel for someone who must know who is "
    "present and speaking. Rewrite the summary below to cover the new passage "
    "as well: who is in the scene, where they are, what just happened, and any "
    "name or title a character is called by. At most 150 words, plain prose, "
    "no headings.")
SUMMARY_MAX_TOKENS = 400
TAIL_LINES = 10


def rolling_summary(client, model_name, params, previous_summary, passage):
    """-> the summary rewritten to include `passage`; the old one on failure.

    One short call with reasoning off (the summary is not the hard part);
    the passage is what the model was shown for the window, narration
    included, so it can name whoever was present."""
    from dataclasses import replace
    body = (f"{SUMMARY_INSTRUCTION}\n\nSUMMARY SO FAR:\n{previous_summary or '(start of the book)'}"
            f"\n\nNEW PASSAGE:\n{passage}")
    try:
        response = client.chat.completions.create(
            model=model_name, temperature=0, max_tokens=SUMMARY_MAX_TOKENS,
            extra_body={"reasoning_effort": "none"},
            messages=[{"role": "user", "content": body}])
        text = (response.choices[0].message.content or "").strip()
    except Exception:
        return previous_summary
    return text or previous_summary


def roster_line(roster, alias_groups=None):
    """Roster with each name's aliases, from alias groups that mention it."""
    parts = []
    for name in roster:
        extra = []
        for group in alias_groups or []:
            if name in group:
                extra += [a for a in group if a != name and a not in extra]
        parts.append(f"{name} (also: {', '.join(sorted(extra))})" if extra else name)
    return ", ".join(parts) or "(none yet)"


def passage_text(frozen_batch, neighbor_contexts=None):
    """The batch as running prose. The harness sends only the SPOKEN lines and
    carries the narration in each entry's previous/next context, so those are
    interleaved here; without them the four variant arms of 2026-09-14 saw
    dialogue with no narration at all and scored 25% against 63%."""
    neighbor_contexts = neighbor_contexts or [{} for _ in frozen_batch]
    out, seen = [], set()

    def narration(ctx_entry):
        text = (ctx_entry or {}).get("text") if isinstance(ctx_entry, dict) else None
        if text and ctx_entry.get("type") == "NARRATOR" and text not in seen:
            seen.add(text)
            out.append(text)

    for i, e in enumerate(frozen_batch):
        ctx = neighbor_contexts[i] if i < len(neighbor_contexts) else {}
        narration(ctx.get("previous_context"))
        if e["type"] == "SPOKEN":
            out.append(f'|{i}|"{e["text"]}"|{i}|')
        else:
            out.append(f"[{i}] {e['text']}")
        narration(ctx.get("next_context"))
    return "\n\n".join(out)


PASSAGE_SHAPED = ("passage", "michel")
USER_VARIANTS = tuple(v for v in VARIANTS if v != "judge")   # judge is gold labelling, harness only


def builtin_texts(variant):
    """The texts a variant sends, as a user-editable preset would carry them:
    {"system", "user", "example"}. For `default` the user text is the
    template with its {roster}/{batch} placeholders; for the passage-shaped
    variants it is the instruction block the pipeline wraps ROSTER/PASSAGE
    around; the canonical-request variants (aliases/incremental/continuity)
    use the default template. `example` is only non-empty for michel2_shot."""
    system, template = load_attribute_prompts()
    if variant.startswith("michel2"):
        return {"system": MICHEL2_SYSTEM, "user": MICHEL2_INSTRUCTION,
                "example": MICHEL2_EXAMPLE if variant == "michel2_shot" else ""}
    if variant in PASSAGE_SHAPED:
        return {"system": system, "user": PASSAGE_INSTRUCTION, "example": ""}
    return {"system": system, "user": template, "example": ""}


VARIANT_DESCRIPTIONS = {
    "default": "the standard prompt (use this with any trained adapter)",
    "michel": "lines shown as running text with nicknames listed and the previous request's answers (Michel et al. 2025)",
    "michel2": "michel plus this project's own rules (e.g. don't default to the main characters)",
    "michel2_full": "michel2 with extra surrounding text (set \"Step 2: extra text around each request\")",
    "michel2_shot": "michel2 with a worked example shown first",
    "continuity": "keeps a running summary of the story so far (one extra request per batch of lines)",
    "aliases": "default, plus character nicknames listed",
    "passage": "default, but lines shown as running text",
    "incremental": "default, plus the previous request's answers",
}


def builtin_presets():
    """One builtin preset per user-selectable variant, named as RECIPES names
    it, carrying the texts the variant actually sends."""
    return [{"name": v, "description": VARIANT_DESCRIPTIONS[v], "variant": v,
             "system_prompt": builtin_texts(v)["system"],
             "user_prompt": builtin_texts(v)["user"],
             "example": builtin_texts(v)["example"], "builtin": True}
            for v in USER_VARIANTS]


def resolve_attribution_preset(config):
    """-> (variant, texts, preset_name) for the run: the preset named by
    prompts.attribution_preset among the user's presets, else the builtin of
    that name, else the builtin for generation.three_pass_attribute_prompt_variant.
    `texts` is None when the preset is a builtin (send exactly the builtin)."""
    prompts = config.get("prompts") or {}
    name = prompts.get("attribution_preset")
    if not name:
        # a config from before presets carried the variant (#581) still says
        # which one it meant through the generation key
        name = (config.get("generation") or {}).get("three_pass_attribute_prompt_variant") or "michel2_full"
    for preset in config.get("prompt_presets") or []:
        if isinstance(preset, dict) and preset.get("name") == name and not preset.get("builtin"):
            variant = preset.get("variant") or "default"
            if variant not in USER_VARIANTS:
                raise ValueError(f"preset {name!r} names unknown variant {variant!r}")
            return variant, {"system": preset.get("system_prompt") or "",
                             "user": preset.get("user_prompt") or "",
                             "example": preset.get("example") or ""}, name
    if name in USER_VARIANTS:
        return name, None, name
    variant = (config.get("generation") or {}).get("three_pass_attribute_prompt_variant") or "michel2_full"
    return variant, None, variant


def validate_preset_texts(variant, texts):
    """-> an error message, or None. The default shape's user text is a
    template the pipeline fills; without both placeholders the model would
    never see the roster or the entries."""
    if variant == "default" or variant in ("aliases", "incremental", "continuity"):
        user = (texts or {}).get("user") or ""
        if user.strip() and ("{roster}" not in user or "{batch}" not in user):
            return ("For the default-shaped prompts the user text is a template and must keep "
                    "the {roster} and {batch} placeholders - that is where the pipeline puts "
                    "the character list and the entries.")
    return None


def _texts_for(variant, texts):
    base = builtin_texts(variant)
    for key, value in (texts or {}).items():
        if key in base and isinstance(value, str) and value.strip():
            base[key] = value
    return base


def build_variant_request(variant, frozen_batch, params, roster, alias_groups=None,
                          neighbor_contexts=None, surround=None, memory=None, texts=None):
    """-> (system_prompt, user_body) for one window under `variant`, with the
    preset `texts` ({"system", "user", "example"}; None = the variant's
    builtin) in place. Pure: this is what the provider sends and what the
    Setup preview shows, one implementation."""
    from dataclasses import replace
    roster = list(roster or [])
    memory = memory or {"previous": [], "summary": "", "tail": []}
    t = _texts_for(variant, texts)
    michel2_family = variant.startswith("michel2")
    if variant in ("aliases", "michel") or michel2_family:
        roster_str = roster_line(roster, alias_groups)
    else:
        roster_str = ", ".join(roster) or "(none yet)"
    sys_prompt = t["system"]
    if michel2_family:
        tail = "\n".join(f'{spk}: "{text}"' for spk, text in memory["tail"])
        if variant == "michel2_full":
            if not surround:
                raise ValueError("michel2_full needs the caller to pass surround=")
            passage = surround_passage(surround, frozen_batch, neighbor_contexts)
        else:
            # the surrounding-text knob applies to every variant; in the
            # product, michel2 with it on is michel2_full
            passage = _wrap_passage(passage_text(frozen_batch, neighbor_contexts), surround or {})
        body = ((t["example"] if variant == "michel2_shot" and t["example"] else "")
                + f"ROSTER: {roster_str}\n\n"
                + (f"HOW THE PREVIOUS PASSAGE ENDED (speakers already decided; evidence "
                   f"only, never attribute these):\n{tail}\n\n" if tail else "")
                + f"{passage}\n\n{t['user']}")
    elif variant in PASSAGE_SHAPED:
        body = (f"{t['user']}\n\nROSTER: {roster_str}\n\n"
                + _wrap_passage(passage_text(frozen_batch, neighbor_contexts), surround or {}))
    else:
        # canonical request, with the preset's texts standing in for the file's
        canon_params = replace(params, attribute_system_prompt=t["system"],
                               user_prompt_template=t["user"])
        sys_prompt, canonical = build_attribute_request(
            frozen_batch, canon_params, roster, neighbor_contexts, surround)
        body = canonical.replace(f"ESTABLISHED ROSTER: {', '.join(roster) or '(none yet)'}",
                                 f"ESTABLISHED ROSTER: {roster_str}")
    if variant in ("incremental", "michel") and memory["previous"]:
        prev = "; ".join(f"{i}: {s}" for i, s in memory["previous"])
        body = ("Speakers already decided for the lines immediately before this passage "
                f"(most recent last): {prev}\n\n") + body
    if variant == "judge":
        body = body + JUDGE_INSTRUCTION
    if variant == "continuity" and (memory["summary"] or memory["tail"]):
        tail = "\n".join(f'{spk}: "{text}"' for spk, text in memory["tail"])
        body = ("STORY SO FAR (for identity and continuity only; never attribute "
                f"lines from it):\n{memory['summary'] or '(none)'}\n\n"
                f"LAST LINES OF THE PREVIOUS PASSAGE, with their speakers:\n{tail or '(none)'}"
                "\n\n") + body
    return sys_prompt, body


def make_provider(variant, alias_groups=None, texts=None):
    """-> an entries_provider for attribute_batch; keeps per-run memory for
    the incremental/continuity/michel2 variants. `texts` is the active
    preset's {"system", "user", "example"}; None sends the builtin."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown prompt variant {variant!r}; expected one of {VARIANTS}")
    memory = {"previous": [], "summary": "", "tail": []}

    def provider(client, model_name, sys_prompt, user_prompt, params, log_name, label,
                 max_retries, validate_entries, attempt_observer, frozen_batch,
                 roster=None, neighbor_contexts=None, surround=None, **_ignored):
        michel2_family = variant.startswith("michel2")
        sys_prompt, body = build_variant_request(
            variant, frozen_batch, params, roster, alias_groups, neighbor_contexts,
            surround, memory, texts)
        named = call_llm_for_entries(
            client, model_name, sys_prompt, body, params, log_name=log_name, label=label,
            max_retries=max_retries, validate_entries=validate_entries,
            attempt_observer=attempt_observer)
        if named:
            spoken = [(i, item.get("speaker")) for i, (f, item) in enumerate(zip(frozen_batch, named))
                      if f["type"] == "SPOKEN" and item.get("speaker")]
            memory["previous"] = spoken[-8:]
            if variant == "continuity" or michel2_family:
                memory["tail"] = [(item.get("speaker"), f["text"])
                                  for f, item in zip(frozen_batch, named)
                                  if f["type"] == "SPOKEN"][-TAIL_LINES:]
        if variant == "judge":
            record_judge_reasons(frozen_batch, named)
        if variant == "continuity":
            memory["summary"] = rolling_summary(
                client, model_name, params, memory["summary"],
                passage_text(frozen_batch, neighbor_contexts))
        return named

    provider.variant = variant
    return provider
