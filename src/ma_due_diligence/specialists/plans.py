"""Narrow workstream-specific retrieval plans for specialist analyzers."""

from ma_due_diligence.domain import DiligenceWorkstream, DocumentType
from ma_due_diligence.specialists.models import AgentId, RetrievalPlan

FINANCIAL_PLAN = RetrievalPlan(
    AgentId.FINANCIAL,
    (DiligenceWorkstream.FINANCIAL,),
    (
        DocumentType.FINANCIAL_STATEMENTS,
        DocumentType.MANAGEMENT_ACCOUNTS,
        DocumentType.GENERAL_LEDGER_EXPORT,
        DocumentType.SALES_REPORT,
        DocumentType.DEBT_SCHEDULE,
        DocumentType.BANK_STATEMENT,
        DocumentType.BUDGET,
        DocumentType.FORECAST,
        DocumentType.MANAGEMENT_PRESENTATION,
    ),
    ("revenue EBITDA adjustments", "working capital", "debt cash restricted cash"),
)

COMMERCIAL_PLAN = RetrievalPlan(
    AgentId.COMMERCIAL,
    (DiligenceWorkstream.COMMERCIAL,),
    (
        DocumentType.SALES_REPORT,
        DocumentType.CUSTOMER_COHORT_REPORT,
        DocumentType.CUSTOMER_CONTRACT,
        DocumentType.MANAGEMENT_PRESENTATION,
        DocumentType.BOARD_MATERIAL,
        DocumentType.BUDGET,
        DocumentType.FORECAST,
    ),
    (
        "largest customer Apex represents revenue concentration",
        "customer churn retention renewal expiry",
        "pricing growth forecast actual",
    ),
    top_k_per_query=10,
)

LEGAL_PLAN = RetrievalPlan(
    AgentId.LEGAL_CONTRACTUAL,
    (DiligenceWorkstream.LEGAL_CONTRACTUAL,),
    (
        DocumentType.CUSTOMER_CONTRACT,
        DocumentType.SUPPLIER_CONTRACT,
        DocumentType.LEGAL_AGREEMENT,
        DocumentType.BOARD_MATERIAL,
    ),
    (
        "change of control consent",
        "termination assignment exclusivity",
        "indemnity liability cap expiry",
    ),
    top_k_per_query=10,
)

OPERATIONAL_PLAN = RetrievalPlan(
    AgentId.OPERATIONAL,
    (DiligenceWorkstream.OPERATIONAL,),
    (
        DocumentType.SUPPLIER_CONTRACT,
        DocumentType.HR_REPORT,
        DocumentType.BOARD_MATERIAL,
        DocumentType.POLICY,
        DocumentType.OTHER,
    ),
    (
        "supplier dependency concentration sole source",
        "key personnel capacity bottleneck",
        "business continuity outsourcing systems",
    ),
    top_k_per_query=10,
)

ALL_PLANS = (FINANCIAL_PLAN, COMMERCIAL_PLAN, LEGAL_PLAN, OPERATIONAL_PLAN)
