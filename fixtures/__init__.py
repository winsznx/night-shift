"""Synthetic research-lab estate fixtures.

Everything here is generated from a seed. No real patient names, no real institutional
data, no PHI. Every record carries ``synthetic: true`` and the UI labels it as such
(PRD §25).
"""

from fixtures.estate import (
    EstateFixture,
    build_estate,
    estate_hash,
    seed_repository,
)

__all__ = ["EstateFixture", "build_estate", "estate_hash", "seed_repository"]
