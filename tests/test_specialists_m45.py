from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from ma_due_diligence.domain import (
    ConflictStatus,
    DiligenceWorkstream,
    DocumentType,
    EvidenceReference,
    EvidenceSourceType,
    FinancialPeriod,
    PeriodKind,
    Priority,
)
from ma_due_diligence.retrieval.embedding import DeterministicHashEmbedder
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.specialists.analyzers import CommercialDiligenceAnalyzer
from ma_due_diligence.specialists.coordinator import SpecialistCoordinator
from ma_due_diligence.specialists.evaluation import evaluate_specialist_result
from ma_due_diligence.specialists.explanations import GroundedExplanationService
from ma_due_diligence.specialists.fixtures import (
    build_m3_financial_findings,
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.specialists.investigation import CrossDocumentInvestigator
from ma_due_diligence.specialists.models import (
    AgentId,
    AttributedFinding,
    ClaimStatus,
    ClaimValueKind,
    ComparisonOutcome,
    CoordinatorResult,
    GroundedExplanation,
    InvestigationClaim,
    SourceAuthority,
    SpecialistContext,
    SpecialistResult,
)
from ma_due_diligence.specialists.plans import COMMERCIAL_PLAN
from ma_due_diligence.vdr.ingestion import VdrIngestionPipeline, manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest, VdrCorpus

SpecialistRun = tuple[VdrCorpus, CoordinatorResult]


@pytest.fixture(scope="module")
def specialist_result(tmp_path_factory: pytest.TempPathFactory) -> SpecialistRun:
    root = tmp_path_factory.mktemp("specialist-vdr")
    engagement = build_specialist_engagement()
    manifest = manifest_from_json(create_specialist_fixture_vdr(root))
    corpus = VdrIngestionPipeline().ingest(
        IngestionRequest(engagement.engagement_id, manifest=manifest)
    )
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    result = SpecialistCoordinator(HybridDiligenceRetriever(index)).run(
        engagement=engagement,
        documents=tuple(item.document for item in corpus.documents),
        financial_findings=build_m3_financial_findings(),
    )
    return corpus, result


def test_commercial_analysis_is_grounded_and_does_not_claim_market_research(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    commercial = next(
        item for item in result.specialist_results if item.agent_id is AgentId.COMMERCIAL
    )
    categories = {item.finding.category for item in commercial.findings}
    assert {"customer_concentration", "customer_renewal", "growth_sustainability"} <= categories
    assert all(item.finding.evidence for item in commercial.findings)
    assert "External market research was not performed" in commercial.warnings[0]


def test_contract_analysis_preserves_clause_provenance_and_revised_version(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    legal = next(
        item for item in result.specialist_results if item.agent_id is AgentId.LEGAL_CONTRACTUAL
    )
    categories = {item.finding.category for item in legal.findings}
    assert {
        "change_of_control_consent",
        "termination_for_convenience",
        "assignment_restriction",
    } <= categories
    assert all(item.finding.evidence[0].source_text for item in legal.findings)
    assert all(item.finding.evidence[0].document_id for item in legal.findings)
    assert result.investigation.superseded_claim_ids
    assert "not legal advice" in legal.warnings[0]


def test_operational_analysis_detects_supplier_and_capacity_risks(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    operational = next(
        item for item in result.specialist_results if item.agent_id is AgentId.OPERATIONAL
    )
    categories = {item.finding.category for item in operational.findings}
    assert {
        "supplier_concentration",
        "single_source_dependency",
        "capacity_constraint",
    } <= categories
    assert all(item.finding.evidence for item in operational.findings)
    assert any(
        "continuity" in item.requested_item.casefold() for item in operational.missing_information
    )


def test_investigation_detects_numeric_and_semantic_conflicts() -> None:
    investigator = CrossDocumentInvestigator()
    claims = (
        _claim("c1", "revenue", ClaimValueKind.NUMBER, Decimal("92"), SourceAuthority.AUDITED),
        _claim(
            "c2",
            "revenue",
            ClaimValueKind.NUMBER,
            Decimal("100"),
            SourceAuthority.MANAGEMENT_NARRATIVE,
        ),
        _claim(
            "c3",
            "customer_concentration_present",
            ClaimValueKind.BOOLEAN,
            False,
            SourceAuthority.MANAGEMENT_NARRATIVE,
        ),
        _claim(
            "c4",
            "customer_concentration_present",
            ClaimValueKind.BOOLEAN,
            True,
            SourceAuthority.DIRECT_SCHEDULE,
        ),
    )
    result = investigator.compare(claims, "eng-test")
    assert {item.topic for item in result.conflicts} == {
        "revenue",
        "customer_concentration_present",
    }
    assert all(
        item.status is ConflictStatus.OPEN and item.review_required for item in result.conflicts
    )
    revenue = next(item for item in result.comparisons if item.left_claim_id == "c1")
    assert revenue.preferred_claim_id == "c1"


def test_investigation_avoids_false_cross_period_conflict() -> None:
    fy24 = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2024")
    fy25 = FinancialPeriod(PeriodKind.FISCAL_YEAR, "FY2025")
    left = replace(
        _claim("c1", "revenue", ClaimValueKind.NUMBER, Decimal("92"), SourceAuthority.AUDITED),
        period=fy24,
    )
    right = replace(
        _claim("c2", "revenue", ClaimValueKind.NUMBER, Decimal("100"), SourceAuthority.AUDITED),
        period=fy25,
    )
    result = CrossDocumentInvestigator().compare((left, right), "eng-test")
    assert not result.conflicts
    assert result.comparisons[0].outcome is ComparisonOutcome.NOT_COMPARABLE


def test_investigation_marks_old_document_version_superseded() -> None:
    old = replace(
        _claim("old", "contract_expiry", ClaimValueKind.DATE, date(2026, 12, 31)),
        version="v1",
        effective_date=date(2024, 1, 1),
        logical_document_key="apex_contract",
    )
    new = replace(
        _claim("new", "contract_expiry", ClaimValueKind.DATE, date(2027, 12, 31)),
        evidence=_evidence("ev-new", "doc-new"),
        version="v2",
        effective_date=date(2025, 7, 1),
        logical_document_key="apex_contract",
    )
    result = CrossDocumentInvestigator().compare((old, new), "eng-test")
    assert result.superseded_claim_ids == ("old",)
    assert not result.conflicts


def test_findings_are_consolidated_and_compound_risk_keeps_all_sources(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    concentration = [
        item for item in result.findings if item.finding.category == "customer_concentration"
    ]
    assert len(concentration) == 1
    assert {AgentId.FINANCIAL, AgentId.COMMERCIAL} <= set(concentration[0].contributing_agents)
    compound = next(
        item for item in result.findings if item.finding.category == "compound_customer_retention"
    )
    assert len(compound.source_finding_ids) == 3
    assert len(compound.finding.evidence) >= 2
    assert len(result.relationships) == 3


def test_distinct_findings_remain_distinct(specialist_result: SpecialistRun) -> None:
    _, result = specialist_result
    categories = {item.finding.category for item in result.findings}
    assert "supplier_concentration" in categories
    assert "capacity_constraint" in categories


def test_information_requests_are_structured_and_deduplicated(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    assert result.requests
    assert len({item.question.casefold() for item in result.requests}) == len(result.requests)
    assert any(item.priority is Priority.URGENT for item in result.requests)
    assert all(item.workstreams and item.rationale for item in result.requests)


def test_agent_failure_is_isolated(specialist_result: SpecialistRun) -> None:
    corpus, _ = specialist_result
    index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
    index.index(corpus.chunks, rebuild=True)
    coordinator = SpecialistCoordinator(
        HybridDiligenceRetriever(index),
        analyzers=(_FailingAnalyzer(), CommercialDiligenceAnalyzer()),
    )
    result = coordinator.run(
        engagement=build_specialist_engagement(),
        documents=tuple(item.document for item in corpus.documents),
    )
    assert result.errors[0].agent_id is AgentId.OPERATIONAL
    assert any(item.agent_id is AgentId.COMMERCIAL for item in result.specialist_results)


def test_grounded_explanation_rejects_unknown_citations(
    specialist_result: SpecialistRun,
) -> None:
    _, result = specialist_result
    finding = next(item for item in result.findings if item.finding.evidence)

    class BadProvider:
        def explain(self, item: AttributedFinding) -> GroundedExplanation:
            return GroundedExplanation(
                item.finding.finding_id,
                "Unsupported text",
                (),
                "Review required",
                None,
                ("invented-evidence",),
            )

    with pytest.raises(ValueError, match="outside the finding context"):
        GroundedExplanationService(BadProvider()).explain(finding)


def test_m45_evaluation_keeps_categories_separate(specialist_result: SpecialistRun) -> None:
    _, result = specialist_result
    report = evaluate_specialist_result(result)
    assert report.passed == len(report.checks) == 10
    assert len({item.category for item in report.checks}) == 10


class _FailingAnalyzer:
    agent_id = AgentId.OPERATIONAL
    retrieval_plan = COMMERCIAL_PLAN

    def analyze(self, context: SpecialistContext) -> SpecialistResult:
        raise RuntimeError("fixture specialist failure")


def _evidence(evidence_id: str, document_id: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id,
        EvidenceSourceType.VDR_DOCUMENT,
        document_id=document_id,
        source_text="Fixture source",
    )


def _claim(
    claim_id: str,
    topic: str,
    kind: ClaimValueKind,
    value: Decimal | bool | date,
    authority: SourceAuthority = SourceAuthority.OTHER,
) -> InvestigationClaim:
    return InvestigationClaim(
        claim_id,
        "Target",
        topic,
        kind,
        f"Fixture claim {claim_id}",
        _evidence(f"ev-{claim_id}", f"doc-{claim_id}"),
        DocumentType.OTHER,
        DiligenceWorkstream.OPERATIONAL,
        authority,
        numeric_value=value if isinstance(value, Decimal) else None,
        boolean_value=value if isinstance(value, bool) else None,
        date_value=value if isinstance(value, date) else None,
        unit="GBP million" if isinstance(value, Decimal) else None,
        status=ClaimStatus.SOURCE_BACKED,
    )
