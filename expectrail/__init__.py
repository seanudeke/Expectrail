"""Expectrail: shared contracts and the reference evaluator."""

from expectrail.legacy import adopt_legacy_env as _adopt_legacy_env

__version__ = "0.1.0"

# Accept NIGHTSHIFT_* settings from before the October 30 rename (see expectrail/legacy.py).
_adopt_legacy_env()
