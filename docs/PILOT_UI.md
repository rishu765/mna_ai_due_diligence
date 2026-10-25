# Step 6 Pilot UI and Runtime

## Purpose

Step 6 provides a minimum browser workflow for a finance reviewer. It connects the Step 3 screen
contracts to the Step 4 persistent database and encrypted storage boundary, the Step 5 identity and
deal-isolation controls, and the completed V1 diligence workflow. It does not change the V1 analysis
logic or imply production readiness.

## Reviewer journey

1. Sign in with an invited pilot account.
2. View only the deal workspaces the account is authorized to access.
3. Create a deal when signed in as the pilot administrator.
4. Open its overview, document, analysis, finding, financial, review, and report views.
5. Run the verified 25-document synthetic VDR through the complete V1 workflow.
6. Inspect evidence-linked findings, retained conflicts, missing information, and deterministic
   financial outputs.
7. Complete the explicit human-review gate when authorized as a reviewer or administrator.
8. Read the final evidence-linked report after the workflow releases it.

The UI deliberately labels the analysis as a synthetic demonstration. Real document upload and
processing controls remain disabled until Step 7 adds the agreed validation, scanning, OCR, table,
batch-status, and failure-recovery behavior.

## Runtime

The `madd-pilot-api` command starts one local FastAPI application that serves the authenticated API
and static browser UI. It uses the existing pilot database, encrypted-document store, session
service, deal authorization service, and persistent LangGraph checkpoint store.

Required configuration:

- `MADD_CHECKPOINT_KEY`: URL-safe base64 for a 32-byte checkpoint encryption key.
- `MADD_BOOTSTRAP_ADMIN_EMAIL`: optional initial local pilot administrator email.
- `MADD_BOOTSTRAP_ADMIN_PASSWORD`: bootstrap password; must meet the configured password policy.
- `MADD_BOOTSTRAP_ADMIN_NAME`: administrator display name.
- `MADD_PILOT_DATA_DIR`: local directory for the SQLite database, encrypted objects, and workflow
  checkpoints. It defaults to `pilot-data` and is excluded from Git.

Example local start:

```powershell
$env:MADD_CHECKPOINT_KEY = "<base64-encoded-32-byte-key>"
$env:MADD_BOOTSTRAP_ADMIN_EMAIL = "reviewer@example.com"
$env:MADD_BOOTSTRAP_ADMIN_PASSWORD = "<strong-local-passphrase>"
$env:MADD_BOOTSTRAP_ADMIN_NAME = "Pilot Reviewer"
& .\.venv\Scripts\python.exe -m ma_due_diligence.pilot_api_cli
```

Open `http://127.0.0.1:8000/`. The bootstrap account is created only when the configured email does
not already exist. The browser keeps the access token in tab memory rather than persistent browser
storage.

## API boundary

The browser uses authenticated, deal-scoped endpoints to list and create deals, start and restore a
run, submit review decisions, and retrieve the report. The server independently enforces every
permission; hiding a UI action is not treated as authorization.

The Step 6 run adapter intentionally feeds the existing synthetic fixture into V1 while binding the
engagement to the selected deal. The workflow pauses at its real LangGraph review checkpoint and
persists a run summary so the server can restore and resume it after restart.

## Security and data handling

- Passwords are verified by the Step 5 Argon2 service.
- Opaque sessions are revocable and stored server-side as hashes.
- Deal access is checked on every run, review, and report endpoint.
- Analysts can run an analysis but cannot release a reviewed report.
- Reviewers and pilot administrators can submit the controlled review action.
- Unknown or unauthorized deal/run identifiers return non-disclosing not-found responses.
- No real pilot documents are accepted in this step.

## Verification

Automated tests cover static delivery, the authenticated reviewer run-review-report journey, the
analyst prohibition on review, and the existing Step 5 isolation suite. Manual browser verification
covers sign-in, deal creation, analysis, findings, financials, review, report release, error display,
and narrow-screen layout.

## Known limitations

- The UI is a minimum local pilot interface, not a deployed multi-tenant product.
- Step 6 uses the synthetic VDR only; real uploads begin in Step 7.
- Review decisions are generated from the bounded demonstration policy rather than an editable
  decision register; richer review and audit interactions are Step 9.
- Report and Excel downloads are Step 10.
- Deployment, monitoring, backup, and rollback controls are Step 13.
