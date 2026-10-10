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
from ma_due_diligence.financial import FinancialMetric, FinancialObservation
from ma_due_diligence.fixtures import build_synthetic_fixture
from ma_due_diligence.retrieval import (
    DeterministicHashEmbedder,
    HybridDiligenceRetriever,
    InMemoryDiligenceIndex,
    RagContextBuilder,
    RetrievalFilters,
)
from ma_due_diligence.serialization import model_from_json, model_to_json
from ma_due_diligence.vdr import IngestionRequest, VdrCorpus, VdrIngestionPipeline, VdrManifest

__all__ = [
    "DiligenceEngagement",
    "DiligenceFact",
    "DiligenceFinding",
    "DiligenceFixtureSet",
    "DiligenceSummary",
    "EvidenceReference",
    "FinancialAdjustment",
    "FinancialMetric",
    "FinancialObservation",
    "DeterministicHashEmbedder",
    "HybridDiligenceRetriever",
    "InMemoryDiligenceIndex",
    "IngestionRequest",
    "RagContextBuilder",
    "RetrievalFilters",
    "VdrDocument",
    "VdrCorpus",
    "VdrIngestionPipeline",
    "VdrManifest",
    "build_synthetic_fixture",
    "model_from_json",
    "model_to_json",
]
