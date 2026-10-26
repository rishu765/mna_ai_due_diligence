# Pilot Authentication and Deal Isolation

## Scope

Step 5 adds backend-enforced identity, sessions, roles, and deal isolation. It does not rely on the
browser hiding controls. Every protected API request authenticates its bearer session and every
deal request checks authorization again.

## Authentication flow

```mermaid
sequenceDiagram
    participant U as Invited user
    participant A as Pilot API
    participant S as Auth service
    participant D as Security database
    U->>A: Email and password over HTTPS
    A->>S: Login request
    S->>D: Load normalized email
    S->>S: Verify Argon2id hash
    S->>S: Generate opaque random token
    S->>D: Store SHA-256 token hash and expiry
    S-->>A: Raw token returned once
    A-->>U: Bearer session
    U->>A: Protected request with bearer token
    A->>S: Authenticate token
    S->>D: Match token hash; check user, expiry, revocation
    S-->>A: Authenticated principal
```

## Password controls

- Argon2id password hashing
- Per-password random salts
- Minimum 12 and maximum 128 characters
- Generic login failure for unknown users and incorrect passwords
- A dummy Argon2 verification for unknown emails to reduce obvious timing differences
- Automatic rehash support when configured parameters change
- No plaintext or reversible password storage

The controlled pilot still requires HTTPS, secure onboarding, password-reset procedures, and
rate-limiting before external users are admitted.

## Session controls

- Cryptographically random opaque bearer tokens
- Only SHA-256 token hashes are persisted
- Eight-hour default expiry
- Explicit logout and revocation
- Administrator deactivation revokes all existing sessions for that user
- Expired and revoked sessions fail closed
- Deactivated or missing users cannot use an otherwise valid session
- `WWW-Authenticate: Bearer` returned on authentication failures

Tokens must not appear in URLs, application logs, analytics, screenshots, or Git. A future browser
frontend should store the session in a secure, HTTP-only, same-site cookie or another reviewed
mechanism rather than persistent browser storage.

## Roles and permissions

| Capability | Analyst | Reviewer | Pilot administrator |
| --- | ---: | ---: | ---: |
| Read assigned deal | Yes | Yes | All deals |
| Upload/manage documents | Yes | Yes | All deals |
| Start analysis | Yes | Yes | All deals |
| Draft findings | Yes | Yes | All deals |
| Approve/reject review items | No | Yes | All deals |
| Release reviewed report | No | Yes | All deals |
| Create deals and assign access | No | No | Yes |

Analyst and reviewer roles are assigned per deal. Pilot-administrator authority is global within the
single-company controlled pilot.

## Deal-isolation rules

1. Non-administrators see only deals with an explicit membership.
2. Deal resource queries include both deal ID and resource ID.
3. Knowing another deal's identifier does not grant access.
4. Unauthorized deal reads return the same not-found response as a nonexistent deal.
5. Reviewer actions and report release require reviewer-level permission.
6. Membership assignment requires a pilot administrator and valid user/deal records.
7. Database foreign keys prevent membership records for missing users or deals.

## Authenticated pilot API

- `POST /pilot/auth/login`
- `POST /pilot/auth/logout`
- `GET /pilot/me`
- `GET /pilot/deals`
- `POST /pilot/deals` — pilot administrator only
- `GET /pilot/deals/{deal_id}` — assigned member or pilot administrator
- `PUT /pilot/deals/{deal_id}/memberships` — pilot administrator only

The original V1 fixture API remains unchanged. The pilot UI will consume this new authenticated
boundary and later endpoints will apply the same permission model to documents, runs, findings,
review actions, evidence, and reports.

## Step 12 hardening and remaining limitations

- No email invitation or password-reset delivery workflow yet
- No multi-factor authentication or enterprise SSO yet
- Login throttling is process-local; there is no enterprise IP policy or anomaly detection yet
- The browser keeps the bearer session in tab memory; secure-cookie and CSRF design remain a
  deployment decision
- No external penetration test or independent security review yet
- The pilot remains single-company rather than a general multi-tenant SaaS platform

Step 12 adds host allowlisting, response security headers, bounded login throttling, readiness
checking, adversarial AI validation, encrypted backup/recovery, performance smoke coverage, and a
repository coverage gate. See [Pilot Security and Test Gate](PILOT_SECURITY_TESTING.md) for the
complete control matrix and explicit residual-risk decision.

## Verification

Automated negative tests prove that missing, malformed, expired, and revoked sessions fail; unknown
emails and wrong passwords return the same error; raw tokens and plaintext passwords are not stored;
nonmembers cannot discover known deal IDs; analysts cannot administer deals or exercise reviewer
permissions; and only pilot administrators can create deals and assign roles.
