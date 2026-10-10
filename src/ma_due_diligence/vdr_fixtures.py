"""Reproducible fictitious VDR used by tests, evaluation, and the offline demo."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
from openpyxl import Workbook


def create_fixture_vdr(root: Path) -> Path:
    """Create a compact Northstar Components VDR and return its manifest path."""

    root.mkdir(parents=True, exist_ok=True)
    _pdf(
        root / "01_audited_financial_statements_FY2025.pdf",
        (
            "NORTHSTAR COMPONENTS LTD\nAUDITED FINANCIAL STATEMENTS FY2025",
            "STATEMENT OF PROFIT OR LOSS\nRevenue | FY2025 GBP 92.0 million\n"
            "EBITDA | FY2025 GBP 14.0 million\nGross margin | 36.0%",
            "NOTES\nThe audited statements contain no management EBITDA add-back schedule.",
        ),
    )
    _workbook(
        root / "02_monthly_management_accounts_FY2025.xlsx",
        {
            "Monthly P&L": [
                ("Month", "Revenue GBP m", "EBITDA GBP m"),
                ("Jan", 7.5, 1.0),
                ("Feb", 7.7, 1.1),
                ("Mar", 7.8, 1.1),
                ("Apr", 7.9, 1.2),
                ("May", 7.8, 1.2),
                ("Jun", 7.9, 1.2),
                ("Jul", 8.0, 1.2),
                ("Aug", 8.1, 1.2),
                ("Sep", 8.0, 1.2),
                ("Oct", 8.1, 1.2),
                ("Nov", 8.1, 1.2),
                ("Dec", 8.1, 1.2),
                ("FY2025 total", 95.0, 14.0),
            ],
            "Working Capital": [
                ("Metric", "Dec-25 GBP m"),
                ("Trade receivables", 12.0),
                ("Inventory", 7.0),
                ("Trade payables", -9.0),
            ],
        },
    )
    _write(
        root / "03_customer_sales_report_FY2025.csv",
        "Customer,Revenue GBP m,Share of FY2025 revenue\n"
        "Apex Retail Group,39.9,42%\n"
        "Beacon Stores,18.1,19%\n"
        "Cedar Wholesale,14.2,15%\n"
        "Other customers,22.8,24%\n"
        "Total,95.0,100%\n",
    )
    _write(
        root / "04_apex_customer_contract.txt",
        "APEX RETAIL GROUP CUSTOMER AGREEMENT\n\n"
        "1. Term. The agreement expires on 31 December 2027.\n\n"
        "8. Change of Control. Customer may terminate this Agreement on written notice if "
        "control of Supplier changes.\n\n"
        "9. Termination for Convenience. Customer may terminate on 90 days written notice.",
    )
    supplier = (
        "# ORION SUPPLIER AGREEMENT\n\n"
        "## 3. Supply commitment\n\n"
        "Orion Metals supplies the sole-source alloy used in Northstar's premium "
        "component line.\n\n"
        "## 11. Termination\n\n"
        "Either party may terminate for material breach after a 30 day cure period."
    )
    _write(root / "05_orion_supplier_contract.md", supplier)
    _write(root / "05_orion_supplier_contract_copy.md", supplier)
    _write(
        root / "06_debt_schedule_FY2025.csv",
        "Instrument,Lender,Outstanding GBP m,Maturity,Covenant\n"
        "Term Loan A,North Bank,20.0,2028-06-30,Net leverage below 3.5x\n"
        "Revolver,Union Bank,5.0,2027-12-31,Interest cover above 3.0x\n",
    )
    _workbook(
        root / "07_budget_forecast_FY2026.xlsx",
        {
            "Forecast": [
                ("Metric", "FY2025A", "FY2026B"),
                ("Revenue GBP m", 95.0, 108.0),
                ("EBITDA GBP m", 14.0, 18.0),
            ]
        },
    )
    deck_v1 = (
        "# NORTHSTAR MANAGEMENT PRESENTATION\n\n"
        "## FY2025 highlights\n\nRevenue was GBP 100.0 million and reported EBITDA was "
        "GBP 14.0 million.\n\n"
        "## Adjusted EBITDA\n\nManagement proposes a GBP 2.0 million legal expense "
        "add-back, producing adjusted EBITDA of GBP 16.0 million.\n\n"
        "## Customers\n\nManagement states that no customer concentration issue exists."
    )
    _write(root / "08_management_presentation_v1.md", deck_v1)
    _write(
        root / "08_management_presentation_v2_revised.md",
        deck_v1 + "\n\n## Revision note\n\nUpdated after the February management meeting.",
    )
    _write(
        root / "09_board_memo.html",
        "<html><body><h1>February Board Memo</h1>"
        "<p>Management reported no customer contributes more than 20% of revenue.</p>"
        "<h2>Legal matters</h2><p>A contract dispute with Delta Logistics remains in litigation; "
        "management has not quantified the contingent liability.</p></body></html>",
    )
    (root / "10_unreadable_archive.bin").write_bytes(b"\x00\xffnot-a-supported-document")
    manifest = {
        "engagement_id": "eng-northstar-vdr",
        "documents": [
            {"path": path.name} for path in sorted(root.iterdir()) if path.name != "manifest.json"
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _pdf(path: Path, pages: tuple[str, ...]) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    try:
        for text in pages:
            page = document.new_page()
            page.insert_textbox(
                pymupdf.Rect(60, 60, 535, 780),  # type: ignore[no-untyped-call]
                text,
                fontsize=11,
            )
        document.save(path)  # type: ignore[no-untyped-call]
    finally:
        document.close()  # type: ignore[no-untyped-call]


def _workbook(path: Path, sheets: dict[str, list[tuple[object, ...]]]) -> None:
    workbook = Workbook()
    default = workbook.active
    assert default is not None
    workbook.remove(default)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    workbook.close()
