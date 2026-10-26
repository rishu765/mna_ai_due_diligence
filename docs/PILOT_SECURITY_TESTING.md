# Pilot Security and Test Gate

## Purpose

Step 12 turns the prior feature-level checks into one explicit pilot gate. It adds security controls
that can be verified locally, recovery tooling, adversarial AI-output tests, a coverage threshold,
and a documented residual-risk decision. Passing this gate is necessary for deployment work in
Step 13, but it is not a claim of production certification or an external penetration test.

## Control map

| Area | Implemented control | Verification evidence |
| --- | --- | --- |
| Authentication | Argon2id passwords, opaque hashed sessions, generic failures, bounded login throttling | Negative session and repeated-failure tests |
| Authorization | Backend deal membership and permission checks; hidden-resource responses | Cross-deal and role-matrix tests |
| HTTP boundary | Host allowlist, CSP, anti-framing, MIME-sniffing, referrer, browser-permission and cache controls | Header, host-rejection, and browser walkthrough tests |
| Uploads | Extension/type/signature/size validation, archive rejection, screening, encrypted storage, per-file failure isolation | Upload attack and batch-recovery tests |
| Persistence | Foreign keys, immutable review events, encrypted documents/checkpoints, SQLite integrity check | Restart, tamper, atomicity, and readiness tests |
| AI boundary | Bounded evidence, untrusted-evidence instruction, citation and number validation, prompt-control rejection, cost/token budgets | Adversarial provider-output tests |
| Backup/recovery | AES-256-GCM archive, independent key, consistent SQLite snapshots, per-file digests, safe-path restore into an absent directory | Backup authentication and full restore test |
| Performance | Bounded authenticated-read smoke test | 100 authenticated list reads must complete within 10 seconds in CI |
| End to end | Login through analysis, human review, immutable history, report and workbook export | Pilot workflow integration suite |
| Regression | Ruff, strict mypy, test suite, coverage, 14-scenario evaluation, browser workflow | CI and milestone verification |

## HTTP and login hardening

The pilot accepts only configured `Host` values. `MADD_ALLOWED_HOSTS` defaults to local addresses;
deployment must replace it with the exact pilot hostname while retaining required health-check
hosts. Responses apply a same-origin content-security policy, deny framing and MIME sniffing, avoid
referrer disclosure, disable camera/microphone/geolocation, and prevent caching of `/pilot/`
responses.

Login throttling is keyed by a SHA-256 digest of normalized email plus client address, so the
process does not retain the raw combination. The default allows five failed attempts in five
minutes and blocks that key for fifteen minutes. A successful login clears its state. This is a
single-process pilot control; Step 13 must use one application instance or replace it with a shared,
durable limiter before horizontal scaling.

`GET /health` remains a non-sensitive liveness response. `GET /ready` performs SQLite
`quick_check` and returns `503` without internal detail if the database is not ready.

## Prompt-injection boundary

Evidence is serialized as data, not inserted into the system instruction. The approved provider
instruction explicitly says evidence is untrusted and must not be followed. A candidate is then
rejected unless it:

1. cites at least one supplied evidence ID and no unknown ID;
2. introduces no numerical token absent from the bounded input;
3. stays inside input, output, request-cost, and run-cost limits; and
4. contains no prompt-control or secret-seeking language such as attempts to override prior
   instructions, reveal a system prompt, or expose an API key.

These are defense-in-depth checks rather than proof that arbitrary models are safe. External mode
remains disabled unless provider approval, data classification, retention, training use, endpoint,
model, and cost policy are explicitly configured.

## Encrypted backup and recovery

Backups require `MADD_BACKUP_KEY`, a separate URL-safe base64-encoded 32-byte key held outside Git.
The command creates transactionally consistent SQLite snapshots, copies encrypted document blobs,
builds a SHA-256 manifest, and encrypts the whole archive with AES-256-GCM. No filenames, database
content, or manifest metadata are readable without the backup key.

```text
madd-pilot-backup create <pilot-data-directory> <new-backup-file>
madd-pilot-backup verify <backup-file>
madd-pilot-backup restore <backup-file> <new-absent-directory>
```

Restore authenticates and verifies the complete archive before writing, permits only the two pilot
databases and `.madd` document objects, rejects traversal or unexpected files, and refuses to
overwrite an existing directory. Operators must test restore using a non-production destination;
Step 13 will define schedule, retention, off-host custody, recovery objectives, and service rollback.

## Automated gate

CI performs dependency consistency, Ruff lint and format checks, strict mypy, and the complete test
suite with branch-aware coverage. The repository-wide minimum is 80%; the Step 12 baseline is 86%.
The deterministic evaluation remains a separate required milestone command:

```text
python -m ma_due_diligence.evaluation_final
```

Browser QA covers login, deal selection, the synthetic run, document inventory, evidence and
financial screens, controlled AI drafting, review, and exports in the supported Chromium-based
pilot browser. The current manual Step 12 check reconfirms the desktop workflow; formal narrow-
viewport and multi-browser automation remains a deployment acceptance item because the current UI
has no cross-browser test service.

## Residual risks accepted for the controlled pilot

- Bearer tokens remain in browser-tab memory rather than secure cookies; the same-origin UI and
  CSP reduce exposure, but secure-cookie/CSRF design is deferred to the deployment architecture.
- Login throttling is process-local and has no anomaly detection, enterprise IP policy, MFA, SSO,
  invitation delivery, or password-reset delivery.
- Backup scheduling, off-host custody, key rotation, recovery objectives, monitoring, and rollback
  are Step 13 operational controls.
- Malware screening remains deterministic signature/structure screening, not an enterprise
  antivirus or sandbox service.
- No external penetration test, independent security review, accessibility certification, or
  formal multi-browser laboratory has been completed.
- The system remains a single-company controlled pilot using synthetic analysis data; confidential
  company data still requires written authorization and an agreed policy.

These risks are acceptable only for the current local/internal synthetic-data gate. They are not
silently inherited by an external company pilot.
