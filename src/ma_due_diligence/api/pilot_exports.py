"""Deterministic, in-memory exports for a released pilot diligence run."""

from __future__ import annotations

import re
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from typing import Any

import pymupdf
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ma_due_diligence.persistence import PilotDealRecord, PilotReviewEvent
from ma_due_diligence.specialists.models import AttributedFinding
from ma_due_diligence.workflow_final.models import (
    DiligenceReport,
    FinancialDiligenceSnapshot,
    ReportStatus,
    WorkflowState,
    WorkflowStatus,
)

_PDF_MEDIA_TYPE = "application/pdf"
_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_NAVY = "17324D"
_PALE_BLUE = "EAF2F8"
_PALE_GOLD = "FFF4D6"
_LIGHT_GREY = "E4E7EC"
_WHITE = "FFFFFF"
_INVALID_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True, slots=True)
class GeneratedExport:
    filename: str
    media_type: str
    content: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.content).hexdigest()


def build_reviewed_report_pdf(
    deal: PilotDealRecord,
    state: WorkflowState,
    review_events: tuple[PilotReviewEvent, ...],
) -> GeneratedExport:
    """Render the released report without changing its values or conclusions."""

    report, financial, findings = _released_components(state)
    decisions = _finding_decisions(review_events)
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    writer = _PdfWriter(document)
    writer.cover(deal, report, financial, findings, review_events)
    writer.heading("Financial summary", level=1)
    summary = report.financial_summary
    writer.key_value(
        "Reported EBITDA", _money(summary.reported_ebitda, summary.currency, summary.unit)
    )
    writer.key_value(
        "Accepted adjustments", _money(summary.accepted_adjustments, summary.currency, summary.unit)
    )
    writer.key_value(
        "Diligence-adjusted EBITDA",
        _money(summary.diligence_adjusted_ebitda, summary.currency, summary.unit),
    )
    writer.key_value("Largest customer", _percent(summary.customer_concentration_percent))
    writer.key_value(
        "Normalized NWC", _money(summary.normalized_nwc, summary.currency, summary.unit)
    )
    writer.key_value(
        "Adjusted net debt", _money(summary.adjusted_net_debt, summary.currency, summary.unit)
    )

    findings_by_id = {item.finding.finding_id: item for item in findings}
    for section in report.sections:
        writer.heading(section.title, level=1)
        writer.paragraph(section.narrative)
        for ordinal, item in enumerate(section.findings, start=1):
            reviewed = findings_by_id.get(item.finding_id)
            status_text = "not recorded"
            if reviewed is not None:
                status_text = reviewed.finding.analyst_review_status.value
            decision = decisions.get(item.finding_id)
            writer.heading(f"{ordinal}. {item.title}", level=2)
            writer.paragraph(
                f"Severity: {item.severity.value} | Support: {item.support_status} | "
                f"Review status: {status_text}"
            )
            writer.paragraph(item.narrative)
            if item.uncertainty:
                writer.paragraph(f"Uncertainty: {item.uncertainty}")
            if decision is not None:
                writer.paragraph(
                    f"Reviewer decision: {decision.event_type.value}; "
                    f"{decision.rationale} ({decision.actor_display_name}, "
                    f"{decision.occurred_at.isoformat()})"
                )
            for citation in item.citations:
                source = citation.document_id or "external source"
                writer.bullet(f"Citation {citation.evidence_id}: {source}; {citation.locator}.")
                if citation.source_excerpt:
                    writer.paragraph(f'Excerpt: "{citation.source_excerpt}"', indent=12)
        if section.request_ids:
            writer.paragraph("Information requests: " + ", ".join(section.request_ids))

    writer.heading("Explicit limitations", level=1)
    for limitation in report.limitations:
        writer.bullet(limitation)
    writer.heading("Review certification", level=1)
    writer.paragraph(
        f"This final report is linked to {len(report.review_action_ids)} workflow review actions "
        f"and {len(review_events)} immutable review-history events."
    )
    for event in review_events:
        if event.subject_type == "run" and event.event_type.value == "commented":
            writer.paragraph(
                f"Overall review by {event.actor_display_name} at "
                f"{event.occurred_at.isoformat()}: {event.rationale}"
            )
    writer.finish()
    content = document.tobytes(garbage=4, deflate=True)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]
    return GeneratedExport(
        filename=f"{_filename_stem(deal.target_name)}-reviewed-diligence-report.pdf",
        media_type=_PDF_MEDIA_TYPE,
        content=content,
    )


def build_reviewed_workbook(
    deal: PilotDealRecord,
    state: WorkflowState,
    review_events: tuple[PilotReviewEvent, ...],
) -> GeneratedExport:
    """Build the reviewed findings register and deterministic financial schedules."""

    report, financial, findings = _released_components(state)
    decisions = _finding_decisions(review_events)
    workbook = Workbook()
    cover = workbook.active
    assert cover is not None
    cover.title = "Read Me"
    _cover_sheet(cover, deal, report, findings, review_events)
    _findings_sheet(workbook.create_sheet("Findings Register"), findings, decisions)
    _citations_sheet(workbook.create_sheet("Citations"), findings)
    _financial_summary_sheet(workbook.create_sheet("Financial Summary"), report)
    _ebitda_sheet(workbook.create_sheet("EBITDA Bridge"), financial)
    _working_capital_sheet(workbook.create_sheet("Working Capital"), financial)
    _nwc_peg_sheet(workbook.create_sheet("NWC Peg"), financial)
    _concentration_sheet(workbook.create_sheet("Customer Concentration"), financial)
    _net_debt_sheet(workbook.create_sheet("Net Debt"), financial)
    _reconciliation_sheet(workbook.create_sheet("Revenue Reconciliation"), financial)
    _review_history_sheet(workbook.create_sheet("Review History"), review_events)
    _limitations_sheet(workbook.create_sheet("Limitations"), report)
    stream = BytesIO()
    workbook.save(stream)
    return GeneratedExport(
        filename=f"{_filename_stem(deal.target_name)}-reviewed-diligence-schedules.xlsx",
        media_type=_XLSX_MEDIA_TYPE,
        content=stream.getvalue(),
    )


def _released_components(
    state: WorkflowState,
) -> tuple[DiligenceReport, FinancialDiligenceSnapshot, tuple[AttributedFinding, ...]]:
    status = state.get("status")
    report = state.get("report")
    financial = state.get("financial")
    final_findings = state.get("final_findings", ())
    if status not in {WorkflowStatus.COMPLETED, WorkflowStatus.COMPLETED_WITH_WARNINGS}:
        raise ValueError("reviewed exports require a completed run")
    if report is None or report.status is not ReportStatus.FINAL:
        raise ValueError("reviewed exports require a final report")
    if financial is None:
        raise ValueError("reviewed exports require financial results")
    findings = tuple(item.finding for item in final_findings)
    if not findings:
        raise ValueError("reviewed exports require final findings")
    return report, financial, findings


def _finding_decisions(
    events: tuple[PilotReviewEvent, ...],
) -> dict[str, PilotReviewEvent]:
    return {
        event.subject_id: event
        for event in events
        if event.subject_type == "finding"
        and event.event_type.value not in {"assigned", "commented"}
    }


class _PdfWriter:
    def __init__(self, document: Any) -> None:
        self.document = document
        self.page: Any = None
        self.y = 0.0
        self.page_number = 0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.document.new_page(width=595, height=842)
        self.page_number += 1
        self.page.draw_rect(
            pymupdf.Rect(0, 0, 595, 42),  # type: ignore[no-untyped-call]
            color=(0.09, 0.20, 0.30),
            fill=(0.09, 0.20, 0.30),
        )
        self.page.insert_text(
            (42, 27),
            "DealLens | Confidential - controlled pilot",
            fontsize=9,
            fontname="helv",
            color=(1, 1, 1),
        )
        self.y = 66

    def _ensure(self, height: float) -> None:
        if self.y + height > 790:
            self._new_page()

    def cover(
        self,
        deal: PilotDealRecord,
        report: DiligenceReport,
        financial: FinancialDiligenceSnapshot,
        findings: tuple[AttributedFinding, ...],
        review_events: tuple[PilotReviewEvent, ...],
    ) -> None:
        self.y = 120
        self.heading("Reviewed M&A Due-Diligence Report", level=0)
        self.heading(report.target_name, level=1)
        self.paragraph(f"Buyer: {deal.buyer_name or 'Not specified'}")
        self.paragraph(f"Transaction: {deal.transaction_type}")
        self.paragraph(f"As-of date: {deal.as_of_date.isoformat()}")
        self.paragraph(f"Run ID: {report.run_id}")
        self.paragraph(f"Generated: {report.generated_at.isoformat()}")
        self.paragraph("Status: FINAL - HUMAN REVIEW COMPLETED")
        self.y += 16
        self.paragraph(
            f"Control totals: {len(findings)} final findings; "
            f"{_citation_count(report)} report citations; "
            f"{len(review_events)} immutable review events."
        )
        self.paragraph(
            f"Financial basis: {financial.ebitda_bridge.currency}; "
            f"unit={financial.ebitda_bridge.unit.value}. Unknown values remain blank and are never "
            "exported as zero."
        )
        self.paragraph(
            "This report supports professional diligence review. It is not an investment, legal, "
            "tax, accounting, or transaction approval opinion."
        )
        self._new_page()

    def heading(self, text: str, *, level: int) -> None:
        size = {0: 25, 1: 17, 2: 12}[level]
        lines = _pdf_lines(text, 48 if level == 0 else (62 if level == 1 else 82))
        height = len(lines) * (size + 4) + (12 if level < 2 else 6)
        self._ensure(height)
        color = (0.09, 0.20, 0.30) if level < 2 else (0.18, 0.40, 0.55)
        for line in lines:
            self.page.insert_text((42, self.y), line, fontsize=size, fontname="helv", color=color)
            self.y += size + 4
        self.y += 8 if level < 2 else 3

    def paragraph(self, text: str, *, indent: float = 0) -> None:
        lines = _pdf_lines(text, 96 if indent == 0 else 91)
        self._ensure(len(lines) * 13 + 8)
        for line in lines:
            self.page.insert_text(
                (42 + indent, self.y), line, fontsize=9.3, fontname="helv", color=(0.15, 0.18, 0.22)
            )
            self.y += 13
        self.y += 5

    def bullet(self, text: str) -> None:
        self.paragraph(f"- {text}", indent=8)

    def key_value(self, label: str, value: str) -> None:
        self._ensure(21)
        self.page.draw_rect(
            pymupdf.Rect(42, self.y - 12, 553, self.y + 8),  # type: ignore[no-untyped-call]
            color=(0.90, 0.92, 0.94),
            fill=(0.97, 0.98, 0.99),
        )
        self.page.insert_text(
            (50, self.y + 2), label, fontsize=9, fontname="helv", color=(0.2, 0.25, 0.3)
        )
        self.page.insert_text(
            (390, self.y + 2), value, fontsize=9, fontname="helv", color=(0.09, 0.20, 0.30)
        )
        self.y += 25

    def finish(self) -> None:
        total = len(self.document)
        for number, page in enumerate(self.document, start=1):
            page.draw_line((42, 805), (553, 805), color=(0.85, 0.87, 0.89))
            page.insert_text(
                (42, 823),
                "Evidence-grounded output | Review status and limitations included",
                fontsize=7.5,
                fontname="helv",
                color=(0.4, 0.45, 0.5),
            )
            page.insert_text(
                (505, 823),
                f"{number} / {total}",
                fontsize=7.5,
                fontname="helv",
                color=(0.4, 0.45, 0.5),
            )


def _pdf_lines(text: str, width: int) -> list[str]:
    normalized = (
        text.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2192", "->")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2019", "'")
    )
    return textwrap.wrap(normalized, width=width, break_long_words=True) or [""]


def _cover_sheet(
    sheet: Worksheet,
    deal: PilotDealRecord,
    report: DiligenceReport,
    findings: tuple[AttributedFinding, ...],
    review_events: tuple[PilotReviewEvent, ...],
) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.merge_cells("A1:F2")
    sheet["A1"] = "Reviewed M&A Due-Diligence Workbook"
    sheet["A1"].font = Font(size=20, bold=True, color=_WHITE)
    sheet["A1"].fill = PatternFill("solid", fgColor=_NAVY)
    sheet["A1"].alignment = Alignment(vertical="center")
    rows: tuple[tuple[str, Any], ...] = (
        ("Target", report.target_name),
        ("Buyer", deal.buyer_name or "Not specified"),
        ("Transaction", deal.transaction_type),
        ("As-of date", deal.as_of_date.isoformat()),
        ("Run ID", report.run_id),
        ("Report status", "FINAL - HUMAN REVIEW COMPLETED"),
        ("Generated", report.generated_at.isoformat()),
        ("Final findings", len(findings)),
        ("Report citations", _citation_count(report)),
        ("Review-history events", len(review_events)),
    )
    for row_number, (label, value) in enumerate(rows, start=4):
        sheet.cell(row_number, 1, label).font = Font(bold=True, color=_NAVY)
        sheet.cell(row_number, 2, value)
    sheet["A16"] = "Workbook controls"
    sheet["A16"].font = Font(size=14, bold=True, color=_NAVY)
    controls = (
        "Values are generated from the same final workflow state as the application report.",
        "Unknown financial inputs remain blank; they are never converted to zero.",
        "Each finding has a final analyst review status and an immutable decision-history link.",
        "Citations retain evidence, document, locator, and source-excerpt fields.",
        "This workbook is not an investment, legal, tax, accounting, or approval opinion.",
    )
    for offset, value in enumerate(controls, start=17):
        sheet.cell(offset, 1, f"{offset - 16}.")
        sheet.cell(offset, 2, value)
    sheet.column_dimensions["A"].width = 24
    sheet.column_dimensions["B"].width = 84
    sheet.freeze_panes = "A4"


def _findings_sheet(
    sheet: Worksheet,
    findings: tuple[AttributedFinding, ...],
    decisions: dict[str, PilotReviewEvent],
) -> None:
    headers = (
        "Finding ID",
        "Title",
        "Workstream",
        "Category",
        "Severity",
        "Finding status",
        "Review status",
        "Support status",
        "Materiality",
        "Deal-impact areas",
        "Potential deal impact",
        "Description",
        "Recommended follow-up",
        "Evidence count",
        "Evidence IDs",
        "Decision",
        "Decision rationale",
        "Reviewer",
        "Decision timestamp (UTC)",
    )
    rows = []
    for item in findings:
        finding = item.finding
        decision = decisions.get(finding.finding_id)
        rows.append(
            (
                finding.finding_id,
                finding.title,
                finding.workstream.value,
                finding.category,
                finding.severity.value,
                finding.status.value,
                finding.analyst_review_status.value,
                finding.support_status.value,
                finding.materiality.qualitative.value,
                ", ".join(value.value for value in finding.impact_areas),
                finding.potential_deal_impact or "",
                finding.description,
                finding.recommended_follow_up or "",
                len(finding.evidence),
                ", ".join(value.evidence_id for value in finding.evidence),
                "" if decision is None else decision.event_type.value,
                "" if decision is None else decision.rationale,
                "" if decision is None else decision.actor_display_name,
                "" if decision is None else decision.occurred_at.isoformat(),
            )
        )
    _table(
        sheet,
        headers,
        rows,
        freeze="A2",
        widths={1: 22, 2: 36, 11: 42, 12: 58, 13: 42, 15: 38, 17: 45},
    )


def _citations_sheet(sheet: Worksheet, findings: tuple[AttributedFinding, ...]) -> None:
    headers = (
        "Finding ID",
        "Evidence ID",
        "Document ID",
        "Pages",
        "Section",
        "Table",
        "Row",
        "Sheet",
        "Cell range",
        "Chunk ID",
        "Source excerpt",
    )
    rows = []
    for item in findings:
        for evidence in item.finding.evidence:
            rows.append(
                (
                    item.finding.finding_id,
                    evidence.evidence_id,
                    evidence.document_id or evidence.external_source_reference or "",
                    ", ".join(str(value) for value in evidence.page_numbers),
                    evidence.section or "",
                    evidence.table or "",
                    evidence.row or "",
                    evidence.sheet_name or "",
                    evidence.cell_range or "",
                    evidence.chunk_id or "",
                    evidence.source_text or "",
                )
            )
    _table(sheet, headers, rows, freeze="A2", widths={3: 30, 11: 72})


def _financial_summary_sheet(sheet: Worksheet, report: DiligenceReport) -> None:
    summary = report.financial_summary
    headers = ("Metric", "Value", "Currency", "Unit")
    rows = (
        ("Reported EBITDA", _excel_number(summary.reported_ebitda), summary.currency, summary.unit),
        (
            "Accepted adjustments",
            _excel_number(summary.accepted_adjustments),
            summary.currency,
            summary.unit,
        ),
        (
            "Diligence-adjusted EBITDA",
            _excel_number(summary.diligence_adjusted_ebitda),
            summary.currency,
            summary.unit,
        ),
        (
            "Largest customer percent",
            _excel_number(summary.customer_concentration_percent),
            "",
            "percent",
        ),
        ("Normalized NWC", _excel_number(summary.normalized_nwc), summary.currency, summary.unit),
        (
            "Adjusted net debt",
            _excel_number(summary.adjusted_net_debt),
            summary.currency,
            summary.unit,
        ),
    )
    _table(sheet, headers, rows, freeze="A2", widths={1: 34, 2: 22})
    _number_column(sheet, 2)


def _ebitda_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    bridge = financial.ebitda_bridge
    headers = ("Line", "Operation", "Amount", "Source IDs", "Evidence IDs")
    rows = [
        (
            item.label,
            item.operation,
            _excel_number(item.amount),
            ", ".join(item.source_ids),
            ", ".join(value.evidence_id for value in item.evidence),
        )
        for item in bridge.lines
    ]
    rows.append(
        ("Diligence-adjusted EBITDA", "result", _excel_number(bridge.final_adjusted_ebitda), "", "")
    )
    _table(sheet, headers, rows, freeze="A2", widths={1: 38, 4: 35, 5: 35})
    _number_column(sheet, 3)
    _notes(
        sheet, len(rows) + 4, "Formula", "reported EBITDA + accepted increases - accepted decreases"
    )
    _notes(sheet, len(rows) + 5, "Currency / unit", f"{bridge.currency} / {bridge.unit.value}")
    _notes(
        sheet,
        len(rows) + 6,
        "Warnings",
        " | ".join(item.message for item in bridge.warnings) or "None",
    )


def _working_capital_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    headers = ("Period", "Line", "Operation", "Amount", "Source IDs", "Evidence IDs", "Result")
    rows: list[tuple[Any, ...]] = []
    for result in financial.working_capital.results:
        for line in result.lines:
            rows.append(
                (
                    result.period.label,
                    line.label,
                    line.operation,
                    _excel_number(line.amount),
                    ", ".join(line.source_ids),
                    ", ".join(value.evidence_id for value in line.evidence),
                    "",
                )
            )
        rows.append(
            (
                result.period.label,
                "Net working capital",
                "result",
                "",
                "",
                "",
                _excel_number(result.net_working_capital),
            )
        )
    _table(sheet, headers, rows, freeze="A2", widths={2: 34, 5: 32, 6: 32})
    _number_column(sheet, 4)
    _number_column(sheet, 7)


def _nwc_peg_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    peg = financial.nwc_peg
    headers = ("Metric", "Value", "Currency", "Unit")
    rows = (
        ("Method", peg.method.value, "", ""),
        ("Included periods", ", ".join(peg.period_labels), "", ""),
        ("Normalized NWC", _excel_number(peg.normalized_nwc), peg.currency, peg.unit.value),
        ("Current NWC", _excel_number(peg.current_nwc), peg.currency, peg.unit.value),
        (
            "Surplus / (shortfall)",
            _excel_number(peg.surplus_or_shortfall),
            peg.currency,
            peg.unit.value,
        ),
        ("Warnings", " | ".join(item.message for item in peg.warnings) or "None", "", ""),
    )
    _table(sheet, headers, rows, freeze="A2", widths={1: 32, 2: 62})


def _concentration_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    headers = ("Customer ID", "Revenue", "Currency", "Unit", "Period", "Evidence IDs")
    rows = [
        (
            item.customer_id,
            _excel_number(item.revenue),
            item.currency,
            item.unit.value,
            item.period.label,
            ", ".join(value.evidence_id for value in item.evidence),
        )
        for item in financial.customer_revenues
    ]
    _table(sheet, headers, rows, freeze="A2", widths={1: 24, 6: 38})
    _number_column(sheet, 2)
    result = financial.concentration
    start = len(rows) + 4
    _notes(sheet, start, "Total identified revenue", _excel_number(result.total_revenue))
    _notes(
        sheet, start + 1, "Largest customer percent", _excel_number(result.largest_customer_percent)
    )
    _notes(sheet, start + 2, "Top five percent", _excel_number(result.top_five_percent))
    _notes(sheet, start + 3, "Top ten percent", _excel_number(result.top_ten_percent))
    _notes(
        sheet, start + 4, "Warnings", " | ".join(item.message for item in result.warnings) or "None"
    )


def _net_debt_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    bridge = financial.net_debt
    headers = ("Line", "Operation", "Amount", "Source IDs", "Evidence IDs")
    rows = [
        (
            item.label,
            item.operation,
            _excel_number(item.amount),
            ", ".join(item.source_ids),
            ", ".join(value.evidence_id for value in item.evidence),
        )
        for item in bridge.lines
    ]
    rows.append(("Adjusted net debt", "result", _excel_number(bridge.adjusted_net_debt), "", ""))
    _table(sheet, headers, rows, freeze="A2", widths={1: 38, 4: 35, 5: 35})
    _number_column(sheet, 3)
    _notes(
        sheet,
        len(rows) + 4,
        "Formula",
        "debt + debt-like items - unrestricted cash - accepted cash-like items",
    )
    _notes(sheet, len(rows) + 5, "Currency / unit", f"{bridge.currency} / {bridge.unit.value}")
    _notes(
        sheet,
        len(rows) + 6,
        "Warnings",
        " | ".join(item.message for item in bridge.warnings) or "None",
    )


def _reconciliation_sheet(sheet: Worksheet, financial: FinancialDiligenceSnapshot) -> None:
    result = financial.revenue_reconciliation
    headers = (
        "Observation ID",
        "Value",
        "Currency",
        "Unit",
        "Period",
        "Basis",
        "Reporting status",
        "Source type",
        "Evidence IDs",
        "Preferred",
    )
    rows = [
        (
            item.observation_id,
            _excel_number(item.value),
            item.currency or "",
            item.unit.value,
            item.period.label,
            item.basis.value,
            item.reporting_status.value,
            item.source_document_type.value,
            ", ".join(value.evidence_id for value in item.evidence),
            "yes" if item.observation_id == result.preferred_observation_id else "no",
        )
        for item in result.observations
    ]
    _table(sheet, headers, rows, freeze="A2", widths={1: 26, 9: 38})
    _number_column(sheet, 2)
    start = len(rows) + 4
    _notes(sheet, start, "Reconciliation status", result.status.value)
    _notes(sheet, start + 1, "Absolute variance", _excel_number(result.absolute_variance))
    _notes(sheet, start + 2, "Percentage variance", _excel_number(result.percent_variance))
    _notes(sheet, start + 3, "Rationale", result.rationale)


def _review_history_sheet(sheet: Worksheet, events: tuple[PilotReviewEvent, ...]) -> None:
    headers = (
        "Timestamp (UTC)",
        "Actor",
        "Actor ID",
        "Subject type",
        "Subject ID",
        "Event type",
        "Rationale",
        "Prior state",
        "Resulting state",
    )
    rows = [
        (
            event.occurred_at.isoformat(),
            event.actor_display_name,
            event.actor_id,
            event.subject_type,
            event.subject_id,
            event.event_type.value,
            event.rationale,
            _state_text(event.prior_state),
            _state_text(event.resulting_state),
        )
        for event in events
    ]
    _table(sheet, headers, rows, freeze="A2", widths={1: 26, 5: 28, 7: 55, 8: 38, 9: 38})


def _limitations_sheet(sheet: Worksheet, report: DiligenceReport) -> None:
    _table(
        sheet,
        ("Number", "Explicit limitation"),
        [(index, value) for index, value in enumerate(report.limitations, start=1)],
        freeze="A2",
        widths={1: 12, 2: 100},
    )


def _table(
    sheet: Worksheet,
    headers: tuple[str, ...],
    rows: Iterable[tuple[Any, ...]],
    *,
    freeze: str,
    widths: dict[int, int] | None = None,
) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color=_WHITE)
        cell.fill = PatternFill("solid", fgColor=_NAVY)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    row_count = 1
    for row_count, row in enumerate(rows, start=2):
        sheet.append(row)
        fill = PatternFill("solid", fgColor=_PALE_BLUE if row_count % 2 == 0 else _WHITE)
        for cell in sheet[row_count]:
            cell.fill = fill
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=Side(style="hair", color=_LIGHT_GREY))
    sheet.freeze_panes = freeze
    sheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(row_count, 1)}"
    for index, header in enumerate(headers, start=1):
        default = min(max(len(header) + 4, 16), 30)
        sheet.column_dimensions[get_column_letter(index)].width = (widths or {}).get(index, default)
    sheet.row_dimensions[1].height = 32


def _number_column(sheet: Worksheet, column: int) -> None:
    for cell in list(sheet.columns)[column - 1][1:]:
        if isinstance(cell.value, (int, float)):
            cell.number_format = "0.00########"


def _notes(sheet: Worksheet, row: int, label: str, value: Any) -> None:
    label_cell = sheet.cell(row, 1, label)
    label_cell.font = Font(bold=True, color=_NAVY)
    label_cell.fill = PatternFill("solid", fgColor=_PALE_GOLD)
    value_cell = sheet.cell(row, 2, value)
    value_cell.alignment = Alignment(wrap_text=True, vertical="top")


def _excel_number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _state_text(value: dict[str, object]) -> str:
    return "; ".join(f"{key}={item}" for key, item in sorted(value.items()))


def _money(value: Decimal | None, currency: str, unit: str) -> str:
    if value is None:
        return "Unknown"
    suffix = {"thousand": "k", "million": "m", "billion": "bn"}.get(unit, "")
    return f"{currency} {value}{suffix}"


def _percent(value: Decimal | None) -> str:
    return "Unknown" if value is None else f"{value}%"


def _citation_count(report: DiligenceReport) -> int:
    return sum(len(item.citations) for section in report.sections for item in section.findings)


def _filename_stem(value: str) -> str:
    normalized = _INVALID_FILENAME.sub("-", value.strip()).strip("-._")
    return normalized or "deal"
