"""Pass 3 lines per request (`three_pass_instruct_batch_size`).

A downstream feature module on purpose: its coverage stays out of the shared
upstream test classes, so future creator edits there cannot collide with it.

The windowing tests drive the real ``run_three_pass()`` through a routing fake
client (the ``client_for`` convention of ``test_three_pass_attempt_outcomes``
and ``_client`` of ``test_narration_context``): the fake tells pass 2 and pass 3
apart by the JSON keys each prompt asks for, and records how many entries every
request carried, so the groupings asserted here are the windows the pipeline
actually built.
"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import config_settings as cs
import three_pass_generate as tp
from generate_script import LLMGenParams


def _entry(text):
    return {"speaker": "NARRATOR", "text": text}


# The two passes ask for different JSON keys, which is the reliable way to tell
# them apart: call_llm_for_entries does not forward its `label` kwarg to the
# client's create(). Pass 3 always asks for {"n","instruct"}; pass 2 asks for
# {"n","speaker"} and never mentions instruct.
_INSTRUCT_MARKER = '"n","instruct"'


def _quoted_source(count, speaker="Alice"):
    """``count`` spoken lines, each naming the speaker.

    The name has to be written in the source: attribution's attestation gate
    rejects a speaker the book never capitalises (this is a pass-2 rule, not a
    pass-3 one, so it only affects the fixture).
    """
    return " ".join('"{} said line{}"'.format(speaker, i) for i in range(count))


def _routing_client(entry_count, attribute_batch_size, instruct_batch_size,
                    speaker="ALICE"):
    """Fake client answering pass 2 and pass 3, recording each request's size.

    Both passes number indices batch-locally (``index_head_check`` wants one row
    per entry with ``0 <= n < len(batch)``), so each reply carries exactly as
    many rows as the window the pipeline just built.
    """
    sizes = {"ATTRIBUTE": [], "INSTRUCT": []}

    def create(**kwargs):
        messages = kwargs.get("messages") or [{}]
        user = messages[-1].get("content", "")
        is_instruct = _INSTRUCT_MARKER in user
        key = "INSTRUCT" if is_instruct else "ATTRIBUTE"
        window = instruct_batch_size if is_instruct else attribute_batch_size
        done = sum(sizes[key])
        k = max(0, min(window, entry_count - done))
        sizes[key].append(k)
        if is_instruct:
            rows = [{"n": i, "instruct": "Measured."} for i in range(k)]
        else:
            rows = [{"n": i, "speaker": speaker,
                     "gender": "FEMALE", "age_group": "ADULT"}
                    for i in range(k)]
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(rows)),
                finish_reason="stop")],
            usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(
        completions=SimpleNamespace(create=create)))
    return client, sizes


def _run(entry_count, attribute_batch_size, instruct_batch_size=None, **kwargs):
    """Run the real three-pass pipeline; report per-pass request groupings."""
    client, sizes = _routing_client(entry_count, attribute_batch_size,
                                    instruct_batch_size or tp.BATCH_SIZE)
    params = LLMGenParams(max_tokens=4096, temperature=0.1,
                           segmentation="quotes", structured_output="off")
    options = {}
    if instruct_batch_size is not None:
        options["instruct_batch_size"] = instruct_batch_size
    with tempfile.TemporaryDirectory() as tmp, \
            contextlib.redirect_stdout(io.StringIO()):
        output = str(Path(tmp) / "book.json")
        entries = tp.run_three_pass(
            client, "fixture", _quoted_source(entry_count), params,
            chunk_size=6000, output_path=output,
            attribute_batch_size=attribute_batch_size,
            cast={"names": ["ALICE"], "known_names": {"ALICE"},
                  "alias_groups": [], "alias_to_name": {}, "sha256": None},
            **options, **kwargs)
    return entries, sizes


class InstructBatchSizeTests(unittest.TestCase):
    """The Pass 3 request window is independent from Pass 2's."""

    def test_pass3_windows_follow_the_selected_value(self):
        # Exercises run_three_pass -> pass 3 -> iter_unique_entry_batches(named,
        # instruct_batch_size) for real: 12 spoken lines, one pass-2 window.
        entries, sizes = _run(12, attribute_batch_size=1000,
                              instruct_batch_size=5)
        self.assertEqual(12, len(entries))
        self.assertEqual([12], sizes["ATTRIBUTE"])
        self.assertEqual([5, 5, 2], sizes["INSTRUCT"])

    def test_a_single_pass3_window_covers_everything(self):
        _entries, sizes = _run(12, attribute_batch_size=1000,
                               instruct_batch_size=25)
        self.assertEqual([12], sizes["INSTRUCT"])

    def test_pass2_and_pass3_windows_are_independent(self):
        # 200 spoken lines; pass 2 is told 5 per request, pass 3 is told 50.
        # Both counts are read off the requests the pipeline actually sent.
        entries, sizes = _run(200, attribute_batch_size=5,
                              instruct_batch_size=50)
        self.assertEqual(200, len(entries))
        self.assertEqual(40, len(sizes["ATTRIBUTE"]))
        self.assertTrue(all(k == 5 for k in sizes["ATTRIBUTE"]))
        self.assertEqual(4, len(sizes["INSTRUCT"]))
        self.assertTrue(all(k == 50 for k in sizes["INSTRUCT"]))
        self.assertNotEqual(len(sizes["ATTRIBUTE"]), len(sizes["INSTRUCT"]))

    def test_pass3_window_size_does_not_leak_into_pass2(self):
        # A large Step 3 value must not widen the Step 2 requests. Pass 3 asks for
        # the whole 200-line window and then subdivides it for the context budget
        # (does_instruct_batch_fit_context), so only its first request is counted.
        _entries, sizes = _run(200, attribute_batch_size=5,
                               instruct_batch_size=1000)
        self.assertEqual(40, len(sizes["ATTRIBUTE"]))
        self.assertTrue(all(k == 5 for k in sizes["ATTRIBUTE"]))
        self.assertEqual(200, sizes["INSTRUCT"][0])

    def test_default_pass3_window_is_unchanged(self):
        # Omitting the argument must behave exactly like the historical default.
        _entries, sizes = _run(60, attribute_batch_size=1000)
        self.assertEqual([25, 25, 10], sizes["INSTRUCT"])


class InstructBatchSizeResolverTests(unittest.TestCase):
    """The setting resolves once, through the shared settings seam."""

    def test_default_config_resolves_to_batch_size(self):
        settings = tp.resolve_three_pass_generation_settings(
            {"generation": {}}, None)
        self.assertEqual(tp.BATCH_SIZE, settings["instruct_batch_size"])
        self.assertEqual(25, settings["instruct_batch_size"])

    def test_saved_value_resolves(self):
        settings = tp.resolve_three_pass_generation_settings(
            {"generation": {"three_pass_instruct_batch_size": 40}}, None)
        self.assertEqual(40, settings["instruct_batch_size"])

    def test_config_default_and_bounds(self):
        self.assertEqual(25, cs.GenerationConfig().three_pass_instruct_batch_size)
        self.assertEqual(3000, cs.GenerationConfig(
            three_pass_instruct_batch_size=3000).three_pass_instruct_batch_size)
        for bad in (4, 3001):
            with self.assertRaises(Exception):
                cs.GenerationConfig(three_pass_instruct_batch_size=bad)

    def test_field_round_trips_through_the_config_model(self):
        saved = cs.GenerationConfig(
            three_pass_instruct_batch_size=40).model_dump()
        self.assertEqual(40, saved["three_pass_instruct_batch_size"])
        self.assertEqual(40, cs.GenerationConfig(**saved).three_pass_instruct_batch_size)

    def test_context_chars_neighbour_is_untouched(self):
        # The historical 06076917 commit deleted this field; it must stay intact.
        self.assertIn("three_pass_attribute_context_chars", cs.GenerationConfig.model_fields)
        self.assertEqual(2000, cs.GenerationConfig().three_pass_attribute_context_chars)


class InstructBatchSizeFingerprintTests(unittest.TestCase):
    """Default keeps existing checkpoint identity; a change invalidates it."""

    def _fingerprint(self, **kwargs):
        return tp.three_pass_fingerprint("Source text.", "fixture", 3000, None, **kwargs)

    def test_omitted_and_explicit_default_match(self):
        self.assertEqual(self._fingerprint(), self._fingerprint(instruct_batch_size=tp.BATCH_SIZE))
        self.assertEqual(self._fingerprint(), self._fingerprint(instruct_batch_size=25))

    def test_non_default_changes_settings_sha256(self):
        self.assertNotEqual(self._fingerprint(),
                            self._fingerprint(instruct_batch_size=40))

    def test_checkpoint_is_ignored_when_the_window_size_changes(self):
        base = self._fingerprint()
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "book.json")
            path = Path(tp.three_pass_checkpoint_path(output))
            state = {
                "fingerprint": base, "stage": "done", "chunks_done": 1,
                "segmented": [{"type": "NARRATOR", "text": "Target."}],
                "named": [{"speaker": "NARRATOR", "text": "Target."}],
                "annotated": [{"speaker": "NARRATOR", "text": "Target.",
                               "instruct": "Neutral."}],
                "resolutions": ["clean"], "elapsed_s": {"segment": 1.5},
                "diagnostic_failures": [],
            }
            path.write_text(json.dumps(state), encoding="utf-8")
            # Same fingerprint -> resumable.
            self.assertIsNotNone(
                tp._load_three_pass_checkpoint(output, base, chunk_count=1))
            # Changed Pass 3 window -> not accepted.
            self.assertIsNone(
                tp._load_three_pass_checkpoint(
                    output, self._fingerprint(instruct_batch_size=40), chunk_count=1))

    def test_pipeline_version_is_unchanged(self):
        import inspect
        source = inspect.getsource(tp.three_pass_fingerprint)
        self.assertIn('"pipeline_version": 9', source)


class InstructBatchSizePlanningTests(unittest.TestCase):
    """Planned calls and preflight agree with the real Pass 3 windowing."""

    def _settings(self, **overrides):
        settings = tp.resolve_three_pass_generation_settings({"generation": {}}, None)
        settings.update(overrides)
        return settings

    def test_planned_calls_agree_with_the_preflight_report(self):
        # The two independent Pass 3 windowing sites (planned-call counter and
        # the preflight request builder) must size windows identically.
        sources = ['Plain narration. More narration.',
                   'Alice waited. "One." Alice left. "Two." "One."',
                   '"A continued speech ' + 'word ' * 40 + 'ending."']
        for size in (5, 25, 40):
            for source in sources:
                settings = self._settings(instruct_batch_size=size)
                params = tp.get_three_pass_run_params(
                    {"llm_mode": "local", "llm_local": {"model_name": "fixture"}},
                    {"context_length": 32768, "max_tokens": 4096})
                expected = tp.planned_calls_from_preflight(
                    tp.build_three_pass_request_preflight(
                        source, settings, 32768, 1, params=params))
                actual = tp.get_three_pass_planned_calls(
                    source, settings, params)
                self.assertEqual(expected, actual, (size, source[:20]))

    def test_planned_call_count_changes_with_the_window(self):
        source = ('"Hello," she said. "Are you coming?" He nodded. '
                  '"Fine," she said, and turned away. "Later, then."\n\n'
                  'Nobody answered for a while. "Did you hear that?" he asked.\n\n'
                  '"I did," she said. "Listen again."\n\n')
        params = tp.get_three_pass_run_params(
            {"llm_mode": "local", "llm_local": {"model_name": "fixture"}},
            {"context_length": 8192, "max_tokens": 4096})
        seen = set()
        for size in (5, 25, 40):
            planned = tp.get_three_pass_planned_calls(
                source, self._settings(instruct_batch_size=size), params)
            self.assertIn(3, planned)
            seen.add(planned[3])
        # Distinct window sizes produce distinct pass-3 call counts.
        self.assertGreater(len(seen), 1)

    def test_preflight_uses_the_selected_window(self):
        source = ('"Hello," she said. "Are you coming?" He nodded.\n\n'
                  '"Fine," she said.\n\n')
        settings = self._settings(instruct_batch_size=40)
        params = tp.get_three_pass_run_params(
            {"llm_mode": "local", "llm_local": {"model_name": "fixture"}},
            {"context_length": 8192, "max_tokens": 4096})
        report = tp.build_three_pass_request_preflight(
            source, settings, 8192, 1, params=params)
        instruct_requests = [r for r in report["requests"] if r["stage"] == "instruct"]
        self.assertTrue(instruct_requests)


class RetryDeliveryPathUnchangedTests(unittest.TestCase):
    """The separate router-driven delivery-repair path is deliberately untouched."""

    def test_retry_delivery_has_no_instruct_batch_size_parameter(self):
        import inspect
        params = inspect.signature(tp.retry_delivery_instructions).parameters
        self.assertNotIn("instruct_batch_size", params)

    def test_retry_delivery_still_batches_at_the_default(self):
        import inspect
        source = inspect.getsource(tp.retry_delivery_instructions)
        self.assertIn("iter_unique_entry_batches(pending)", source)


if __name__ == "__main__":
    unittest.main()