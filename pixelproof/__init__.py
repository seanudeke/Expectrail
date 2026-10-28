"""Pixel Proof: shared contracts and the reference evaluator."""

from pixelproof.legacy import adopt_legacy_env as _adopt_legacy_env

__version__ = "0.1.0"

# Accept NIGHTSHIFT_* settings from before the October 28 rename (see pixelproof/legacy.py).
_adopt_legacy_env()
