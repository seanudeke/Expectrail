"""Voice feedback intake: rules, model merge, drafts, transcription request shape, CLI, contract."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path
from unittest import mock

from agents import feedback as fb
from harness.run import REPO
from nightshift import spec_writer
from nightshift.contracts import ContractError, validate

FIX = REPO / "agents" / "fixtures" / "feedback"
TRANSCRIPT = FIX / "playtest-transcript.json"
SPARK = FIX / "spark-fixture.json"


def _turns() -> list[dict]:
    return fb.turns_from_response(json.loads(TRANSCRIPT.read_text()))


def _source() -> dict:
    return {"kind": "transcript", "file": TRANSCRIPT.name, "sha256": fb.sha256_file(TRANSCRIPT),
            "durationMs": 32000, "transcriber": {"provenance": "fixture", "model": None, "mode": "DIARIZATION"}}


def _wav(path: Path, *, channels=1, rate=24000, width=2, seconds=0.5) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(rate * seconds) * channels * width)
    return path


class RulesTest(unittest.TestCase):
    def test_requests_to_weaken_a_check_are_caught(self):
        for text in (
            "just turn the floor check off so we can ship",
            "if the floor check keeps failing, just turn it off",
            "Can you skip the held-out tests tonight?",
            "delete that spec, it's flaky",
            "loosen the tolerance on the ground test",
            "bump the threshold to 40 pixels",
            "mark all the tests as passing",
            "just ship it",
            "accept it anyway",
            "comment out the verifier",
            "make the coin check optional",
            "Ship it regardless of the checks",
            "Don't run the floor check",
            "Set the tolerance to 500 pixels",
            "make the test pass",
            "The floor test is broken, please make it always succeed.",
        ):
            with self.subTest(text=text):
                self.assertEqual(fb.classify_rules(text), "weaken-check")

    def test_bug_request_and_other(self):
        self.assertEqual(fb.classify_rules("the robot fell straight through the floor"), "bug")
        self.assertEqual(fb.classify_rules("a coin disappeared when I walked past it"), "bug")
        self.assertEqual(fb.classify_rules("it would be nice if the robot could double jump"), "request")
        self.assertIsNone(fb.classify_rules("Okay, I'm on the first level now."))
        self.assertIsNone(fb.classify_rules("turn off the music please"))
        self.assertIsNone(fb.classify_rules("the second platform is fun"))

    def test_weaken_wins_over_bug_in_one_remark(self):
        text = "the robot falls through the floor, just disable that test"
        self.assertEqual(fb.classify_rules(text), "weaken-check")

    def test_decide_lets_either_side_send_to_a_person(self):
        turn = {"speaker": "B", "startMs": 0, "text": "the robot fell through the floor, just disable the test"}
        item = fb.decide(0, turn, {"category": "bug", "instruction": "x", "reason": "r"}, "model")
        self.assertEqual((item["category"], item["route"]), ("weaken-check", "human-queue"))
        self.assertEqual(item["decidedBy"], ["rule"])
        self.assertIsNone(item["instruction"])
        quiet = {"speaker": "B", "startMs": 0, "text": "you know what to do with that floor thing"}
        item = fb.decide(0, quiet, {"category": "weaken-check", "instruction": None, "reason": "r"}, "model")
        self.assertEqual((item["category"], item["decidedBy"]), ("weaken-check", ["model"]))
        item = fb.decide(0, quiet, None, "model")
        self.assertEqual((item["category"], item["route"], item["decidedBy"]), ("other", "logged", ["default"]))


class IntakeTest(unittest.TestCase):
    def test_fixture_run_drafts_bugs_and_refuses_weakening(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            doc = fb.intake(_turns(), out=out, intake_id="fb-test", source=_source(),
                            transport=fb.fixture_transport(json.loads(SPARK.read_text())),
                            classifier_label="fixture")
            self.assertEqual(validate(doc), "feedback-intake")
            self.assertEqual(doc["counts"], {"bug": 2, "weaken-check": 2, "request": 1, "other": 2})
            self.assertEqual(doc["policy"]["toFixer"], "never")
            drafts = [i for i in doc["items"] if i.get("draft")]
            self.assertEqual(len(drafts), 2)
            for item in drafts:
                spec = json.loads((out / item["draft"]["path"]).read_text())
                self.assertEqual(validate(spec), "test-spec")
                self.assertNotIn("approval", spec)
                self.assertFalse(item["draft"]["approved"])
            weak = [i for i in doc["items"] if i["category"] == "weaken-check"]
            self.assertEqual([i["turn"] for i in weak], [3, 5])
            for item in weak:
                self.assertEqual(item["route"], "human-queue")
                self.assertIsNone(item["draft"])
            # turn 5 is "other" in the fixture: only the fixed rule caught it
            self.assertEqual(weak[1]["decidedBy"], ["rule"])
            names = [p.name for p in out.rglob("*")]
            self.assertFalse([n for n in names if "repair-request" in n])
            self.assertTrue((out / "feedback-intake.json").is_file())

    def test_rules_only_never_drafts_from_raw_speech(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-test", source=_source(), transport=None,
                            classifier_label="model")
            self.assertEqual(doc["classifier"]["provenance"], "rules-only")
            bugs = [i for i in doc["items"] if i["category"] == "bug"]
            self.assertEqual(len(bugs), 2)
            for item in bugs:
                self.assertEqual(item["route"], "human-queue")
                self.assertIsNone(item["draft"])
                self.assertIsNone(item["instruction"])
            self.assertFalse((Path(tmp) / "drafts").exists())

    def test_model_failure_falls_back_to_rules_and_says_so(self):
        def broken(body):
            raise spec_writer.SpecDraftError("HTTP 500: upstream")

        with tempfile.TemporaryDirectory() as tmp:
            doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-test", source=_source(), transport=broken,
                            classifier_label="model")
            self.assertEqual(doc["classifier"]["provenance"], "rules-only")
            self.assertIn("HTTP 500", doc["classifier"]["error"])
            self.assertEqual(doc["counts"]["weaken-check"], 2)
            for item in doc["items"]:
                if item["category"] == "bug":
                    self.assertEqual(item["route"], "human-queue")
                    self.assertIsNone(item["draft"])

    def test_junk_model_answers_never_crash_or_draft(self):
        junk = [
            {"choices": [{"message": {"content": None}}]},
            {"choices": []},
            {"choices": [{"message": {"content": "[1, 2]"}}]},
            {"choices": [{"message": {"content": "{\"items\": \"lots\"}"}}]},
        ]
        for answer in junk:
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as tmp:
                doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-test", source=_source(),
                                transport=lambda body, a=answer: a, classifier_label="model")
                self.assertEqual(doc["classifier"]["provenance"], "rules-only")
                self.assertNotIn("\n", doc["classifier"]["error"])
                self.assertFalse(any(i.get("draft") for i in doc["items"]))

    def test_a_bad_draft_answer_is_a_problem_not_a_crash(self):
        fixture = json.loads(SPARK.read_text())
        classify = fixture["classify"]

        def transport(body):
            if body["messages"][0]["content"] == fb.CLASSIFIER_SYSTEM:
                return {"choices": [{"message": {"content": json.dumps(classify)}}]}
            return {"choices": [{"message": {"content": "[\"not\", \"a spec\"]"}}]}

        with tempfile.TemporaryDirectory() as tmp:
            doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-test", source=_source(), transport=transport,
                            classifier_label="model")
            bugs = [i for i in doc["items"] if i["route"] == "draft-spec"]
            self.assertEqual(len(bugs), 2)
            for item in bugs:
                self.assertIsNone(item["draft"])
                self.assertTrue(item["draftProblems"])

    def test_model_cannot_slip_a_weakening_past(self):
        turn = {"speaker": "A", "startMs": 0, "text": "the robot fell through the floor"}
        sneaky = {"category": "bug", "instruction": "Skip the floor check during CI.", "reason": "bug"}
        item = fb.decide(0, turn, sneaky, "model")
        self.assertEqual((item["category"], item["route"], item["draft"], item["instruction"]),
                         ("weaken-check", "human-queue", None, None))
        long = {"category": "bug", "instruction": "The player never falls through the ground. " * 10, "reason": ""}
        item = fb.decide(0, turn, long, "model")
        self.assertEqual((item["category"], item["route"], item["instruction"]), ("bug", "human-queue", None))

        def two_answers(body):
            items = [{"turn": 0, "category": "bug", "instruction": "x", "reason": ""},
                     {"turn": 0, "category": "weaken-check", "instruction": None, "reason": "asks to skip"}]
            return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}

        self.assertEqual(fb.classify_model([turn], two_answers)[0]["category"], "weaken-check")

    def test_long_intake_ids_still_give_one_file_per_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-" + "very-long-playtest-name-" * 4,
                            source=_source(), transport=fb.fixture_transport(json.loads(SPARK.read_text())),
                            classifier_label="fixture")
            paths = [i["draft"]["path"] for i in doc["items"] if i.get("draft")]
            self.assertEqual(len(paths), 2)
            self.assertEqual(len(set(paths)), 2)

    def test_a_draft_that_arrives_approved_loses_its_approval(self):
        fixture = json.loads(SPARK.read_text())
        for spec in fixture["drafts"].values():
            spec["approval"] = {"by": "playtester", "at": "2026-10-28T00:00:00Z"}
        with tempfile.TemporaryDirectory() as tmp:
            doc = fb.intake(_turns(), out=Path(tmp), intake_id="fb-test", source=_source(),
                            transport=fb.fixture_transport(fixture), classifier_label="fixture")
            for item in doc["items"]:
                if item.get("draft"):
                    spec = json.loads((Path(tmp) / item["draft"]["path"]).read_text())
                    self.assertNotIn("approval", spec)

    def test_model_items_out_of_range_or_unknown_are_ignored(self):
        turns = _turns()

        def transport(body):
            items = [{"turn": 99, "category": "bug", "instruction": "x", "reason": ""},
                     {"turn": 0, "category": "ship-it", "instruction": None, "reason": ""},
                     {"turn": 6, "category": "other", "instruction": None, "reason": "praise"}]
            return {"choices": [{"message": {"content": json.dumps({"items": items})}}]}

        got = fb.classify_model(turns, transport)
        self.assertEqual(sorted(got), [6])

    def test_contributor_tier_is_refused(self):
        with self.assertRaises(fb.FeedbackError):
            fb.classify_model(_turns(), lambda body: {}, model="muse-spark-1.3-contributor")
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(Path(tmp) / "a.wav")
            with self.assertRaises(fb.FeedbackError):
                fb.transcribe_request(wav, keywords=[], model="muse-voice-transcribe-1.0-contributor", key="k")

    def test_keywords_come_from_spec_prompts(self):
        words = fb.game_keywords()
        self.assertIn("blue robot", words)
        self.assertIn("gold coin", words)
        self.assertEqual(len(words), len({w.lower() for w in words}))


class TranscribeTest(unittest.TestCase):
    def test_request_shape_matches_the_file_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(Path(tmp) / "clip.wav")
            req = fb.transcribe_request(wav, keywords=["blue robot"], key="secret",
                                        api_base="https://api.meta.ai/v1")
            self.assertEqual(req.full_url, "https://api.meta.ai/v1/asr/transcribe")
            self.assertEqual(req.get_method(), "POST")
            self.assertEqual(req.get_header("Authorization"), "Bearer secret")
            ctype = req.get_header("Content-type")
            self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
            body = req.data
            self.assertIn(b'name="request"', body)
            self.assertIn(b'name="audio"; filename="clip.wav"', body)
            self.assertIn(wav.read_bytes(), body)
            start = body.index(b"\r\n\r\n", body.index(b'name="request"')) + 4
            config = json.loads(body[start:body.index(b"\r\n--", start)])
            self.assertEqual(config, {"mode": "DIARIZATION", "model": fb.TRANSCRIBE_MODEL,
                                      "audioEncoding": "WAV", "keywords": ["blue robot"]})

    def test_wav_format_is_checked_before_any_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok = fb.check_wav(_wav(Path(tmp) / "ok.wav", rate=16000))
            self.assertEqual(ok["rate"], 16000)
            for kwargs in ({"channels": 2}, {"rate": 44100}, {"width": 1}):
                with self.subTest(**kwargs):
                    with self.assertRaisesRegex(fb.FeedbackError, "ffmpeg"):
                        fb.check_wav(_wav(Path(tmp) / "bad.wav", **kwargs))
            junk = Path(tmp) / "junk.wav"
            junk.write_bytes(b"not audio")
            with self.assertRaises(fb.FeedbackError):
                fb.check_wav(junk)

    def test_transcribe_parses_turns_and_explains_errors(self):
        response = json.loads(TRANSCRIPT.read_text())

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(Path(tmp) / "clip.wav")
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}):
                got = fb.transcribe(wav, keywords=[], opener=lambda req, timeout: Resp(json.dumps(response).encode()))
                self.assertEqual(len(fb.turns_from_response(got)), 7)

                def denied(req, timeout):
                    raise urllib.error.HTTPError(req.full_url, 401, "nope", {}, io.BytesIO(b"bad key"))

                with self.assertRaisesRegex(fb.FeedbackError, "401.*MODEL_API_KEY"):
                    fb.transcribe(wav, keywords=[], opener=denied)

    def test_odd_turn_shapes_are_dropped_not_fatal(self):
        turns = fb.turns_from_response({"turns": ["nope", {"speaker": 0, "startMs": "1.5", "transcript": "hi"},
                                                  {"speaker": "B", "startMs": None, "transcript": 7},
                                                  {"speaker": None, "startMs": -3, "text": "yo"}]})
        self.assertEqual(turns, [{"speaker": "0", "startMs": 1, "text": "hi"},
                                 {"speaker": "?", "startMs": 0, "text": "yo"}])
        with self.assertRaises(fb.FeedbackError):
            fb.turns_from_response(["not", "a", "dict"])

    def test_turns_without_diarization(self):
        self.assertEqual(fb.turns_from_response({"transcript": " hello "}),
                         [{"speaker": "?", "startMs": 0, "text": "hello"}])
        self.assertEqual(fb.turns_from_response({"transcript": ""}), [])
        turns = fb.turns_from_response({"turns": [{"speaker": "A", "startMs": 5, "transcript": "  "},
                                                  {"speaker": "B", "startMs": 9, "transcript": "hi"}]})
        self.assertEqual(turns, [{"speaker": "B", "startMs": 9, "text": "hi"}])


class CliTest(unittest.TestCase):
    def test_offline_fixture_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = fb.main(["--offline", "--transcript", str(TRANSCRIPT), "--fixture", str(SPARK), "--out", tmp])
            self.assertEqual(rc, 0)
            doc = json.loads((Path(tmp) / "feedback-intake.json").read_text())
            self.assertEqual(doc["classifier"]["provenance"], "fixture")
            self.assertEqual(len(list((Path(tmp) / "drafts").glob("*.json"))), 2)

    def test_guard_rails_on_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = _wav(Path(tmp) / "clip.wav")
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}):
                with mock.patch.object(fb, "transcribe") as called:
                    self.assertEqual(fb.main(["--audio", str(wav), "--out", tmp]), 1)  # no --consent
                    called.assert_not_called()
            self.assertEqual(fb.main(["--transcript", str(TRANSCRIPT), "--fixture", str(SPARK), "--out", tmp]), 1)
            self.assertEqual(fb.main(["--offline", "--audio", str(wav), "--consent", "--out", tmp]), 1)
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": ""}):
                self.assertEqual(fb.main(["--transcript", str(TRANSCRIPT), "--consent", "--out", tmp]), 1)
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}):
                with mock.patch.object(fb.spec_writer, "http_transport") as called:
                    # a live run on a transcript still sends people's words to Meta: consent first
                    self.assertEqual(fb.main(["--transcript", str(TRANSCRIPT), "--out", tmp]), 1)
                    called.assert_not_called()


class ReportTest(unittest.TestCase):
    def _verification(self):
        doc = json.loads((REPO / "contracts" / "examples" / "verification.json").read_text())
        doc["checks"] = [c for c in doc["checks"] if c["kind"] != "gameplay"]
        return doc

    def _report(self, tmp: Path, **kwargs) -> tuple[str, dict]:
        from agents.report import build_report
        from agents.signing import generate_run_keys

        keys = generate_run_keys(tmp / "verifier-host")
        summary = build_report(verification=self._verification(), candidate=None, out=tmp / "morning",
                               signing_key_path=keys["privatePathObj"], **kwargs)
        return (tmp / "morning" / "morning-report.md").read_text(), summary

    def test_sections_show_feedback_refusals_and_guard_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            self.assertEqual(fb.main(["--offline", "--transcript", str(TRANSCRIPT), "--fixture", str(SPARK),
                                      "--out", str(tmp / "feedback")]), 0)
            guard = {"installed": True, "loaded": True, "calls": 9, "blocked": [
                {"tool": "write_file", "rel": "specs/player-stays-above-ground.json", "reason": "outside"},
                {"tool": "web_fetch", "reason": "web_fetch is not available to the fixer"}]}
            md, summary = self._report(tmp, feedback=tmp / "feedback" / "feedback-intake.json", guard=guard)
            feedback_in = md.split("## Feedback in", 1)[1].split("## Refused or blocked", 1)[0]
            refused = md.split("## Refused or blocked", 1)[1].split("## Unresolved for a human", 1)[0]
            self.assertIn("fell straight through the floor", feedback_in)
            self.assertIn("not used until a person approves it", feedback_in)
            self.assertIn("double jump", feedback_in)
            self.assertIn("nothing from feedback goes to the fixer", feedback_in)
            self.assertNotIn("turn it off", feedback_in)
            self.assertIn("just turn it off so we can ship tonight", refused)
            self.assertIn("mark all the tests as passing", refused)
            self.assertIn("blocked `write_file` on `specs/player-stays-above-ground.json`", refused)
            self.assertIn("blocked `web_fetch`", refused)
            self.assertIn("by its own log it checked 9 tool call(s) and blocked 2", refused)
            self.assertEqual(summary["feedback"]["refused"], 2)
            self.assertEqual(len(summary["feedback"]["drafts"]), 2)
            self.assertEqual(summary["guard"], {"installed": True, "loaded": True, "calls": 9, "blocked": 2})

    def test_hostile_text_renders_as_text(self):
        doc = json.loads((REPO / "contracts" / "examples" / "feedback-intake.json").read_text())
        hostile = "look ![pwned](https://evil.example/x.png) <script> www.evil.com @someone `tick`"
        doc["items"][0]["text"] = hostile
        with tempfile.TemporaryDirectory() as tmp:
            md, _ = self._report(Path(tmp), feedback=doc)
            line = next(l for l in md.splitlines() if "pwned" in l)
            # the whole remark is one code span: GitHub renders no image, link, HTML or mention in it
            self.assertIn("`" + hostile.replace("`", "'") + "`", line)
            self.assertEqual(line.count("`"), 2 + 2)  # the speaker's span and the remark's span

    def test_unconfirmed_guard_and_no_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            md, summary = self._report(Path(tmp), guard={"installed": True, "loaded": False, "calls": 0,
                                                         "blocked": []})
            self.assertIn("not confirmed", md)
            self.assertNotIn("## Feedback in", md)
        with tempfile.TemporaryDirectory() as tmp:
            md, summary = self._report(Path(tmp))
            self.assertNotIn("## Refused or blocked", md)
            self.assertNotIn("feedback", summary)


class WorkflowTest(unittest.TestCase):
    def test_live_feedback_is_manual_and_needs_consent(self):
        import re

        live = (REPO / ".github" / "workflows" / "feedback-live.yml").read_text()
        triggers = live.split("\non:", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        for other in ("pull_request", "push:", "schedule"):
            self.assertNotIn(other, triggers)
        self.assertEqual([l for l in re.findall(r"(?m)^    if:.*$", live) if "secrets." in l], [])
        self.assertIn('if [ "$CONSENT" != "true" ]', live)
        self.assertNotIn("${{ inputs.audio }}\"", live.split("steps:", 1)[1])  # inputs reach run via env only

    def test_offline_job_uses_no_keys(self):
        ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
        job = ci.split("\n  feedback-offline:", 1)[1].split("\n  agents-sandbox:", 1)[0]
        self.assertNotIn("secrets.", job)
        self.assertIn("--offline", job)


class ContractTest(unittest.TestCase):
    def _doc(self):
        return json.loads((REPO / "contracts" / "examples" / "feedback-intake.json").read_text())

    def test_example_is_valid_and_rules_are_encoded(self):
        self.assertEqual(validate(self._doc()), "feedback-intake")
        doc = self._doc()
        weak = next(i for i in doc["items"] if i["category"] == "weaken-check")
        weak["route"] = "draft-spec"
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        next(i for i in doc["items"] if i["category"] == "request")["route"] = "draft-spec"
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        next(i for i in doc["items"] if i.get("draft"))["draft"]["approved"] = True
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        doc["policy"]["toFixer"] = "sometimes"
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        next(i for i in doc["items"] if i["category"] == "request")["draft"] = {
            "path": "drafts/x.json", "specId": "x", "approved": False}
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        next(i for i in doc["items"] if i["category"] == "weaken-check")["instruction"] = "Skip it."
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        next(i for i in doc["items"] if i["category"] == "weaken-check")["decidedBy"] = ["default"]
        with self.assertRaises(ContractError):
            validate(doc)
        doc = self._doc()
        doc["items"][0]["turn"] = len(doc["turns"])
        with self.assertRaisesRegex(ContractError, "past the last turn"):
            validate(doc)
        doc = self._doc()
        doc["counts"]["bug"] += 1
        with self.assertRaisesRegex(ContractError, "counts"):
            validate(doc)
        doc = self._doc()
        doc["source"]["kind"] = "audio"
        with self.assertRaises(ContractError):
            validate(doc)  # audio needs consent: true
        doc["source"]["consent"] = True
        self.assertEqual(validate(doc), "feedback-intake")


if __name__ == "__main__":
    unittest.main()
