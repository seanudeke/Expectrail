"""Reading the dev.meta.ai usage export: byte-order mark, CRLF, list prices per day and in total."""
import tempfile
import unittest
from pathlib import Path

import agents.usage_report as ur

CSV = ("﻿date,metric,series,value,unit\r\n"
       "2026-10-29,spend,total,5.5,USD\r\n"
       "2026-10-29,images_processed,total,1000,images\r\n"
       "2026-10-29,video_frames_processed,total,1000,frames\r\n"
       "2026-10-29,input_tokens,cached,1000000,tokens\r\n"
       "2026-10-29,input_tokens,uncached,1000000,tokens\r\n"
       "2026-10-29,output_tokens,output,1000000,tokens\r\n"
       "2026-10-29,requests,total,1002,requests\r\n"
       "2026-10-30,requests,total,0,requests\r\n")


class UsageReportTest(unittest.TestCase):
    def test_list_price_and_billed_per_day_and_in_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.csv"
            path.write_bytes(CSV.encode("utf-8"))
            doc = ur.summarize(ur.read(path))
        self.assertEqual([d["date"] for d in doc["days"]], ["2026-10-29"])  # a day with no use is left out
        t = doc["total"]
        self.assertEqual(t["samListUsd"], 2.70)    # 1,000 images at $2.50 per 1,000 + 1,000 video frames at $0.20
        self.assertEqual(t["museListUsd"], 5.65)   # $0.15 + $1.25 + $4.25 per million
        self.assertEqual((t["listUsd"], t["billedUsd"], t["requests"]), (8.35, 5.5, 1002))
        md = ur.markdown(doc, "x.csv")
        self.assertIn("| **Total** | 1,002 | 1,000 | 1,000 |", md)

    def test_credits_are_added_and_the_matching_muse_mode_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "usage.csv"
            path.write_bytes(CSV.encode("utf-8"))
            days = ur.read(path)
        doc = ur.summarize(days, credits=0.0)
        # Contributor tokens: $0.002 + $0.10 + $0.20 per million = $0.30; SAM $2.70; total $3.00 against $5.50 billed
        self.assertEqual(doc["total"]["listContributorUsd"], 3.0)
        self.assertEqual((doc["actualUsd"], doc["museModeThatMatches"]), (5.5, "contributor"))
        doc = ur.summarize(days, credits=2.85)
        self.assertEqual((doc["actualUsd"], doc["museModeThatMatches"], doc["matchOffUsd"]), (8.35, "standard", 0.0))
        self.assertIn("$5.50 billed + $2.85 of free credits = **$8.35**", ur.markdown(doc, "x.csv"))


if __name__ == "__main__":
    unittest.main()
