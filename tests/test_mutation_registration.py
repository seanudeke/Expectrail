"""The mutation bench's registration must keep loading on main until the bench is recorded.

Its pins are the sha256 of the code that judged the runs (bench/mutation/preregistration.json). A
change to any pinned file makes every mutation bench run, plan and record refuse to start. #170 did
that to agents/judge_bench.py and nothing caught it until a record failed, so this catches it on the
pull request instead.
"""
from __future__ import annotations

import unittest

from agents import mutate_game as mg


class RegistrationLoadsTest(unittest.TestCase):
    def test_the_registration_still_loads(self):
        try:
            mg.load_preregistration()
        except mg.PreregistrationError as exc:
            self.fail(f"{exc}\nA pinned file changed after registration, which blocks every mutation bench run "
                      "and record. Put it back byte for byte and make the change in a file that is not pinned.")


if __name__ == "__main__":
    unittest.main()
