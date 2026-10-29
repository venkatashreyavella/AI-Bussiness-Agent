# Verification record — 28 October 2026

Verified on this Windows workspace with Python 3.12.14.

## Gmail integration preparation — 29 October 2026

- Added official Google OAuth/Gmail clients, encrypted credentials and PKCE state, identity-bound OAuth callbacks, owner-private recent-inbox import, MIME-to-plain-text handling, and explicit approved Gmail reply delivery.
- Final full suite passed **88 tests against isolated PostgreSQL schemas**. Earlier targeted Gmail/dashboard checks passed 32 tests on Windows. Google/OpenAI calls are mocked; no real Gmail content was accessed and no real email was sent.
- Tests cover PKCE, encrypted credentials, expired/consumed/wrong-account OAuth state, login-required callback completion and URL clearing, private mailbox reads/results/analytics/actions, excluded fictional business records, duplicate import, HTML script removal, provider failures, explicit approved revision/recipient checks, duplicate/ambiguous delivery protection, concurrent edit blocking, disconnect revocation and original-mailbox binding after reconnect.
- Applied the additive migration on SQLite and PostgreSQL; Alembic reports no schema drift. Existing owner-account and email/review smoke tests passed after deployment. Existing accounts and shared demo messages were preserved.
- Generated a private token-encryption key and activation checklist. Google OAuth client ID/secret and OpenAI API key/model are still missing. Live Google consent, live AI and actual delivery remain unverified and disabled until the user supplies those credentials and authorizes access.
- Added Gmail setup/configuration guidance in `GMAIL_SETUP.md`. Sync is user-triggered (20 recent Inbox messages), not unattended continuous monitoring. The temporary preview tunnel required renewal after its previous hostname expired; a stable domain is recommended before ongoing OAuth use.
- Verified the renewed public HTTPS dashboard in the browser: existing owner sign-in succeeded, Gmail navigation opened, and missing Google/OpenAI configuration was clearly displayed. Saved the setup view privately in `artifacts/gmail-ready.png`; no Google consent or live email action was attempted.

## Public self-registration update

- The user explicitly selected Reviewer access for anyone who registers. Added public registration options and account creation, with a Create account tab on the sign-in screen and automatic sign-in after successful registration.
- All **64 tests passed against isolated PostgreSQL schemas**. Targeted registration/dashboard checks also passed 15 tests on Windows before the additional disabled-signup UI case was added.
- Verified new Reviewer sessions, actual email processing/approval permissions, rejection of Admin/active/id/password-hash registration fields, case-insensitive duplicate rejection, preservation of existing credentials, registration throttling, disabled registration, owner-bootstrap requirement, password confirmation, and successful automatic sign-in through the dashboard.
- Deployment reports public registration enabled with role Reviewer. The live owner-session smoke test passed after deployment, and Alembic reports no schema drift. Existing accounts were preserved; no extra live accounts were created by verification.
- Public-browser verification confirmed the Sign in / Create account tabs, username/display-name/password/confirmation fields, and disclosure of shared Reviewer access. Left Create account selected for the user; no real registration credential was entered by the browser verification.
- Public registration can be disabled through `PUBLIC_SIGNUP_ENABLED=false`. It is explicitly open access to the shared fictional inbox, rather than private per-person mailboxes.

## Individual accounts and role permissions

- Full final regression suite passed **54 tests against PostgreSQL**, using a separate generated test schema for each database-backed case. The earlier SQLite/Windows run passed 52 tests before the two additional dashboard account-creation/password-error cases were added.
- Verified hashed passwords, individual login/logout, one-hour session expiry, role-based API denial, role/disable/password-reset session revocation, self-service password change, no shared-password bypass, no account-management access via the integration token, last-admin protection, sign-in throttling, authenticated review attribution, and account/review audit records.
- Dashboard tests cover all six Admin pages, account creation through Users, Viewer read-only controls, wrong-password and outage behavior, and validation messages that do not echo passwords.
- Applied the account/session/audit migration to the existing PostgreSQL database, preserved the inbox, and bootstrapped the `owner` administrator with the existing initial dashboard password. `alembic check` reports no schema drift.
- Live `scripts.smoke_accounts` passed: owner sign-in, database session, account management, rejection of old raw-password bearer access, restriction of the service token, and logout revocation.
- The existing PostgreSQL email/review smoke test passed again after deployment.
- Browser verification through the existing public HTTPS URL succeeded with username `owner` and the preserved initial password. Confirmed authenticated Admin identity, all six navigation pages, Users account creation controls, existing owner account, role/enabled controls, password reset and audit sections. Left the owner signed in on Users; did not create extra live accounts.
- Account and permission instructions are in `ACCOUNTS.md`. The private login file now includes the owner username. No colleague accounts or email invitations were created automatically.

## Internet-access and accessibility update

- Updated regression suite: **40 passed** on Windows and **40 passed** inside the rebuilt Linux dashboard container. Added checks for the password gate, wrong passwords, missing configuration, one-hour session expiry, password rotation, account-wide login throttling, sign-out and inbox-card navigation.
- PostgreSQL-backed smoke test passed again after deployment. API, healthy dashboard and healthy PostgreSQL are running locally.
- Browser verification at a narrow viewport confirmed a readable, labeled sign-in form and that signed-out visitors see no inbox or review controls. The browser check also caught and verified a fix for Streamlit's standalone import path.
- Replaced the canvas data grid as the default inbox view with readable cards; retained the grid as optional. Navigation stays above page content; fields and evidence have text views; charts have text counts; columns stack below 800 pixels; touch targets and keyboard focus indicators were improved.
- Service API credentials no longer appear in browser widgets. The dashboard requires a separate randomly generated password saved privately in ignored `artifacts/dashboard-access.txt`. Both `.env` and that file were confirmed ignored by Git.
- Added an optional Cloudflare tunnel profile and documented its temporary HTTPS preview lifecycle in `INTERNET_ACCESS.md`. After the user explicitly approved Cloudflare, started the tunnel successfully. Browser verification of the generated public HTTPS URL confirmed a working page and live Streamlit connection showing only the password sign-in screen. No inbox data or review controls appeared before login. The temporary public URL was saved with the private local login instructions; it depends on the computer, Docker and tunnel remaining online.
- This update does not certify WCAG conformance or verify every physical device/browser/screen-reader combination.

## Original application verification

- Windows regression run: **34 passed**. After adding two non-finite-number validation cases, `docker compose exec -T api python -m pytest -q --tb=short -p no:cacheprovider` passed **all 36 tests** in the Linux Python 3.12 container. One installed Starlette warning deprecates its current httpx TestClient adapter; it does not affect the passing checks.
- `python -m alembic upgrade head`: succeeded on the local SQLite database.
- `python -m alembic check`: no new upgrade operations detected.
- `python -m scripts.seed_database`: succeeded; all records are fictional.
- `python -m evaluation.run_evaluation`: all **60** offline cases processed and validated. Category labels matched **59/60**; invoice/order lookup checks matched **25/25**. Full report is in `evaluation/reports/report.md`. These are deterministic demo results, not measured OpenAI model performance.
- `python -m compileall -q app frontend scripts evaluation`: succeeded.
- `docker compose config --quiet`: succeeded.
- Started the installed Docker Desktop engine, built all three application images, and ran `docker compose up --build -d` successfully. PostgreSQL is healthy; API and dashboard are running on localhost ports 8000 and 8501.
- `docker compose exec -T api python -m alembic check`: succeeded against PostgreSQL, with no schema drift.
- `docker compose exec -T api python -m scripts.smoke_test`: passed against the running PostgreSQL-backed API. Verified authenticated submission, duplicate reuse, extraction, actual invoice lookup, grounded draft, approval, approval reset, disabled sending, persisted results and analytics. The fictional smoke-test draft is left pending.
- Running API and Streamlit services were checked through the browser: created a fictional email, processed it, inspected extraction, and displayed the grounded Pending/AED 3500.00 reply for human review. The sample draft is left pending.

Live OpenAI requests have not been made: a real API key and account-supported model must be configured. Responses API parsing and tool protocol are covered with a mocked SDK.

Docker build and PostgreSQL runtime were verified after starting Docker Desktop. The earlier SQLite local database remains available for the non-Docker workflow; Docker uses its separate persistent PostgreSQL volume.

Binary documents, mailbox integration, sending, semantic factual-claim adjudication and production identity/RBAC are outside this implementation. See README for supported text-document input, bounded factual screening, deployment controls and limitations.
