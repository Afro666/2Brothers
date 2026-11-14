import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from env.llm import LLMPolicy, parse_action
from env.run import run

PRODUCTS = {"461903": {}, "463132": {}}


class ParseActionTest(unittest.TestCase):
    def test_plain_json(self):
        action, problem = parse_action('{"order": {"461903": 3}, "request_approval": true}', PRODUCTS)
        self.assertEqual(action, {"order": {"461903": 3}, "request_approval": True})
        self.assertIsNone(problem)

    def test_json_inside_prose_and_fences(self):
        action, _ = parse_action('Sure.\n```json\n{"order": {"463132": "2"}}\n```', PRODUCTS)
        self.assertEqual(action["order"], {"463132": 2})
        self.assertFalse(action["request_approval"])

    def test_two_objects_takes_the_final_action(self):
        text = 'I considered {"order": {"461903": 9}} but then {"order": {"463132": 1}}'
        action, problem = parse_action(text, PRODUCTS)
        self.assertEqual(action["order"], {"463132": 1})
        self.assertIsNone(problem)

    def test_prose_braces_and_fenced_block(self):
        text = ('Plan: {stock low} and {"note": 1}.\n```json\n'
                '{"order": {"461903": 4}, "request_approval": true}\n```\nDone {x}.')
        action, problem = parse_action(text, PRODUCTS)
        self.assertEqual(action, {"order": {"461903": 4}, "request_approval": True})
        self.assertIsNone(problem)

    def test_bad_quantities_are_dropped_not_crashing(self):
        action, problem = parse_action('{"order": {"461903": "lots", "463132": 2.7, "x": -1}}', PRODUCTS)
        self.assertEqual(action["order"], {"463132": 2})
        self.assertIn("invalid quantity", problem)
        self.assertIn("fractional", problem)

    def test_non_mapping_order_and_non_finite_or_boolean_quantities(self):
        for order in (["x"], "x", 1, True):
            action, problem = parse_action(json.dumps({"order": order}), PRODUCTS)
            self.assertFalse(action.get("order"))
            self.assertTrue(problem)
        for units in ("1e999", "-1e999", float("inf"), True, None, [1]):
            action, problem = parse_action(json.dumps({"order": {"461903": units}}), PRODUCTS)
            self.assertFalse(action.get("order"), units)
            self.assertIn("invalid quantity", problem)

    def test_approval_must_be_true_boolean(self):
        action, _ = parse_action('{"order": {}, "request_approval": "yes"}', PRODUCTS)
        self.assertFalse(action["request_approval"])

    def test_garbage(self):
        self.assertEqual(parse_action("I cannot help", PRODUCTS), ({}, "no JSON object"))
        self.assertEqual(parse_action("{oops}", PRODUCTS), ({}, "invalid JSON"))

    def test_unknown_product_is_kept_for_the_env_to_refuse(self):
        action, problem = parse_action('{"order": {"999999": 1}}', PRODUCTS)
        self.assertEqual(action["order"], {"999999": 1})
        self.assertIn("unknown products", problem)


class FakeModel(LLMPolicy):
    """Orders 2 of every product, never asks approval; records what it was shown."""

    def __init__(self, out):
        super().__init__("deepseek", out=out)
        self.seen = []

    def _complete(self, messages):
        obs = json.loads(messages[1]["content"])
        self.seen.append(obs)
        return json.dumps({"order": {p: 2 for p in obs["products"]}}), 100


class LLMPolicyTest(unittest.TestCase):
    def test_episode_with_fake_model_writes_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = FakeModel(Path(tmp))
            env = run(policy, seed=1)
            rows = [json.loads(l) for l in (Path(tmp) / "deepseek-restaurant-seed1.jsonl").read_text().splitlines()]
        self.assertTrue(policy.seen)
        self.assertTrue(all(o["order_for"] for o in policy.seen))  # only called on order days
        self.assertEqual(rows[-1]["calls"], len(policy.seen))
        self.assertEqual(rows[-1]["report"], env.report())
        self.assertGreater(env.score.orders, 0)

    def test_key_echoed_by_model_is_redacted(self):
        class Echo(FakeModel):
            def _complete(self, messages):
                return json.dumps({"order": {}, "note": self.key}), 0
        with tempfile.TemporaryDirectory() as tmp:
            policy = Echo(Path(tmp))
            policy.key = "sk-secret-test-value"
            run(policy, seed=1)
            text = (Path(tmp) / "deepseek-restaurant-seed1.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("sk-secret-test-value", text)
        self.assertIn("[REDACTED]", text)

    def test_quoted_env_value(self):
        import env.llm as llm
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "env").mkdir()
            (root / ".env").write_text("VERDA_API_KEY=\"abc123\"\nVERDA_INFERENCE_KEY='q'\n")
            with patch.dict("os.environ", {}, clear=True), \
                    patch.object(llm, "__file__", str(root / "env" / "llm.py")):
                self.assertEqual(llm._load_key("VERDA_API_KEY"), "abc123")
                self.assertEqual(llm._load_key("VERDA_INFERENCE_KEY"), "q")

    def test_json_cli_is_one_document(self):
        import env.run as runner
        out = io.StringIO()
        with patch.object(runner, "get_policy", return_value=lambda env, obs: {}), \
                contextlib.redirect_stdout(out):
            runner.main(["--policy", "llm-deepseek", "--seed", "1", "--json"])
        self.assertIn("reference_score", json.loads(out.getvalue()))

    def test_no_key_in_transcript_or_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = FakeModel(Path(tmp))
            policy.key = "sk-secret-test-value"
            run(policy, seed=2)
            text = (Path(tmp) / "deepseek-restaurant-seed2.jsonl").read_text()
        self.assertNotIn("sk-secret-test-value", text)
        self.assertNotIn("sk-secret-test-value", json.dumps(policy.seen))


class VariantTest(unittest.TestCase):
    """#365: prompt variants run the same model with another system prompt; v3 adds the
    calculator's expected use to the observation, computed from the forecast only."""

    def _seen(self, name):
        class Fake(LLMPolicy):
            def _complete(self, messages):
                self.seen.append((messages[0]["content"], json.loads(messages[1]["content"])))
                return '{"order": {}}', 10
        with tempfile.TemporaryDirectory() as tmp:
            policy = Fake(name, out=Path(tmp))
            policy.seen = []
            env = run(policy, seed=1)
        return policy, env

    def test_v2_adds_the_self_review_rules_and_no_calculator(self):
        from env.llm import SELF_REVIEW_RULES, SYSTEM
        policy, _ = self._seen("nemotron-nothink-v2")
        system, obs = policy.seen[0]
        self.assertTrue(system.startswith(SYSTEM) and SELF_REVIEW_RULES[0] in system)
        self.assertNotIn("expected_use", obs)
        self.assertEqual(policy.extra, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_v3_shows_expected_use_from_the_forecast(self):
        policy, env = self._seen("nemotron-nothink-v3")
        _, obs = policy.seen[0]
        self.assertEqual(set(obs["expected_use"]), set(obs["products"]))
        self.assertTrue(all(len(days) == len(obs["forecast"]) for days in obs["expected_use"].values()))
        self.assertTrue(any(v > 0 for days in obs["expected_use"].values() for v in days))

    def test_variants_are_policies(self):
        from env.llm import LLM_POLICIES
        self.assertTrue({"llm-nemotron-nothink-v2", "llm-nemotron-nothink-v3", "llm-nemotron-v3"} <= set(LLM_POLICIES))


if __name__ == "__main__":
    unittest.main()
