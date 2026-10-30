# Model API usage and cost

Written by `python3 -m agents.usage_report bench/cost/meta-usage-2026-10-24-to-30.csv` from the dev.meta.ai usage export for the team (all keys); do not edit by hand. List prices: dev.meta.ai/docs/pricing-rate-limits, read October 29, 2026; tokens at Muse Spark Standard rates.

| Day | Requests | SAM images | SAM video frames | Muse tokens in (cached / uncached) | Muse tokens out | SAM at list | Muse at list | Total at list | Billed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-10-27 | 1 | 0 | 0 | 0 / 1,375 | 2,930 | $0.00 | $0.01 | $0.01 | $0.00 |
| 2026-10-28 | 8,960 | 8,859 | 0 | 3,502,544 / 597,861 | 74,371 | $22.15 | $1.59 | $23.74 | $0.00 |
| 2026-10-29 | 74,052 | 72,088 | 2,160 | 102,171,369 / 9,600,691 | 1,657,963 | $180.65 | $34.37 | $215.02 | $54.33 |
| **Total** | 83,013 | 80,947 | 2,160 | 105,673,913 / 10,199,927 | 1,735,264 | $202.80 | $35.98 | $238.78 | $54.33 |
