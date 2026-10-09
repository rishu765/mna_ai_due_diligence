"""Evidence-first M&A due-diligence domain foundation."""

from ma_due_diligence.domain import (
    DiligenceEngagement,
    DiligenceFact,
    DiligenceFinding,
    DiligenceFixtureSet,
    DiligenceSummary,
    EvidenceReference,
    FinancialAdjustment,
    VdrDocument,
)
from ma_due_diligence.fixtures import build_synthetic_fixture
from ma_due_diligence.serialization import model_from_json, model_to_json

__all__ = [
    "DiligenceEngagement",
    "DiligenceFact",
    "DiligenceFinding",
    "DiligenceFixtureSet",
    "DiligenceSummary",
    "EvidenceReference",
    "FinancialAdjustment",
    "VdrDocument",
    "build_synthetic_fixture",
    "model_from_json",
    "model_to_json",
]
