"""Deterministic risk prioritization and evidence-grounded report generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ma_due_diligence.domain import (
    DealImpactArea,
    DiligenceWorkstream,
    HumanReviewAction,
    Severity,
    SupportStatus,
)
from ma_due_diligence.specialists.models import AttributedFinding, CoordinatorResult
from ma_due_diligence.workflow_final.models import (
    DiligenceReport,
    FinancialDiligenceSnapshot,
    FinancialReportSummary,
    PrioritizedFinding,
    PriorityBand,
    ReportFinding,
    ReportSection,
    ReportStatus,
    citation_from_evidence,
)

_SEVERITY = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
    Severity.UNASSESSED: 4,
}


class ReportNarrativeProvider(Protocol):
    def draft(self, title: str, grounded_text: tuple[str, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class DiligenceReportGenerator:
    provider: ReportNarrativeProvider | None = None

    def generate(
        self,
        *,
        run_id: str,
        target_name: str,
        findings: tuple[PrioritizedFinding, ...],
        coordinator: CoordinatorResult,
        financial: FinancialDiligenceSnapshot,
        reviews: tuple[HumanReviewAction, ...],
    ) -> DiligenceReport:
        executive = tuple(
            item.finding.finding.finding_id
            for item in findings
            if item.priority in {PriorityBand.IMMEDIATE, PriorityBand.HIGH}
        )[:8]
        sections = self._sections(findings, coordinator, reviews)
        summary = FinancialReportSummary(
            financial.ebitda_bridge.reported_ebitda.value,
            financial.ebitda_bridge.total_adjustment,
            financial.ebitda_bridge.final_adjusted_ebitda,
            financial.concentration.largest_customer_percent,
            financial.nwc_peg.normalized_nwc,
            financial.net_debt.adjusted_net_debt,
            financial.ebitda_bridge.currency,
            financial.ebitda_bridge.unit.value,
        )
        report = DiligenceReport(
            f"report-{run_id}",
            run_id,
            target_name,
            datetime.now(UTC),
            ReportStatus.FINAL,
            executive,
            sections,
            summary,
            (
                "Analysis is based on the supplied synthetic VDR and may be incomplete.",
                "Contract observations are issue spotting and are not legal advice.",
                "No external market research, tax diligence, cyber diligence, or forensic accounting was performed.",
                "Unresolved source conflicts and missing information remain subject to analyst review.",
            ),
            tuple(item.action_id for item in reviews),
        )
        validate_report(report, findings, financial)
        return report

    def _sections(
        self,
        findings: tuple[PrioritizedFinding, ...],
        coordinator: CoordinatorResult,
        reviews: tuple[HumanReviewAction, ...],
    ) -> tuple[ReportSection, ...]:
        definitions = (
            ("executive_summary", "Executive Summary", None),
            ("key_red_flags", "Key Red Flags", None),
            ("financial", "Financial Due Diligence", DiligenceWorkstream.FINANCIAL),
            ("qoe", "Quality of Earnings", DiligenceWorkstream.FINANCIAL),
            ("working_capital", "Working Capital", DiligenceWorkstream.FINANCIAL),
            ("net_debt", "Net Debt / Debt-Like Items", DiligenceWorkstream.FINANCIAL),
            ("commercial", "Commercial Diligence", DiligenceWorkstream.COMMERCIAL),
            ("legal", "Legal / Contractual Diligence", DiligenceWorkstream.LEGAL_CONTRACTUAL),
            ("operational", "Operational Diligence", DiligenceWorkstream.OPERATIONAL),
            ("conflicts", "Cross-Document Inconsistencies", None),
            ("missing", "Missing Information", None),
            ("requests", "Information Requests / Follow-Ups", None),
            ("review", "Analyst Review Decisions", None),
            ("limitations", "Limitations", None),
        )
        output: list[ReportSection] = []
        for section_id, title, workstream in definitions:
            selected = _section_findings(section_id, workstream, findings)
            grounded = tuple(item.finding.finding.description for item in selected)
            narrative = _default_narrative(section_id, grounded, coordinator, reviews)
            if self.provider is not None:
                drafted = self.provider.draft(title, grounded)
                if not drafted.strip():
                    raise ValueError("report provider returned blank narrative")
                narrative = drafted.strip()
            output.append(
                ReportSection(
                    section_id,
                    title,
                    narrative,
                    tuple(_report_finding(item) for item in selected),
                    tuple(item.request_id for item in coordinator.requests)
                    if section_id == "requests"
                    else (),
                )
            )
        return tuple(output)


def prioritize_findings(
    findings: tuple[AttributedFinding, ...],
) -> tuple[PrioritizedFinding, ...]:
    ranked = sorted(findings, key=_priority_key)
    return tuple(
        PrioritizedFinding(item, _priority_band(item), _priority_rationale(item), ordinal)
        for ordinal, item in enumerate(ranked, start=1)
    )


def validate_report(
    report: DiligenceReport,
    findings: tuple[PrioritizedFinding, ...],
    financial: FinancialDiligenceSnapshot,
) -> None:
    expected_ids = {
        item.finding.finding.finding_id
        for item in findings
        if item.priority in {PriorityBand.IMMEDIATE, PriorityBand.HIGH}
    }
    represented = {item.finding_id for section in report.sections for item in section.findings}
    if not expected_ids <= represented:
        raise ValueError("report omitted a material finding")
    available_evidence = {
        evidence.evidence_id for item in findings for evidence in item.finding.finding.evidence
    }
    cited = {
        citation.evidence_id
        for section in report.sections
        for item in section.findings
        for citation in item.citations
    }
    if not cited <= available_evidence:
        raise ValueError("report contains unsupported citations")
    summary = report.financial_summary
    expected = (
        financial.ebitda_bridge.final_adjusted_ebitda,
        financial.nwc_peg.normalized_nwc,
        financial.net_debt.adjusted_net_debt,
        financial.concentration.largest_customer_percent,
    )
    actual = (
        summary.diligence_adjusted_ebitda,
        summary.normalized_nwc,
        summary.adjusted_net_debt,
        summary.customer_concentration_percent,
    )
    if actual != expected:
        raise ValueError("report numerical summary differs from deterministic outputs")
    if not report.limitations:
        raise ValueError("report must disclose limitations")


def render_markdown(report: DiligenceReport) -> str:
    lines = [f"# Due-Diligence Report — {report.target_name}", ""]
    for section in report.sections:
        lines.extend((f"## {section.title}", "", section.narrative, ""))
        for item in section.findings:
            lines.append(f"### {item.title} [{item.severity.value.upper()}]")
            lines.append(item.narrative)
            for citation in item.citations:
                source = citation.document_id or "external source"
                lines.append(
                    f"- Source: {source}; {citation.locator}; evidence `{citation.evidence_id}`"
                )
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _priority_key(item: AttributedFinding) -> tuple[int, int, int, str]:
    finding = item.finding
    impact = (
        0
        if set(finding.impact_areas)
        & {
            DealImpactArea.CLOSING_CONDITION,
            DealImpactArea.QUALITY_OF_EARNINGS,
            DealImpactArea.NET_DEBT,
            DealImpactArea.DEAL_THESIS,
        }
        else 1
    )
    uncertainty = (
        0
        if finding.support_status
        in {
            SupportStatus.CONFLICTING,
            SupportStatus.UNVERIFIED,
        }
        else 1
    )
    return _SEVERITY[finding.severity], impact, uncertainty, finding.finding_id


def _priority_band(item: AttributedFinding) -> PriorityBand:
    finding = item.finding
    if finding.severity is Severity.CRITICAL or (
        finding.severity is Severity.HIGH
        and (
            finding.support_status is SupportStatus.CONFLICTING
            or DealImpactArea.CLOSING_CONDITION in finding.impact_areas
            or finding.category == "compound_customer_retention"
        )
    ):
        return PriorityBand.IMMEDIATE
    if finding.severity is Severity.HIGH:
        return PriorityBand.HIGH
    return PriorityBand.STANDARD


def _priority_rationale(item: AttributedFinding) -> str:
    finding = item.finding
    return (
        f"Severity={finding.severity.value}; materiality={finding.materiality.qualitative.value}; "
        f"support={finding.support_status.value}; impacts="
        + ",".join(value.value for value in finding.impact_areas)
    )


def _section_findings(
    section_id: str,
    workstream: DiligenceWorkstream | None,
    findings: tuple[PrioritizedFinding, ...],
) -> tuple[PrioritizedFinding, ...]:
    if section_id == "executive_summary":
        return tuple(item for item in findings if item.priority is not PriorityBand.STANDARD)[:8]
    if section_id == "key_red_flags":
        return tuple(
            item
            for item in findings
            if item.finding.finding.severity in {Severity.HIGH, Severity.CRITICAL}
        )
    if section_id == "conflicts":
        return tuple(
            item
            for item in findings
            if item.finding.finding.support_status is SupportStatus.CONFLICTING
        )
    if workstream is None:
        return ()
    selected = tuple(item for item in findings if item.finding.finding.workstream is workstream)
    if section_id == "qoe":
        return tuple(item for item in selected if "quality" in item.finding.finding.category)
    if section_id == "working_capital":
        return tuple(
            item for item in selected if "working" in item.finding.finding.title.casefold()
        )
    if section_id == "net_debt":
        return tuple(
            item
            for item in selected
            if "cash" in item.finding.finding.title.casefold()
            or "debt" in item.finding.finding.title.casefold()
        )
    return selected


def _report_finding(item: PrioritizedFinding) -> ReportFinding:
    finding = item.finding.finding
    return ReportFinding(
        finding.finding_id,
        finding.title,
        finding.severity,
        finding.support_status.value,
        finding.description,
        item.finding.uncertainty,
        tuple(citation_from_evidence(value) for value in finding.evidence),
    )


def _default_narrative(
    section_id: str,
    grounded: tuple[str, ...],
    coordinator: CoordinatorResult,
    reviews: tuple[HumanReviewAction, ...],
) -> str:
    if grounded:
        return " ".join(grounded)
    if section_id == "missing":
        return " ".join(item.reason_needed for item in coordinator.missing_information)
    if section_id == "requests":
        return " ".join(item.question for item in coordinator.requests)
    if section_id == "review":
        return (
            " ".join(f"{item.action.value}: {item.rationale}" for item in reviews)
            or "No analyst decisions were recorded."
        )
    if section_id == "limitations":
        return "See the explicit report limitations and unresolved issues."
    return "No material items were identified in the available evidence for this section."
