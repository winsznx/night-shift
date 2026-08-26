"""Night Shift Drill Range — the assurance plane.

No agent or skill revision gets operational authority because it builds. It gets
authority because it survived the disaster drill corpus, and the verdict is computed by
deterministic Python over stored artifacts (PRD §23.4).
"""

from assurance.corpus import DRILLS, DrillSpec, load_corpus
from assurance.faults import FaultInjector, FaultSpec
from assurance.qualify import (
    DrillOutcome,
    QualificationRun,
    qualify_revision,
    score_drill,
)

__all__ = [
    "DRILLS",
    "DrillOutcome",
    "DrillSpec",
    "FaultInjector",
    "FaultSpec",
    "QualificationRun",
    "load_corpus",
    "qualify_revision",
    "score_drill",
]
