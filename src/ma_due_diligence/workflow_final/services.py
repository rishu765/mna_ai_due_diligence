"""Injectable service bundle for the final workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.specialists.coordinator import SpecialistCoordinator
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline
from ma_due_diligence.workflow_final.financial import run_fixture_financial_diligence
from ma_due_diligence.workflow_final.models import FinancialDiligenceSnapshot
from ma_due_diligence.workflow_final.reporting import DiligenceReportGenerator


@dataclass(frozen=True, slots=True)
class WorkflowServices:
    """Dependencies are replaceable for production adapters and failure tests."""

    ingestion: VdrIngestionPipeline = field(default_factory=VdrIngestionPipeline)
    report_generator: DiligenceReportGenerator = field(default_factory=DiligenceReportGenerator)
    financial_runner: Callable[[str], FinancialDiligenceSnapshot] = run_fixture_financial_diligence
    coordinator_factory: Callable[[HybridDiligenceRetriever], SpecialistCoordinator] = (
        SpecialistCoordinator
    )
