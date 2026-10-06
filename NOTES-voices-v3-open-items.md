# Voices V3 — open items

Findings from the first live browser run (2026-10-06). Not blocking; none fixed yet.

## 1. `window_total` counts calls that can never happen

`three_pass_generate.py:2313`

```python
window_total = sum(1 for _ in iter_unique_entry_batches(segmented, attribute_batch_size))
```

`iter_unique_entry_batches` (`:298`) greedily colours each source window into
duplicate-free batches. Pass 2 then skips any batch with no unattributed SPOKEN
entry (`:2327`, `if not any(index not in deterministic ...)`).

So the denominator counts coloured batches, but only batches containing SPOKEN
work can become model calls. Measured on `state-voice-test.txt` (146 entries,
`attribute_batch_size: 500`): `window_total` = 18, of which **1** was real. The
other 17 were NARRATOR-only attribution tags (`"Maro said."` ×18, `"he said."` ×5,
`"his wife said."` ×3 — duplicates created by the segment prompt's rule that
attribution tags must be their own entry).

Pass 2 made **2** model calls (123 entries + a 6-entry re-ask), not 18.

Effect: the UI reports a denominator that overstates real work by ~9x here.
Fix direction: count only batches that would actually be asked.

## 2. Entry indices are rebased per window — silent mismatch risk

`build_attribute_request` (`:478`) builds the batch with
`enumerate(frozen_batch)`, so `n` is **window-local**, not global.

Live evidence: the second pass-2 window showed `n=3, n=4, n=5` for what are
global entries ~140-142.

A reply assembled across windows must therefore be remapped by position, and
neither the prompt text nor the UI says so. A user (or script) matching `n`
against global script indices mis-maps every reply after the first window.

This is the one with teeth: silent index mismatch is a data-corruption path,
not a display issue. Worth confirming whether the response parser already
rebases correctly on its side before assuming it is unhandled.

## 3. ~~Test text flaw~~ RESOLVED — my prediction was wrong

I predicted chapter 1 would scatter MARO across bands and yield only 2 states,
based on counting from a mid-run partial checkpoint. The finished run disagrees:

```
MARO  54 lines  states=3
   male/teen      from_entry   4
   male/adult     from_entry  50
   male/elderly   from_entry 100
```

All three bands clear PERSIST_LINES=10 and the gaps are >= STATE_CHANGE_BANDS=2.
`young_adult` resolved away once pass 2 finished attributing the rest. The text
was fine as written; no rewrite needed. Lesson: don't infer final trait state from
a partial checkpoint.

149 entries, all with `instruct`, 9 speakers, NARRATOR correctly traitless.

## 4. Cost of repetitive attribution tags (real, worth changing in the text)

18 copies of `Maro said.` in `state-voice-test.txt` produced:

- pass 1: 18 duplicate entries (the segment prompt requires attribution tags be
  their own entry, so this is *correct* behaviour on correct input)
- pass 2: inflated `window_total` (item 1)
- pass 3: ~15 real, separate LLM calls, one per tag pair — pass 3 does NOT skip
  NARRATOR-only batches the way pass 2 does, because every entry needs an
  `instruct`

So the duplication is cheap in pass 2 and genuinely expensive in pass 3.
Varying the tags (`he told her`, `she answered`) avoids all three effects at once.

## 4. Confirmed working

- Manual LLM transport, end to end (cast list + both script passes)
- `transport: manual` needs no reachable LLM endpoint — `base_url` is ignored
- **"Test this book with the LLM" (preflight) cannot use manual transport.**
  `script.py:1030` sets `ALEXANDRIA_DATA_DIR` to a private temp dir, so its
  pending request is written where `/api/manual_llm/pending` never looks. It hangs
  by construction. Do not use it in manual mode.
- `is_manual_request_owner_alive` is wired (`llm_provider.py:530`) — I earlier
  claimed it had no callers; that was wrong.