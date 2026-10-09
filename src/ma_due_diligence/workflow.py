"""Conceptual state for the future graph; M0 does not construct or run a graph."""

from __future__ import annotations

from typing import TypedDict

from ma_due_diligence.domain import (
    BalanceSheetItem,
    DiligenceEngagement,
    DiligenceFact,
    DiligenceFinding,
    DiligenceSummary,
    EvidenceReference,
    FactConflict,
    FinancialAdjustment,
    FollowUpQuestion,
    HumanReviewAction,
    MissingInformation,
    ReportSectionContract,
    RunStatus,
    VdrDocument,
)


class DiligenceGraphState(TypedDict, total=False):
    """Data that later LangGraph nodes may exchange and checkpoint."""

    engagement: DiligenceEngagement
    documents: tuple[VdrDocument, ...]
    document_classifications: tuple[str, ...]
    retrieved_evidence: tuple[EvidenceReference, ...]
    extracted_facts: tuple[DiligenceFact, ...]
    conflicts: tuple[FactConflict, ...]
    findings: tuple[DiligenceFinding, ...]
    adjustments: tuple[FinancialAdjustment, ...]
    balance_sheet_items: tuple[BalanceSheetItem, ...]
    missing_information: tuple[MissingInformation, ...]
    follow_up_questions: tuple[FollowUpQuestion, ...]
    human_decisions: tuple[HumanReviewAction, ...]
    report_sections: tuple[ReportSectionContract, ...]
    summary: DiligenceSummary
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    run_status: RunStatus
