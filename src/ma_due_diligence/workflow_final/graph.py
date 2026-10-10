"""Checkpointed LangGraph composition and pause/resume application facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from ma_due_diligence.workflow_final.checkpointing import TrustedLocalSerializer
from ma_due_diligence.workflow_final.models import (
    HumanReviewInput,
    HumanReviewSubmission,
    RetryPolicy,
    ReviewDecisionInput,
    WorkflowRequest,
    WorkflowState,
    WorkflowStatus,
)
from ma_due_diligence.workflow_final.nodes import WorkflowNodes
from ma_due_diligence.workflow_final.services import WorkflowServices

CompiledWorkflow = CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]


def build_workflow(
    services: WorkflowServices | None = None,
    *,
    retry_policy: RetryPolicy | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledWorkflow:
    policy = retry_policy or RetryPolicy()
    nodes = WorkflowNodes(services or WorkflowServices(), policy.ingestion, policy.report)
    builder = StateGraph(WorkflowState)
    builder.add_node("validate_engagement", nodes.validate_engagement)
    builder.add_node("ingest_vdr", nodes.ingest_vdr)
    builder.add_node("build_index", nodes.build_index)
    builder.add_node("retrieve_core_evidence", nodes.retrieve_core_evidence)
    builder.add_node("run_financial_diligence", nodes.run_financial_diligence)
    builder.add_node("run_specialist_analysis", nodes.run_specialist_analysis)
    builder.add_node("route_for_review", nodes.route_for_review)
    builder.add_node("human_review", nodes.human_review)
    builder.add_node("finalize_findings", nodes.finalize_findings)
    builder.add_node("generate_report", nodes.generate_report)
    builder.add_node("evaluate_run", nodes.evaluate_run)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "validate_engagement")
    builder.add_conditional_edges(
        "validate_engagement", _failed, {"continue": "ingest_vdr", "finalize": "finalize"}
    )
    builder.add_conditional_edges(
        "ingest_vdr",
        _ingestion_route,
        {"retry": "ingest_vdr", "continue": "build_index", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "build_index", _failed, {"continue": "retrieve_core_evidence", "finalize": "finalize"}
    )
    builder.add_edge("retrieve_core_evidence", "run_financial_diligence")
    builder.add_conditional_edges(
        "run_financial_diligence",
        _failed,
        {"continue": "run_specialist_analysis", "finalize": "finalize"},
    )
    builder.add_conditional_edges(
        "run_specialist_analysis", _failed, {"continue": "route_for_review", "finalize": "finalize"}
    )
    builder.add_conditional_edges(
        "route_for_review",
        _review_route,
        {"review": "human_review", "continue": "finalize_findings"},
    )
    builder.add_conditional_edges(
        "human_review",
        _post_review_route,
        {"continue": "finalize_findings", "finalize": "finalize"},
    )
    builder.add_edge("finalize_findings", "generate_report")
    builder.add_conditional_edges(
        "generate_report",
        _report_route,
        {"retry": "generate_report", "continue": "evaluate_run", "finalize": "finalize"},
    )
    builder.add_edge("evaluate_run", "finalize")
    builder.add_edge("finalize", END)
    saver = checkpointer or InMemorySaver(serde=TrustedLocalSerializer())
    return builder.compile(checkpointer=saver, name="ai_due_diligence_final_workflow")


@dataclass(frozen=True, slots=True)
class WorkflowApplication:
    graph: CompiledWorkflow

    def start(self, request: WorkflowRequest, *, thread_id: str) -> WorkflowState:
        initial: WorkflowState = {
            "request": request,
            "status": WorkflowStatus.CREATED,
            "failure_code": None,
            "warnings": (),
            "errors": (),
            "retry_counts": {},
            "retry_stage": None,
            "review_actions": (),
            "trace": (),
        }
        return cast(WorkflowState, self.graph.invoke(initial, config=_config(thread_id)))

    def resume(self, *, thread_id: str, submission: HumanReviewSubmission) -> WorkflowState:
        decisions: list[ReviewDecisionInput] = []
        for item in submission.decisions:
            decision: ReviewDecisionInput = {
                "subject_type": item.subject_type,
                "subject_id": item.subject_id,
                "action": item.action.value,
                "rationale": item.rationale,
            }
            if item.severity:
                decision["severity"] = item.severity.value
            if item.preferred_source_id:
                decision["preferred_source_id"] = item.preferred_source_id
            decisions.append(decision)
        response: HumanReviewInput = {
            "reviewer": submission.reviewer,
            "rationale": submission.rationale,
            "decisions": decisions,
        }
        return cast(
            WorkflowState, self.graph.invoke(Command(resume=response), config=_config(thread_id))
        )

    def state(self, *, thread_id: str) -> WorkflowState:
        return cast(WorkflowState, self.graph.get_state(_config(thread_id)).values)


def _config(thread_id: str) -> RunnableConfig:
    if not thread_id.strip():
        raise ValueError("thread_id must not be blank")
    return cast(RunnableConfig, {"configurable": {"thread_id": thread_id.strip()}})


def _failed(state: WorkflowState) -> Literal["continue", "finalize"]:
    return "finalize" if state.get("status") is WorkflowStatus.FAILED else "continue"


def _ingestion_route(state: WorkflowState) -> Literal["retry", "continue", "finalize"]:
    if state.get("retry_stage") == "ingestion":
        return "retry"
    return _failed(state)


def _report_route(state: WorkflowState) -> Literal["retry", "continue", "finalize"]:
    if state.get("retry_stage") == "report":
        return "retry"
    return _failed(state)


def _review_route(state: WorkflowState) -> Literal["review", "continue"]:
    return "review" if state.get("status") is WorkflowStatus.REVIEW_REQUIRED else "continue"


def _post_review_route(state: WorkflowState) -> Literal["continue", "finalize"]:
    return (
        "finalize"
        if state.get("status") in {WorkflowStatus.FAILED, WorkflowStatus.WAITING_FOR_INFORMATION}
        else "continue"
    )
