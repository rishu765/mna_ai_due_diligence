"""Deal-scoped workflow application service for the pilot UI."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from ma_due_diligence.financial.methodology import default_financial_methodology
from ma_due_diligence.financial.models import CalculationLine
from ma_due_diligence.persistence import PilotDatabase, PilotRunRecord
from ma_due_diligence.specialists.fixtures import (
    build_specialist_engagement,
    create_specialist_fixture_vdr,
)
from ma_due_diligence.workflow_final import (
    HumanReviewSubmission,
    WorkflowApplication,
    WorkflowRequest,
)
from ma_due_diligence.workflow_final.models import (
    FinancialDiligenceSnapshot,
    WorkflowState,
    WorkflowStatus,
)


class PilotRunService:
    """Run the existing V1 fixture workflow behind a deal-scoped pilot boundary."""

    def __init__(self, database: PilotDatabase, application: WorkflowApplication) -> None:
        self._database = database
        self._application = application
        self._fixture_directories: dict[str, TemporaryDirectory[str]] = {}

    def start_demo_run(self, *, deal_id: str, actor_id: str) -> WorkflowState:
        deal = self._database.get_deal(deal_id)
        if deal is None:
            raise KeyError(f"deal not found: {deal_id}")
        run_id = f"run-{uuid4().hex}"
        directory = TemporaryDirectory(prefix="madd-pilot-demo-")
        self._fixture_directories[run_id] = directory
        manifest = create_specialist_fixture_vdr(Path(directory.name))
        base = build_specialist_engagement()
        target = replace(
            base.target,
            entity_id=f"{run_id}-target",
            legal_name=deal.target_name,
            alternative_names=(),
        )
        engagement = replace(
            base,
            engagement_id=run_id,
            target=target,
            as_of_date=deal.as_of_date,
            reporting_currency=deal.reporting_currency,
        )
        state = self._application.start(
            WorkflowRequest(run_id, engagement, manifest),
            thread_id=run_id,
        )
        timestamp = datetime.now(UTC)
        self._database.save_run(
            PilotRunRecord(
                run_id=run_id,
                deal_id=deal_id,
                status=state["status"].value,
                review_policy="when_needed",
                state=_state_summary(state),
                created_by=actor_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        return state

    def state(self, *, deal_id: str, run_id: str) -> WorkflowState:
        if self._database.get_run(deal_id, run_id) is None:
            raise KeyError(f"run not found: {run_id}")
        return self._application.state(thread_id=run_id)

    def resume(
        self,
        *,
        deal_id: str,
        run_id: str,
        submission: HumanReviewSubmission,
    ) -> WorkflowState:
        record = self._database.get_run(deal_id, run_id)
        if record is None:
            raise KeyError(f"run not found: {run_id}")
        state = self._application.resume(thread_id=run_id, submission=submission)
        self._database.save_run(
            replace(
                record,
                status=state["status"].value,
                state=_state_summary(state),
                updated_at=datetime.now(UTC),
            )
        )
        return state

    def close(self) -> None:
        for directory in self._fixture_directories.values():
            directory.cleanup()
        self._fixture_directories.clear()


def run_payload(run_id: str, state: WorkflowState) -> dict[str, object]:
    coordinator = state.get("specialist_result")
    findings = []
    if coordinator is not None:
        findings = [
            {
                "finding_id": item.finding.finding_id,
                "title": item.finding.title,
                "description": item.finding.description,
                "severity": item.finding.severity.value,
                "workstream": item.finding.workstream.value,
                "support_status": item.finding.support_status.value,
                "deal_impact": item.finding.potential_deal_impact,
                "evidence": [
                    {
                        "evidence_id": evidence.evidence_id,
                        "document_id": evidence.document_id,
                        "pages": list(evidence.page_numbers),
                        "section": evidence.section,
                        "source_text": evidence.source_text,
                    }
                    for evidence in item.finding.evidence
                ],
            }
            for item in coordinator.findings
        ]
    conflicts = [
        {
            "conflict_id": item.conflict_id,
            "topic": item.topic,
            "observation_fact_ids": list(item.observation_fact_ids),
            "status": item.status.value,
        }
        for item in state.get("conflicts", ())
    ]
    financial = state.get("financial")
    financial_payload: dict[str, object] | None = None
    if financial is not None:
        financial_payload = {
            "reported_ebitda": _decimal_string(financial.ebitda_bridge.reported_ebitda.value),
            "accepted_adjustments": _decimal_string(financial.ebitda_bridge.total_adjustment),
            "adjusted_ebitda": _decimal_string(financial.ebitda_bridge.final_adjusted_ebitda),
            "largest_customer_percent": _decimal_string(
                financial.concentration.largest_customer_percent
            ),
            "normalized_nwc": _decimal_string(financial.nwc_peg.normalized_nwc),
            "adjusted_net_debt": _decimal_string(financial.net_debt.adjusted_net_debt),
            "currency": financial.ebitda_bridge.reported_ebitda.currency,
            "unit": financial.ebitda_bridge.unit.value,
            "methodology": default_financial_methodology().payload(),
            "calculation_trace": _financial_calculation_trace(financial),
        }
    request = state.get("review_request")
    return {
        "run_id": run_id,
        "status": state.get("status", WorkflowStatus.CREATED).value,
        "document_count": len(state.get("documents", ())),
        "finding_count": len(findings),
        "findings": findings,
        "conflicts": conflicts,
        "review_required": state.get("status") is WorkflowStatus.REVIEW_REQUIRED,
        "review_reasons": [] if request is None else list(request.reasons),
        "review_finding_ids": [] if request is None else list(request.finding_ids),
        "review_conflict_ids": [] if request is None else list(request.conflict_ids),
        "warnings": list(state.get("warnings", ())),
        "errors": [item.message for item in state.get("errors", ())],
        "financial": financial_payload,
        "report_available": state.get("report") is not None,
    }


def _state_summary(state: WorkflowState) -> dict[str, object]:
    request = state.get("review_request")
    coordinator = state.get("specialist_result")
    return {
        "document_count": len(state.get("documents", ())),
        "finding_count": len(state.get("final_findings", ()))
        or len(coordinator.findings if coordinator is not None else ()),
        "review_reasons": [] if request is None else list(request.reasons),
        "warning_count": len(state.get("warnings", ())),
        "error_count": len(state.get("errors", ())),
        "report_available": state.get("report") is not None,
    }


def _decimal_string(value: object) -> str | None:
    return None if value is None else str(value)


def _financial_calculation_trace(
    financial: FinancialDiligenceSnapshot,
) -> dict[str, object]:
    ebitda_lines = _calculation_lines(financial.ebitda_bridge.lines)
    net_debt_lines = _calculation_lines(financial.net_debt.lines)
    working_capital = [
        {
            "period": item.period.label,
            "formula": "AR + inventory + other operating current assets - AP - other operating current liabilities",
            "lines": _calculation_lines(item.lines),
            "result": _decimal_string(item.net_working_capital),
            "reconciles": None
            if item.net_working_capital is None
            else _line_total(item.lines) == item.net_working_capital,
            "warnings": [warning.message for warning in item.warnings],
        }
        for item in financial.working_capital.results
    ]
    customers = [
        {
            "customer_id": item.customer_id,
            "revenue": str(item.revenue),
            "currency": item.currency,
            "unit": item.unit.value,
            "period": item.period.label,
            "evidence_ids": [value.evidence_id for value in item.evidence],
        }
        for item in financial.customer_revenues
    ]
    reconciliation = financial.revenue_reconciliation
    return {
        "revenue_reconciliation": {
            "metric": reconciliation.metric.value,
            "period": None if reconciliation.period is None else reconciliation.period.label,
            "preferred_observation_id": reconciliation.preferred_observation_id,
            "absolute_variance": _decimal_string(reconciliation.absolute_variance),
            "percent_variance": _decimal_string(reconciliation.percent_variance),
            "status": reconciliation.status.value,
            "rationale": reconciliation.rationale,
            "observations": [
                {
                    "observation_id": item.observation_id,
                    "value": _decimal_string(item.value),
                    "currency": item.currency,
                    "unit": item.unit.value,
                    "period": item.period.label,
                    "basis": item.basis.value,
                    "reporting_status": item.reporting_status.value,
                    "source_document_type": item.source_document_type.value,
                    "evidence_ids": [value.evidence_id for value in item.evidence],
                }
                for item in reconciliation.observations
            ],
        },
        "ebitda_bridge": {
            "formula": "reported EBITDA + accepted increases - accepted decreases",
            "lines": ebitda_lines,
            "result": _decimal_string(financial.ebitda_bridge.final_adjusted_ebitda),
            "reconciles": _line_total(financial.ebitda_bridge.lines)
            == financial.ebitda_bridge.final_adjusted_ebitda,
            "rejected_adjustment_ids": [
                item.adjustment_id for item in financial.ebitda_bridge.rejected_adjustments
            ],
            "warnings": [item.message for item in financial.ebitda_bridge.warnings],
        },
        "customer_concentration": {
            "formula": "customer revenue / total identified customer revenue × 100",
            "customers": customers,
            "total_revenue": _decimal_string(financial.concentration.total_revenue),
            "largest_customer_percent": _decimal_string(
                financial.concentration.largest_customer_percent
            ),
            "top_five_percent": _decimal_string(financial.concentration.top_five_percent),
            "top_ten_percent": _decimal_string(financial.concentration.top_ten_percent),
            "warnings": [item.message for item in financial.concentration.warnings],
        },
        "working_capital": working_capital,
        "nwc_peg": {
            "method": financial.nwc_peg.method.value,
            "period_labels": list(financial.nwc_peg.period_labels),
            "normalized_nwc": _decimal_string(financial.nwc_peg.normalized_nwc),
            "current_nwc": _decimal_string(financial.nwc_peg.current_nwc),
            "surplus_or_shortfall": _decimal_string(financial.nwc_peg.surplus_or_shortfall),
            "warnings": [item.message for item in financial.nwc_peg.warnings],
        },
        "net_debt": {
            "formula": "debt + debt-like items - unrestricted cash - accepted cash-like items",
            "lines": net_debt_lines,
            "result": _decimal_string(financial.net_debt.adjusted_net_debt),
            "reconciles": _line_total(financial.net_debt.lines)
            == financial.net_debt.adjusted_net_debt,
            "warnings": [item.message for item in financial.net_debt.warnings],
        },
    }


def _calculation_lines(lines: tuple[CalculationLine, ...]) -> list[dict[str, object]]:
    return [
        {
            "label": item.label,
            "amount": str(item.amount),
            "operation": item.operation,
            "source_ids": list(item.source_ids),
            "evidence_ids": [value.evidence_id for value in item.evidence],
        }
        for item in lines
    ]


def _line_total(lines: tuple[CalculationLine, ...]) -> Decimal:
    return sum((item.amount for item in lines), start=Decimal("0"))
