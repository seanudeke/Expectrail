"""The Mutation record workflow: it plans and records with the repo's own tools, and never writes to main."""
from __future__ import annotations

import re
import subprocess
import unittest

import yaml

from harness.run import REPO

PATH = REPO / ".github" / "workflows" / "mutation-record.yml"


class MutationRecordWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = PATH.read_text(encoding="utf-8")
        self.doc = yaml.safe_load(self.text)
        self.jobs = self.doc["jobs"]

    def step(self, job: str) -> str:
        return next(s["run"] for s in self.jobs[job]["steps"] if "GH_TOKEN" in str(s.get("env")))

    def test_it_only_runs_when_dispatched(self):
        self.assertEqual(set(self.doc[True]), {"workflow_dispatch"})

    def test_the_private_set_and_secrets_are_never_touched(self):
        self.assertNotIn("Nightshift-heldout", self.text)
        self.assertNotIn("HELDOUT", self.text)
        self.assertNotIn("secrets.", self.text)

    def test_only_the_record_job_can_write_and_the_plan_job_holds_no_push_credential(self):
        self.assertEqual(self.doc["permissions"], {"contents": "read"})
        self.assertEqual(self.jobs["plan"]["permissions"], {"contents": "read", "actions": "read"})
        self.assertEqual(self.jobs["record"]["permissions"], {"contents": "write", "actions": "read"})
        self.assertIs(self.jobs["plan"]["steps"][0]["with"]["persist-credentials"], False)

    def test_both_jobs_run_from_main_on_validated_run_ids(self):
        for job, pattern in (("plan", r"^[0-9]+$"), ("record", r"^[0-9]+(,[0-9]+)*$")):
            with self.subTest(job=job):
                run = self.step(job)
                self.assertIn('[[ "$GITHUB_REF" == refs/heads/main ]]', run)
                self.assertIn(f'[[ "$RUNS" =~ {pattern} ]]', run)
                self.assertNotIn("${{", run)  # inputs reach the shell as env, never spliced into it

    def test_it_uses_the_repos_own_recorders(self):
        self.assertIn("python -m agents.mutation_collect --plan-sam", self.step("plan"))
        record = self.step("record")
        self.assertIn("python -m agents.mutation_collect --part generated", record)
        self.assertIn("python -m agents.mutation_fix --record", record)

    def test_a_record_is_pushed_to_a_new_branch_never_main(self):
        record = self.step("record")
        pushes = re.findall(r"git push .*", record)
        self.assertEqual(pushes, ['git push origin "HEAD:refs/heads/${branch}"'])
        self.assertIn('branch="bench/record-${ACTION#record-}-${GITHUB_RUN_ID}"', record)
        self.assertIn('git add -A -- "$dir"', record)

    def test_the_shell_steps_parse(self):
        for job in ("plan", "record"):
            with self.subTest(job=job):
                subprocess.run(["bash", "-n"], input=self.step(job), text=True, check=True)


if __name__ == "__main__":
    unittest.main()
