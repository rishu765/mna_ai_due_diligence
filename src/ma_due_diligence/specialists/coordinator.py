"""Failure-isolated M4/5 coordinator; this is deliberately not a graph runtime."""

from __future__ import annotations

from dataclasses import replace

from ma_due_diligence.domain import (
    DiligenceEngagement,
    DiligenceFact,
    DiligenceFinding,
    FollowUpQuestion,
    MissingInformation,
    VdrDocument,
)
from ma_due_diligence.financial.models import FinancialFindingOutput
from ma_due_diligence.retrieval.models import (
    DiligenceEvidenceResult,
    RetrievalFilters,
    RetrievalWarning,
)
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.specialists.analyzers import (
    CommercialDiligenceAnalyzer,
    FinancialDiligenceAnalyzer,
    LegalContractualAnalyzer,
    OperationalDiligenceAnalyzer,
    SpecialistAnalyzer,
)
from ma_due_diligence.specialists.claims import extract_claims
from ma_due_diligence.specialists.consolidation import (
    FindingConsolidator,
    build_relationships,
    build_traces,
    conflict_findings,
    consolidate_requests,
    create_compound_customer_risk,
)
from ma_due_diligence.specialists.investigation import (
    CrossDocumentInvestigator,
    mark_claim_statuses,
)
from ma_due_diligence.specialists.models import (
    AgentError,
    CoordinatorResult,
    SpecialistContext,
    SpecialistResult,
)


class SpecialistCoordinator:
    def __init__(
        self,
        retriever: HybridDiligenceRetriever,
        *,
        analyzers: tuple[SpecialistAnalyzer, ...] | None = None,
        investigator: CrossDocumentInvestigator | None = None,
        consolidator: FindingConsolidator | None = None,
    ) -> None:
        self._retriever = retriever
        self._analyzers = analyzers or (
            FinancialDiligenceAnalyzer(),
            CommercialDiligenceAnalyzer(),
            LegalContractualAnalyzer(),
            OperationalDiligenceAnalyzer(),
        )
        self._investigator = investigator or CrossDocumentInvestigator()
        self._consolidator = consolidator or FindingConsolidator()

    def run(
        self,
        *,
        engagement: DiligenceEngagement,
        documents: tuple[VdrDocument, ...],
        facts: tuple[DiligenceFact, ...] = (),
        existing_findings: tuple[DiligenceFinding, ...] = (),
        financial_findings: tuple[FinancialFindingOutput, ...] = (),
    ) -> CoordinatorResult:
        evidence_by_agent: dict[str, tuple[DiligenceEvidenceResult, ...]] = {}
        warning_by_agent: dict[str, tuple[RetrievalWarning, ...]] = {}
        all_results: dict[str, DiligenceEvidenceResult] = {}
        errors: list[AgentError] = []
        for analyzer in self._analyzers:
            collected: dict[str, DiligenceEvidenceResult] = {}
            warnings: list[RetrievalWarning] = []
            try:
                for query in analyzer.retrieval_plan.queries:
                    response = self._retriever.retrieve(
                        query,
                        filters=RetrievalFilters(
                            engagement.engagement_id,
                            document_types=analyzer.retrieval_plan.document_types,
                            workstreams=analyzer.retrieval_plan.workstreams,
                        ),
                        top_k=analyzer.retrieval_plan.top_k_per_query,
                    )
                    for result in response.results:
                        collected[result.chunk_id] = result
                        all_results[result.chunk_id] = result
                    warnings.extend(response.warnings)
                evidence_by_agent[analyzer.agent_id.value] = tuple(collected.values())
                warning_by_agent[analyzer.agent_id.value] = tuple(warnings)
            except Exception as error:
                errors.append(AgentError(analyzer.agent_id, type(error).__name__, str(error)))
                evidence_by_agent[analyzer.agent_id.value] = ()
                warning_by_agent[analyzer.agent_id.value] = ()

        claims = extract_claims(tuple(all_results.values()), documents)
        investigation = self._investigator.compare(claims, engagement.engagement_id)
        claims = mark_claim_statuses(claims, investigation)

        specialist_results: list[SpecialistResult] = []
        for analyzer in self._analyzers:
            context = SpecialistContext(
                engagement,
                documents,
                evidence_by_agent[analyzer.agent_id.value],
                claims,
                facts,
                existing_findings,
                financial_findings,
                warning_by_agent[analyzer.agent_id.value],
            )
            try:
                specialist_results.append(analyzer.analyze(context))
            except Exception as error:
                errors.append(AgentError(analyzer.agent_id, type(error).__name__, str(error)))

        raw_findings = tuple(
            finding for result in specialist_results for finding in result.findings
        ) + conflict_findings(engagement.engagement_id, claims, investigation)
        consolidated = self._consolidator.consolidate(raw_findings)
        compound = create_compound_customer_risk(engagement.engagement_id, consolidated)
        relationships = build_relationships(consolidated, compound)
        findings = consolidated if compound is None else (*consolidated, compound)
        missing = _deduplicate_missing(
            tuple(item for result in specialist_results for item in result.missing_information)
        )
        questions: tuple[FollowUpQuestion, ...] = tuple(
            item for result in specialist_results for item in result.questions
        )
        requests = consolidate_requests(missing, questions)
        return CoordinatorResult(
            tuple(specialist_results),
            investigation,
            findings,
            relationships,
            missing,
            requests,
            build_traces(findings),
            tuple(errors),
        )


def _deduplicate_missing(
    values: tuple[MissingInformation, ...],
) -> tuple[MissingInformation, ...]:
    by_key: dict[str, MissingInformation] = {}
    for item in values:
        key = " ".join(item.requested_item.casefold().split())
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = item
        elif item.blocking and not existing.blocking:
            by_key[key] = replace(item, blocking=True)
    return tuple(by_key[key] for key in sorted(by_key))
