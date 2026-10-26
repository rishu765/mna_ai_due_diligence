# Step 9 Review Actions and Immutable Decision History

## Purpose

Step 9 turns the pilot's single bulk-approval control into an explicit finance-review workflow. A
reviewer must disposition every finding independently and resolve every conflict identified by the
review policy before a report can be released. The existing V1 review rules and LangGraph checkpoint
remain the decision-application engine; this step adds the pilot controls, durable history, and
reviewer interface around that boundary.

## Reviewer workflow

For every released finding, the reviewer must choose one action and provide a rationale:

- approve the finding;
- reject the finding;
- change its severity;
- mark it non-material; or
- request more evidence.

Every required conflict must identify a controlling source and a resolution rationale. The review
also requires an overall comment describing the work performed. Blank actions, blank rationales,
duplicate subjects, partial finding coverage, missing required conflicts, and action/subject
mismatches are rejected by the API before the workflow is resumed.

A request for more evidence records the complete submission but leaves the run in
`waiting_for_information`; no report is released. Otherwise, the reviewed findings flow through the
existing prioritization, report-generation, consistency-validation, and evaluation nodes.

## Durable event model

Review history is stored in `pilot_review_events`, scoped by both `deal_id` and `run_id`. Each row
retains:

- an immutable event identifier and insertion sequence;
- finding, conflict, or run subject identifiers;
- event type;
- reviewer user ID and display name;
- rationale or comment;
- prior and resulting state;
- workflow action metadata; and
- timezone-aware occurrence time.

The event vocabulary covers assignment, comment, approval, rejection, edit/non-material treatment,
severity change, information request, and conflict resolution. Each subject is assigned to the
authenticated reviewer as part of the submitted decision, and the assignment and resulting action
are separate events.

The database exposes insertion and ordered retrieval only. SQLite triggers reject direct update or
delete attempts. The run summary, review-event batch, and top-level audit event are committed in one
database transaction, preventing a released run from being saved without its decision history.

## Complete finding coverage

The workflow may flag only a subset of findings as materially ambiguous, but a released report can
contain additional findings. The pilot therefore requires one explicit decision for every finding
that would be released, while separately requiring resolutions for conflicts selected by the review
policy. Server-side validation compares the submission against the workflow state; hiding or
altering browser controls cannot bypass this requirement.

Reviewed status and severity are returned from the resulting workflow state rather than the original
candidate set. The Findings screen therefore reflects reviewer changes after submission.

## API

Submit the complete decision set:

`POST /pilot/deals/{deal_id}/runs/{run_id}/review`

Read the ordered immutable history:

`GET /pilot/deals/{deal_id}/runs/{run_id}/review-history`

Submission requires `review_decide`. History requires `deal_read`. Unknown or unauthorized run and
deal combinations use the existing non-disclosing not-found behavior.

## User interface

The Review Queue provides:

- the policy reasons that require attention;
- an independent action and rationale control for every finding;
- conditional severity selection;
- controlling-source selection for required conflicts;
- an overall review comment;
- validation before submission; and
- an ordered decision-history timeline showing actor, event, timestamp, and state transition.

The interface does not default findings to approval. Reviewers must actively choose each
disposition. After submission, it routes to the report only when the workflow actually releases one;
information requests remain visibly blocked.

## Control boundary and limitations

- This is a controlled pilot review register, not a substitute for formal investment-committee,
  accounting, legal, or transaction approval procedures.
- The current V1 graph accepts one terminal review submission per synthetic run. A later real-data
  integration must define how responses to information requests reopen and version a run.
- Assignment records the authenticated decision-maker at submission. Team workload routing and
  pre-submission reassignment are outside the present pilot scope.
- History is append-only inside the application database. Deployment backup, retention, external
  attestation, and operational access monitoring remain later pilot steps.

## Verification

Automated tests cover database migration, ordered deal-scoped retrieval, duplicate rejection,
database-level update/delete prevention, complete-finding enforcement, partial-submission rejection,
reviewer authorization, report release, information-request blocking, and all persisted event types.
The complete V1 test and 14-scenario evaluation suites remain regression gates.
