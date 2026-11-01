"""Outside screenshot judges: the same prompt and frames as Muse's judge, failing closed, keys kept apart."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents.outside_judge as oj
from agents.keys import muse_subprocess_env
from agents.muse_judge import build_judge_prompt

KEYS = {"ANTHROPIC_API_KEY": "test-anthropic-key-not-real", "OPENAI_API_KEY": "test-openai-key-not-real"}


def frames(tmp: Path, n: int = 5) -> tuple[list[Path], list[Path]]:
    before, after = [], []
    for i in range(n):
        for side, out in (("b", before), ("a", after)):
            p = tmp / f"{side}{i}.png"
            p.write_bytes(f"png-{side}-{i}".encode())
            out.append(p)
    return before, after


def anthropic_reply(text: str) -> dict:
    return {"model": "claude-fable-5-1", "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "DECISION: accept"}, {"type": "text", "text": text}],
            "usage": {"input_tokens": 20000, "output_tokens": 1000}}


def openai_reply(text: str) -> dict:
    return {"model": "gpt-6-astra", "status": "completed",
            "output": [{"type": "reasoning", "summary": []},
                       {"type": "message", "content": [{"type": "output_text", "text": text}]}],
            "usage": {"input_tokens": 15000, "output_tokens": 3000}}


class Poster:
    """A fake API: each vendor's answers in turn (the vendors are asked side by side), and what it was sent."""

    def __init__(self, *answers):
        import threading
        self.answers = {"anthropic": [], "openai": []}
        for status, payload in answers:
            vendor = "openai" if isinstance(payload, dict) and "output" in payload else "anthropic"
            if status != 200 and isinstance(payload, dict):
                vendor = payload.pop("_vendor", "anthropic")
            self.answers[vendor].append((status, payload))
        self.sent = []
        self.lock = threading.Lock()

    def __call__(self, url, headers, body, timeout=None):
        vendor = "anthropic" if "anthropic" in url else "openai"
        with self.lock:
            self.sent.append((url, headers, body))
            return self.answers[vendor].pop(0)

    def to(self, vendor):
        return [s for s in self.sent if vendor in s[0]]


class OutsideJudgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.before, self.after = frames(self.tmp)
        env = mock.patch.dict(os.environ, KEYS)
        env.start()
        self.addCleanup(env.stop)
        for j in oj.JUDGES.values():
            os.environ.pop(j["modelEnv"], None)

    def test_the_prompt_is_muse_judges_prompt_byte_for_byte(self):
        b, a = oj.labels(self.before, self.after)
        muse_prompt = build_judge_prompt(before_rel=b, after_rel=a, instruction="A player reported: x")
        post = Poster((200, anthropic_reply("ok\nDECISION: reject")), (200, openai_reply("DECISION: reject")))
        oj.judge_frames(self.tmp / "o", before=self.before, after=self.after, instruction="A player reported: x",
                        names=["claude", "gpt"], passes=1, post=post, sleep=lambda s: None)
        claude_body, gpt_body = post.to("anthropic")[0][2], post.to("openai")[0][2]
        self.assertEqual(claude_body["messages"][0]["content"][0]["text"], muse_prompt)
        self.assertEqual(gpt_body["input"][0]["content"][0]["text"], muse_prompt)
        self.assertEqual((self.tmp / "o" / "prompt.txt").read_text(), muse_prompt)

    def test_every_frame_is_attached_once_after_its_file_name(self):
        b, a = oj.labels(self.before, self.after)
        body = oj.anthropic_body("m", "p", list(zip(b + a, self.before + self.after)))
        content = body["messages"][0]["content"][2:]
        self.assertEqual(len(content), 20)
        for k, (label, path) in enumerate(zip(b + a, self.before + self.after)):
            self.assertEqual(content[2 * k]["text"], f"{label}:")
            self.assertEqual(base64.b64decode(content[2 * k + 1]["source"]["data"]), path.read_bytes())
        body = oj.openai_body("m", "p", list(zip(b + a, self.before + self.after)), "high")
        images = [c for c in body["input"][0]["content"] if c["type"] == "input_image"]
        self.assertEqual(len(images), 10)
        self.assertTrue(all(c["detail"] == "high" and c["image_url"].startswith("data:image/png;base64,")
                            for c in images))
        self.assertEqual(body["reasoning"], {"effort": "high"})

    def test_decisions_are_read_from_the_answer_text_only(self):
        # A DECISION line inside Claude's thinking block is not its answer.
        post = Poster((200, anthropic_reply("The robot is drawn inside the ground.\nDECISION: reject")))
        r = oj.call("claude", "p", [], post=post, sleep=lambda s: None)
        self.assertEqual((r["decision"], r["ok"], r["model"]), ("reject", True, "claude-fable-5-1"))
        post = Poster((200, anthropic_reply("I could not decide.")))  # the thinking block says accept
        self.assertIsNone(oj.call("claude", "p", [], post=post, sleep=lambda s: None)["decision"])
        post = Poster((200, openai_reply("DECISION: accept\nOn reflection:\nDECISION: reject")))
        self.assertEqual(oj.call("gpt", "p", [], post=post, sleep=lambda s: None)["decision"], "reject")

    def test_no_decision_line_is_undecided_never_a_rejection(self):
        post = Poster((200, anthropic_reply("I cannot tell from these frames.")))
        r = oj.call("claude", "p", [], post=post, sleep=lambda s: None)
        self.assertIsNone(r["decision"])
        self.assertFalse(r["ok"])

    def test_a_missing_key_sends_nothing(self):
        post = Poster()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            r = oj.call("gpt", "p", [], post=post, sleep=lambda s: None)
        self.assertEqual(post.sent, [])
        self.assertIsNone(r["decision"])
        self.assertIn("OPENAI_API_KEY is not set", r["detail"])

    def test_a_rate_limit_is_waited_out_and_a_refusal_is_not_retried(self):
        waits = []
        post = Poster((429, {"error": {"message": "slow down"}, "_vendor": "openai"}), (200, openai_reply("DECISION: accept")))
        r = oj.call("gpt", "p", [], post=post, sleep=waits.append)
        self.assertEqual((r["decision"], r["attempts"], len(waits)), ("accept", 2, 1))
        post = Poster((400, {"error": {"message": "model not found"}}))
        r = oj.call("claude", "p", [], post=post, sleep=waits.append)
        self.assertEqual((r["decision"], r["attempts"], len(post.sent)), (None, 1, 1))
        self.assertIn("HTTP 400: model not found", r["detail"])

    def test_the_keys_go_only_in_the_auth_header_and_never_into_a_file(self):
        post = Poster((200, anthropic_reply("DECISION: reject")), (200, openai_reply("DECISION: reject")))
        oj.judge_frames(self.tmp / "o", before=self.before, after=self.after, instruction="x",
                        names=["claude", "gpt"], passes=1, post=post, sleep=lambda s: None)
        self.assertEqual(post.to("anthropic")[0][1]["x-api-key"], KEYS["ANTHROPIC_API_KEY"])
        self.assertEqual(post.to("openai")[0][1]["authorization"], f"Bearer {KEYS['OPENAI_API_KEY']}")
        for (_url, _headers, body) in post.sent:
            for key in KEYS.values():
                self.assertNotIn(key, json.dumps(body))
        for f in (self.tmp / "o").rglob("*"):
            if f.is_file():
                text = f.read_text()
                for key in KEYS.values():
                    self.assertNotIn(key, text, f)

    def test_the_keys_never_reach_muse_code(self):
        env = muse_subprocess_env({**KEYS, "META_API_KEY": "m", "PATH": "/usr/bin"})
        for name in KEYS:
            self.assertNotIn(name, env)

    def test_every_pass_is_its_own_request_and_is_recorded(self):
        post = Poster(*[(200, anthropic_reply(f"DECISION: {d}")) for d in ("accept", "reject", "accept")])
        res = oj.judge_frames(self.tmp / "o", before=self.before, after=self.after, instruction="x",
                              names=["claude"], passes=3, post=post, sleep=lambda s: None)
        self.assertEqual(len(post.sent), 3)
        self.assertEqual(res["claude"]["decisions"], ["accept", "reject", "accept"])
        self.assertTrue(all((self.tmp / "o" / f"claude-pass-{n}.json").is_file() for n in (1, 2, 3)))
        # 3 x (20,000 in at $10/M + 1,000 out at $50/M) = $0.75
        self.assertAlmostEqual(res["claude"]["usd"], 0.75)

    def test_a_model_variable_names_another_model(self):
        with mock.patch.dict(os.environ, {"EXPECTRAIL_OUTSIDE_CLAUDE_MODEL": "claude-opus-5-5"}):
            post = Poster((200, anthropic_reply("DECISION: reject")))
            oj.call("claude", "p", [], post=post, sleep=lambda s: None)
        self.assertEqual(post.sent[0][2]["model"], "claude-opus-5-5")


class CollectTest(unittest.TestCase):
    RESULTS = {
        "bad/fall-through-sink-player": ("bad", {"claude": ["accept", "reject", "reject"], "gpt": ["reject"] * 3}, "accept"),
        "bad/fall-through-freeze": ("bad", {"claude": ["reject"] * 3, "gpt": ["reject", None, "reject"]}, "reject"),
        "good/sinking/v1": ("good", {"claude": ["accept"] * 3, "gpt": ["reject", "accept", "accept"]}, "reject"),
    }

    def fake_fetch(self, live=True):
        notes = []
        for case, (label, decisions, muse) in self.RESULTS.items():
            results = {n: {"model": oj.JUDGES[n]["model"], "decisions": d, "reasons": ["it looks fine"] * 3,
                           "usd": 0.5} for n, d in decisions.items()}
            for line in oj.annotation(case, label, results):
                title, message = line[len("::notice title="):].split("::", 1)
                notes.append({"title": title, "message": message})
            notes.append({"title": f"Judge {case}", "message": f"label {label}; SAM on None; SAM off reject; "
                                                               f"Muse screenshots {muse}; 300.0 s; live={live}"})

        def fetch(path):
            if path.endswith("/jobs?per_page=100"):
                return {"jobs": [{"name": "judge-run (x)", "id": 1}]}
            if "/check-runs/" in path:
                return notes
            return {"html_url": "https://example/run/9", "head_sha": "abc1234", "created_at": "2026-11-01T15:00:00Z"}
        return fetch

    def test_annotations_round_trip_into_per_pass_scores(self):
        doc = oj.collect(9, fetch=self.fake_fetch())
        s = doc["scores"]
        self.assertEqual([p["badAccepted"] for p in s["claude"]["passes"]], [1, 0, 0])
        self.assertEqual([p["goodAccepted"] for p in s["gpt"]["passes"]], [0, 1, 1])
        self.assertEqual([p["undecided"] for p in s["gpt"]["passes"]], [0, 1, 0])
        self.assertEqual(s["museScreenshots"]["passes"][0]["badAccepted"], 1)
        self.assertEqual(s["claude"]["models"], ["claude-fable-5-1"])
        self.assertEqual(doc["estimatedUsd"], 3.0)
        md = oj.markdown(doc)
        self.assertIn("| Claude | claude-fable-5-1 | 1 | 1 of 1 | 1 of 2 | 0 |", md)
        self.assertIn("| bad/fall-through-sink-player | reject | accept | accept, reject, reject | reject, reject, reject |", md)

    def test_an_offline_run_is_refused(self):
        with self.assertRaises(SystemExit):
            oj.collect(9, fetch=self.fake_fetch(live=False))


class SmokeTest(unittest.TestCase):
    def test_smoke_fails_on_a_missing_key_or_a_refusal(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "k"}):
            self.assertEqual(oj.smoke(post=Poster((200, openai_reply("DECISION: accept")))), 1)
        with mock.patch.dict(os.environ, KEYS):
            self.assertEqual(oj.smoke(post=Poster((200, anthropic_reply("DECISION: accept")),
                                                  (404, {"error": {"message": "no such model"}, "_vendor": "openai"}))), 1)
            post = Poster((200, anthropic_reply("DECISION: accept")), (200, openai_reply("DECISION: accept")))
            self.assertEqual(oj.smoke(post=post), 0)
        # The check sends a real game frame in the benchmark's own image format.
        claude, gpt = post.to("anthropic")[0][2], post.to("openai")[0][2]
        self.assertEqual(base64.b64decode(claude["messages"][0]["content"][3]["source"]["data"]),
                         oj.SMOKE_FRAME.read_bytes())
        self.assertEqual(sum(c["type"] == "input_image" for c in gpt["input"][0]["content"]), 1)


if __name__ == "__main__":
    unittest.main()
