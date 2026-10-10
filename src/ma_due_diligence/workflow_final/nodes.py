"""Thin LangGraph nodes that call M1-M5 services and preserve an audit trace."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, cast

from langgraph.types import interrupt

from ma_due_diligence.domain import ReviewActionType, Severity
from ma_due_diligence.errors import IndexingError, VdrIngestionError
from ma_due_diligence.retrieval.embedding import DeterministicHashEmbedder
from ma_due_diligence.retrieval.index import InMemoryDiligenceIndex
from ma_due_diligence.retrieval.models import RetrievalFilters
from ma_due_diligence.retrieval.service import HybridDiligenceRetriever
from ma_due_diligence.vdr.ingestion import manifest_from_json
from ma_due_diligence.vdr.models import IngestionRequest
from ma_due_diligence.workflow_final.models import (
    DiligenceWorkflowResult,
    FailureCode,
    HumanReviewInput,
    HumanReviewSubmission,
    ReviewDecision,
    RunEvaluationMetadata,
    TraceEvent,
    WorkflowIssue,
    WorkflowState,
    WorkflowStatus,
)
from ma_due_diligence.workflow_final.reporting import prioritize_findings
from ma_due_diligence.workflow_final.review import apply_review, build_review_request
from ma_due_diligence.workflow_final.services import WorkflowServices


class WorkflowNodes:
    def __init__(self, services: WorkflowServices, retry_ingestion: int, retry_report: int) -> None:
        self.services = services
        self.retry_ingestion = retry_ingestion
        self.retry_report = retry_report

    def validate_engagement(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        request = state["request"]
        if not request.manifest_path.is_file():
            return self._fail(
                state,
                FailureCode.INVALID_INPUT,
                "validate_engagement",
                f"Manifest does not exist: {request.manifest_path}",
                started,
            )
        return self._update(
            status=WorkflowStatus.INGESTING,
            trace=self._trace(
                state, "validate_engagement", WorkflowStatus.INGESTING, started, "Input validated."
            ),
        )

    def ingest_vdr(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        request = state["request"]
        attempt = state.get("retry_counts", {}).get("ingestion", 0) + 1
        try:
            manifest = manifest_from_json(request.manifest_path, request.run_id)
            corpus = self.services.ingestion.ingest(
                IngestionRequest(request.run_id, manifest=manifest)
            )
            if not corpus.documents:
                return self._fail(
                    state,
                    FailureCode.NO_DOCUMENTS,
                    "ingest_vdr",
                    "No readable documents were ingested.",
                    started,
                    attempt,
                )
        except (OSError, VdrIngestionError) as error:
            if attempt <= self.retry_ingestion:
                return self._retry(state, "ingestion", attempt, "ingest_vdr", str(error), started)
            return self._fail(
                state, FailureCode.INGESTION_FAILED, "ingest_vdr", str(error), started, attempt
            )
        warnings = tuple(issue.message for issue in corpus.issues)
        return self._update(
            corpus=corpus,
            documents=tuple(item.document for item in corpus.documents),
            status=WorkflowStatus.ANALYZING,
            retry_stage=None,
            warnings=tuple(dict.fromkeys((*state.get("warnings", ()), *warnings))),
            trace=self._trace(
                state,
                "ingest_vdr",
                WorkflowStatus.ANALYZING,
                started,
                f"Ingested {len(corpus.documents)} documents.",
            ),
        )

    def build_index(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        index = InMemoryDiligenceIndex(DeterministicHashEmbedder())
        try:
            report = index.index(state["corpus"].chunks, rebuild=True)
        except IndexingError as error:
            return self._fail(
                state, FailureCode.RETRIEVAL_INSUFFICIENT, "build_index", str(error), started
            )
        return self._update(
            index=index,
            trace=self._trace(
                state,
                "build_index",
                WorkflowStatus.ANALYZING,
                started,
                f"Indexed {report.chunks_indexed} chunks.",
            ),
        )

    def retrieve_core_evidence(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        request = state["request"]
        retriever = HybridDiligenceRetriever(
            state["index"], ingestion_issues=state["corpus"].issues
        )
        response = retriever.retrieve(
            "revenue EBITDA customer concentration change of control debt supplier working capital",
            filters=RetrievalFilters(request.run_id),
            top_k=20,
        )
        warnings = tuple(item.message for item in response.warnings)
        return self._update(
            retrieved_evidence=response.results,
            warnings=tuple(dict.fromkeys((*state.get("warnings", ()), *warnings))),
            trace=self._trace(
                state,
                "retrieve_core_evidence",
                WorkflowStatus.ANALYZING,
                started,
                f"Retrieved {len(response.results)} grounded chunks.",
            ),
        )

    def run_financial_diligence(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        try:
            financial = self.services.financial_runner(state["request"].run_id)
        except (ArithmeticError, ValueError) as error:
            return self._fail(
                state,
                FailureCode.FINANCIAL_ANALYSIS_INCOMPLETE,
                "run_financial_diligence",
                str(error),
                started,
            )
        return self._update(
            financial=financial,
            trace=self._trace(
                state,
                "run_financial_diligence",
                WorkflowStatus.ANALYZING,
                started,
                "Deterministic M3 financial analysis completed.",
            ),
        )

    def run_specialist_analysis(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        retriever = HybridDiligenceRetriever(
            state["index"], ingestion_issues=state["corpus"].issues
        )
        try:
            result = self.services.coordinator_factory(retriever).run(
                engagement=state["request"].engagement,
                documents=state["documents"],
                financial_findings=state["financial"].findings,
            )
        except Exception as error:  # coordinator is an isolation boundary
            return self._fail(
                state,
                FailureCode.SPECIALIST_ANALYSIS_FAILED,
                "run_specialist_analysis",
                str(error),
                started,
            )
        warnings = tuple(f"{item.agent_id.value}: {item.message}" for item in result.errors)
        return self._update(
            specialist_result=result,
            conflicts=result.investigation.conflicts,
            warnings=tuple(dict.fromkeys((*state.get("warnings", ()), *warnings))),
            trace=self._trace(
                state,
                "run_specialist_analysis",
                WorkflowStatus.ANALYZING,
                started,
                f"Completed {len(result.specialist_results)} specialists; isolated {len(result.errors)} errors.",
            ),
        )

    def route_for_review(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        request = build_review_request(state["specialist_result"], state["request"].review_policy)
        if request is None:
            return self._update(
                trace=self._trace(
                    state,
                    "route_for_review",
                    WorkflowStatus.ANALYZING,
                    started,
                    "No analyst interruption required.",
                ),
            )
        return self._update(
            review_request=request,
            status=WorkflowStatus.REVIEW_REQUIRED,
            failure_code=FailureCode.REVIEW_REQUIRED,
            trace=self._trace(
                state,
                "route_for_review",
                WorkflowStatus.REVIEW_REQUIRED,
                started,
                "Material ambiguity routed to analyst review.",
            ),
        )

    def human_review(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        response = cast(
            dict[str, Any], interrupt(self._review_payload(state), response_schema=HumanReviewInput)
        )
        try:
            decisions = tuple(
                ReviewDecision(
                    str(item["subject_type"]),
                    str(item["subject_id"]),
                    ReviewActionType(str(item["action"])),
                    str(item["rationale"]),
                    Severity(str(item["severity"])) if item.get("severity") else None,
                    str(item["preferred_source_id"]) if item.get("preferred_source_id") else None,
                )
                for item in response["decisions"]
            )
            submission = HumanReviewSubmission(
                str(response["reviewer"]), str(response["rationale"]), decisions, datetime.now(UTC)
            )
            findings, conflicts, actions, waiting = apply_review(
                state["specialist_result"].findings,
                state.get("conflicts", ()),
                submission,
                state["request"].run_id,
            )
        except (KeyError, TypeError, ValueError) as error:
            return self._fail(state, FailureCode.INVALID_INPUT, "human_review", str(error), started)
        coordinator = replace(
            state["specialist_result"],
            findings=findings,
            investigation=replace(state["specialist_result"].investigation, conflicts=conflicts),
        )
        status = WorkflowStatus.WAITING_FOR_INFORMATION if waiting else WorkflowStatus.RESUMING
        return self._update(
            specialist_result=coordinator,
            conflicts=conflicts,
            review_submission=submission,
            review_actions=actions,
            status=status,
            failure_code=FailureCode.MISSING_CRITICAL_INFORMATION if waiting else None,
            trace=self._trace(
                state, "human_review", status, started, "Analyst decisions and rationale recorded."
            ),
        )

    def finalize_findings(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        findings = prioritize_findings(state["specialist_result"].findings)
        return self._update(
            final_findings=findings,
            trace=self._trace(
                state,
                "finalize_findings",
                WorkflowStatus.ANALYZING,
                started,
                f"Prioritized {len(findings)} findings with transparent rules.",
            ),
        )

    def generate_report(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        attempt = state.get("retry_counts", {}).get("report", 0) + 1
        request = state["request"]
        try:
            report = self.services.report_generator.generate(
                run_id=request.run_id,
                target_name=request.engagement.target.legal_name,
                findings=state["final_findings"],
                coordinator=state["specialist_result"],
                financial=state["financial"],
                reviews=state.get("review_actions", ()),
            )
        except (TimeoutError, ValueError) as error:
            if attempt <= self.retry_report:
                return self._retry(state, "report", attempt, "generate_report", str(error), started)
            return self._fail(
                state,
                FailureCode.REPORT_GENERATION_FAILED,
                "generate_report",
                str(error),
                started,
                attempt,
            )
        return self._update(
            report=report,
            retry_stage=None,
            trace=self._trace(
                state,
                "generate_report",
                WorkflowStatus.ANALYZING,
                started,
                "Evidence-linked diligence report generated.",
            ),
        )

    def evaluate_run(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        coordinator = state["specialist_result"]
        findings = state["final_findings"]
        evidence_findings = [item for item in findings if item.finding.finding.evidence]
        coverage = (
            Decimal("100")
            if not findings
            else (Decimal(len(evidence_findings)) / Decimal(len(findings)) * 100).quantize(
                Decimal("0.01")
            )
        )
        evaluation = RunEvaluationMetadata(
            len(state["documents"]),
            len(state["corpus"].chunks),
            len(findings),
            sum(
                item.finding.finding.severity in {Severity.HIGH, Severity.CRITICAL}
                for item in findings
            ),
            len(state.get("conflicts", ())),
            len(coordinator.missing_information),
            coverage,
            True,
            len(coordinator.specialist_results),
            len(coordinator.errors),
        )
        return self._update(
            evaluation=evaluation,
            trace=self._trace(
                state,
                "evaluate_run",
                WorkflowStatus.ANALYZING,
                started,
                "Run-level evidence and consistency metrics recorded.",
            ),
        )

    def finalize(self, state: WorkflowState) -> WorkflowState:
        started = perf_counter()
        current = state.get("status")
        status: WorkflowStatus
        if current is WorkflowStatus.WAITING_FOR_INFORMATION or current is WorkflowStatus.FAILED:
            status = current
        elif state.get("warnings"):
            status = WorkflowStatus.COMPLETED_WITH_WARNINGS
        else:
            status = WorkflowStatus.COMPLETED
        coordinator = state.get("specialist_result")
        result = DiligenceWorkflowResult(
            state["request"].run_id,
            status,
            state.get("failure_code"),
            state["request"].engagement,
            state.get("documents", ()),
            () if coordinator is None else coordinator.specialist_results,
            state.get("final_findings", ()),
            state.get("conflicts", ()),
            () if coordinator is None else coordinator.relationships,
            () if coordinator is None else coordinator.missing_information,
            () if coordinator is None else coordinator.requests,
            state.get("review_actions", ()),
            state.get("report"),
            state.get("evaluation"),
            state.get("warnings", ()),
            state.get("errors", ()),
            self._trace(
                state, "finalize", status, started, f"Workflow ended with status {status.value}."
            ),
        )
        return self._update(status=status, final_result=result, trace=result.trace)

    @staticmethod
    def _review_payload(state: WorkflowState) -> dict[str, object]:
        request = state["review_request"]
        return {
            "run_id": state["request"].run_id,
            "reasons": request.reasons,
            "finding_ids": request.finding_ids,
            "conflict_ids": request.conflict_ids,
            "missing_item_ids": request.missing_item_ids,
            "allowed_actions": tuple(item.value for item in ReviewActionType),
        }

    def _retry(
        self,
        state: WorkflowState,
        stage: str,
        attempt: int,
        node: str,
        message: str,
        started: float,
    ) -> WorkflowState:
        counts = dict(state.get("retry_counts", {}))
        counts[stage] = attempt
        issue = WorkflowIssue(
            FailureCode.INGESTION_FAILED
            if stage == "ingestion"
            else FailureCode.REPORT_GENERATION_FAILED,
            node,
            message,
            True,
            attempt,
        )
        return self._update(
            retry_counts=counts,
            retry_stage=stage,
            errors=(*state.get("errors", ()), issue),
            trace=self._trace(
                state,
                node,
                state.get("status", WorkflowStatus.ANALYZING),
                started,
                f"Recoverable failure; retry {attempt}.",
                attempt,
            ),
        )

    def _fail(
        self,
        state: WorkflowState,
        code: FailureCode,
        node: str,
        message: str,
        started: float,
        attempt: int = 1,
    ) -> WorkflowState:
        issue = WorkflowIssue(code, node, message, False, attempt)
        return self._update(
            status=WorkflowStatus.FAILED,
            failure_code=code,
            retry_stage=None,
            errors=(*state.get("errors", ()), issue),
            trace=self._trace(state, node, WorkflowStatus.FAILED, started, message, attempt - 1),
        )

    @staticmethod
    def _trace(
        state: WorkflowState,
        node: str,
        status: WorkflowStatus,
        started: float,
        message: str,
        retry_count: int = 0,
    ) -> tuple[TraceEvent, ...]:
        event = TraceEvent(
            node,
            status,
            message,
            datetime.now(UTC),
            int((perf_counter() - started) * 1000),
            retry_count,
        )
        return (*state.get("trace", ()), event)

    @staticmethod
    def _update(**values: object) -> WorkflowState:
        return cast(WorkflowState, values)
