from __future__ import annotations

from ma_due_diligence.contracts import DocumentClassification, EvidenceQuery
from ma_due_diligence.domain import (
    DiligenceFixtureSet,
    DiligenceSummary,
    DiligenceWorkstream,
    DocumentType,
    ReportSectionContract,
    ReportSectionType,
    ReviewStatus,
    RunStatus,
    WorkstreamStatus,
    WorkstreamSummary,
)
from ma_due_diligence.workflow import DiligenceGraphState


def test_report_and_summary_contracts(diligence_fixture: DiligenceFixtureSet) -> None:
    financial = WorkstreamSummary(
        DiligenceWorkstream.FINANCIAL,
        WorkstreamStatus.IN_PROGRESS,
        finding_count=1,
        high_or_critical_count=0,
        open_question_count=1,
    )
    summary = DiligenceSummary(
        diligence_fixture.engagement,
        (financial,),
        total_findings=2,
        high_or_critical_findings=2,
        unresolved_conflicts=1,
        missing_information_count=1,
        proposed_adjustment_count=1,
        human_review_status=ReviewStatus.IN_PROGRESS,
    )
    section = ReportSectionContract(
        ReportSectionType.FINANCIAL_DILIGENCE,
        "Financial diligence",
        DiligenceWorkstream.FINANCIAL,
        adjustment_ids=("adjustment-legal-fees",),
        missing_item_ids=("missing-debt-schedule",),
    )
    assert summary.unresolved_conflicts == 1
    assert section.requires_human_approval is True


def test_future_vdr_and_graph_contracts_are_data_only(
    diligence_fixture: DiligenceFixtureSet,
) -> None:
    classification = DocumentClassification(
        "doc-audited-fs",
        DocumentType.FINANCIAL_STATEMENTS,
        (DiligenceWorkstream.FINANCIAL,),
        "Audited statements contain the primary financial disclosures.",
    )
    query = EvidenceQuery(
        diligence_fixture.engagement.engagement_id,
        "FY2025 revenue",
        workstreams=(DiligenceWorkstream.FINANCIAL,),
        document_types=(DocumentType.FINANCIAL_STATEMENTS,),
    )
    state: DiligenceGraphState = {
        "engagement": diligence_fixture.engagement,
        "documents": diligence_fixture.documents,
        "retrieved_evidence": diligence_fixture.evidence,
        "extracted_facts": diligence_fixture.facts,
        "run_status": RunStatus.INITIALIZED,
    }
    assert classification.document_type is DocumentType.FINANCIAL_STATEMENTS
    assert query.limit == 10
    assert state["run_status"] is RunStatus.INITIALIZED
