# Business Inbox AI Agent

A working inbox application that turns business messages into validated extraction, summaries, database evidence, and reply drafts for human review. FastAPI serves an authenticated API; Streamlit provides the review workspace. PostgreSQL is the Docker database. SQLite is supported for a quick local demonstration.

**Individual accounts are enabled.** Sign in as `owner` with your existing dashboard password for the initial administrator account. Add each colleague under **Users**, choosing Admin, Reviewer or Viewer. See [Accounts and permissions](ACCOUNTS.md). Accounts share this business workspace; Viewers cannot modify it.

**All included customers, emails, invoices and orders are fictional.** Demo mode uses deterministic rules and templates, clearly labeled in the dashboard. OpenAI mode uses the official SDK, Responses API structured parsing and actual function calls. Neither mode sends email.

## What is implemented

- Six categories, structured extraction, missing identifiers, uncertainty, summaries and relevant prior-thread context.
- Manual input, `.eml` import, UTF-8 `.txt` documents and a 60-email sample loader. Plain-text attachments are treated as untrusted content; non-text attachments are rejected.
- Read-only customer, invoice, order and business-record tools; Pydantic argument validation, parameterized SQLAlchemy queries, bounded results and database statement/connection timeouts.
- Persistent emails, extractions, drafts, processing runs and sanitized tool audit records.
- Inbox search, category/urgency/status filters, pagination, original-email inspection, business evidence, editable drafts and analytics.
- Explicit approval/rejection, reviewer and UTC timestamps, optimistic revision checks, and automatic approval reset on edits.
- Token authentication, fail-closed configuration, safe database errors, input limits, duplicate email detection, atomic processing claims and retryable failures.
- Alembic migrations, deterministic seed data, Docker Compose, tests and independent evaluation.

## Architecture

```mermaid
flowchart LR
    Human[Human reviewer] --> UI[Streamlit dashboard]
    UI -->|Bearer token| API[FastAPI]
    API --> Workflow[Email service]
    Workflow --> Provider[Demo or OpenAI provider]
    Provider -->|Allowlisted function calls| Tools[Business tools]
    Workflow --> DB[(PostgreSQL)]
    Tools --> DB
    API --> DB
    Eval[Evaluation runner] --> Provider
    Eval --> Reports[JSON and Markdown reports]
```

API routes are in `app/api/routes.py`; workflow orchestration is in `app/services/email_service.py`; provider integration is in `app/services/llm_service.py`; all tool queries are in `app/services/business_tools.py`. SQLAlchemy models and schemas are separate. Provider implementations expose extraction and drafting methods; orchestration also exposes `classify_email`, `extract_email_data`, `summarize_email`, `generate_reply_draft`, `retrieve_business_context` and `process_email`. Standalone classification/summary functions intentionally reuse validated extraction; normal processing makes only one extraction call.

## Quick start with Docker Compose

Prerequisites: Git, Docker Desktop with its engine running, and Docker Compose v2. No email account or OpenAI key is needed for demo mode. Run commands from the repository root.

```powershell
Copy-Item .env.example .env  # only if .env does not already exist
```

Edit `.env`: set `APP_API_TOKEN` and a different `DASHBOARD_PASSWORD` to long random private values and leave `LLM_PROVIDER=demo`. The example values are placeholders. The dashboard password must have at least 16 characters. Alternatively, after configuring the API token, run `python -m scripts.configure_dashboard` to generate a dashboard password and save private login instructions under ignored `artifacts/dashboard-access.txt`. Compose explicitly configures PostgreSQL connection settings and the dashboard's internal API address. The default database password is for local development; set `POSTGRES_PASSWORD` before first database creation to change it. If the password contains URL-special characters, configure an encoded database URL in Compose as well.

```powershell
docker compose up --build -d
docker compose logs -f api
```

Compose waits for PostgreSQL health, applies migrations, seeds fictional records, creates the first owner account only if no accounts exist, then starts the API and dashboard. Visit [Dashboard](http://127.0.0.1:8501) and sign in with username `owner` and your initial dashboard password. Existing account passwords are never reset by startup. Browser requests use individual revocable sessions; the service API token is not used by the dashboard. In [API documentation](http://127.0.0.1:8000/docs), select **Authorize** and enter a user session token or the private integration token for supported CLI operations. Ports bind to localhost; PostgreSQL is internal to Compose. See [Internet access](INTERNET_ACCESS.md) for the authenticated HTTPS preview.

```powershell
docker compose run --rm api python -m pytest -q
docker compose run --rm -v "${PWD}/evaluation/reports:/app/evaluation/reports" api python -m evaluation.run_evaluation
docker compose down
```

The explicit writable evaluation mount overrides the API's read-only reports mount for that command. PostgreSQL data persists in a named volume. Do not remove the volume unless you intend to delete stored data.

## Local Python demonstration

Requires Python **3.11+**. This workspace was verified using Python 3.12. On Windows, `py -3.12` can select it if your default `python` is older.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -c requirements.lock.txt
.\.venv\Scripts\python.exe -m scripts.configure_local
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m scripts.seed_database
.\.venv\Scripts\python.exe -m scripts.bootstrap_admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`configure_local` creates an ignored `.env` with a random access token and SQLite configuration. It preserves an existing `.env`. If you previously configured Docker, set `DATABASE_URL=sqlite:///./inbox.db` and `API_BASE_URL=http://127.0.0.1:8000` for this workflow. In a second terminal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py --server.address 127.0.0.1 --server.port 8501
```

For a separately installed PostgreSQL server, use `DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/inbox`, create that database first, and run the same migrations and seed commands. Use URL-encoded credentials. No tables are created automatically on API startup.

## Environment variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy database URL; Compose overrides this with its PostgreSQL service |
| `APP_API_TOKEN` | Required bearer token for all inbox, review and analytics routes |
| `DASHBOARD_PASSWORD` | Initial owner bootstrap password, at least 16 characters; changing it does not reset existing account passwords |
| `BOOTSTRAP_ADMIN_USERNAME` | First administrator username, default `owner`; applies only when no accounts exist |
| `LLM_PROVIDER` | `demo` (offline rules) or `openai` |
| `OPENAI_API_KEY` | Your OpenAI key, required only for OpenAI mode |
| `OPENAI_MODEL` | A model available to your account that supports Responses, structured outputs and function calling; required in OpenAI mode |
| `LLM_TIMEOUT_SECONDS` | Per-request SDK timeout; default 45 seconds, with one SDK retry |
| `API_BASE_URL` | Dashboard/sample-loader API address; Compose dashboard overrides to `http://api:8000` |
| `SAMPLE_DUE_DATE` | Seed invoice date, default `2026-11-30`; existing records are preserved |
| `POSTGRES_PASSWORD` | Compose database password, default `inbox` for local development |

Set the provider, API key and model in `.env`, then restart the API (or recreate Compose services) to enable live AI. There is no silent fallback to offline rules on live-provider errors. A failure is saved and displayed for inspection/retry. Settings are loaded once per process.

Official integration references: [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) and [Function calling](https://developers.openai.com/api/docs/guides/function-calling). The provider uses `responses.parse(..., text_format=...)` and bounded `responses.create` tool loops. Responses are not stored at the API provider via this application's requests (`store=False`). Consider your organization's data-sharing requirements before using real emails.

## Exact demonstration steps

1. Open [the dashboard](http://127.0.0.1:8501), sign in with your individual username/password (initial owner: `owner` and the existing dashboard password), and confirm the offline demonstration banner.
2. On **Inbox**, expand **Add an email** and submit its prefilled fictional invoice enquiry. Alternatively import `samples/invoice.eml`.
3. Open **Email Details**. The new email ID is selected automatically. Click **Process email**.
4. Inspect the summary and extraction. Expand business evidence to see invoice `INV-1042`: **Pending**, **AED 3500.00**, due **2026-11-30** (or your configured seed date). Email assertions and database evidence are shown separately.
5. As a Reviewer or Admin, open **Reply Review**. Edit the draft and click **Save edits**, then click **Approve**. Your authenticated username and approval timestamp are recorded; sending remains disabled. Viewers can inspect the draft but cannot edit or approve it.
6. Edit an approved draft and save it again to see approval reset. Try **Reject** to record a different decision.
7. Submit an unknown invoice, such as `INV-9999`, and process it. The reply asks for clarification rather than inventing a status.
8. Run the evaluation command below, then open **Analytics** to inspect measured results and charts.

To populate a larger inbox while the API is running:

```powershell
.\.venv\Scripts\python.exe -m scripts.load_sample_emails
```

This imports the fixed 60-case dataset without processing it or spending API credits. Repeating the loader reuses duplicate messages.

## API examples

PowerShell examples use the token you configured in `.env`:

```powershell
$headers = @{ Authorization = 'Bearer YOUR_APP_API_TOKEN' }
$body = @{ sender='accounts@aisha.example'; subject='Invoice enquiry'; body='Please check invoice INV-1042.' } | ConvertTo-Json
$email = Invoke-RestMethod http://127.0.0.1:8000/emails -Method Post -Headers $headers -ContentType application/json -Body $body
$result = Invoke-RestMethod "http://127.0.0.1:8000/emails/$($email.id)/process" -Method Post -Headers $headers
$review = @{revision=$result.draft.revision; reviewer='Demo reviewer'} | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:8000/drafts/$($result.draft.id)/approve" -Method Post -Headers $headers -ContentType application/json -Body $review
```

Example extraction for that enquiry includes `category: invoice_enquiry`, `invoice_number: INV-1042`, unknown email-stated amount/currency as `null`, and a human-review next step. The verified amount comes from tool evidence, not the extraction. In demo mode the reply says the demonstration records list the invoice as Pending for AED 3500.00.

| Endpoint | Behavior |
|---|---|
| `POST /emails` | Validate, normalize and persist; identical payloads reuse the stored email |
| `POST /emails/import` | Multipart `file` field with `.eml`, maximum 100 KB |
| `GET /emails` | `q`, `category`, `urgency`, `status`, `offset`, `limit` filters |
| `GET /emails/{id}` | Original email and status |
| `POST /emails/{id}/process` | Run once; completed retries return existing results, concurrent work returns 409 |
| `GET /emails/{id}/results` | Extraction, draft, processing runs and tool logs |
| `PATCH /drafts/{id}` | `{body, revision}`; clears previous approval |
| `POST /drafts/{id}/approve` | `{revision, reviewer}`; approval only |
| `POST /drafts/{id}/reject` | `{revision, reviewer}`; rejection only |
| `POST /drafts/{id}/send` | Always returns 409; no configured sending integration |
| `GET /analytics` | Counts, distributions and latest evaluation report |
| `GET /health` | Public database connectivity and provider mode; no email data |

## Testing and evaluation

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evaluation.run_evaluation
# Optional: live evaluation, incurs API charges for 60 cases
.\.venv\Scripts\python.exe -m evaluation.run_evaluation --live
```

With the demo API running, `python -m scripts.smoke_test` exercises authenticated submission, processing, business lookup, approval, approval reset and persisted analytics against that API. The included Compose setup and this smoke test were verified against PostgreSQL. See `VALIDATION.md` for actual verification results, including dashboard authentication and session checks.

Ordinary tests use mocked SDK responses and the deterministic provider; no API key or credits are required. Tests cover schemas, tool validation/lookups, missing records, imports, text attachments, prompt injection, API timeouts/rate limits, invalid/refused outputs, bounded tool loops, persistence, retries, duplicate requests, review revisions, auth, database failures, thread context and all four dashboard pages.

`evaluation/dataset.jsonl` contains 60 fixed fictional emails with explicit authored categories, factual extraction labels, expected missing identifiers and lookup expectations. `evaluation/build_dataset.py` is their reproducible authoring source. Evaluation uses an isolated seeded SQLite database, never the inbox database. It records classification accuracy and per-category precision/recall/F1, field-level extraction precision/recall/F1, required completeness, validation/processing success, API failures and lookup correctness.

Outputs under `evaluation/reports/`:

- `latest.json`: machine-readable metrics and provider identification, read by Analytics.
- `cases.jsonl`: individual expected/actual fields, draft, evidence, errors and factual-screen flags.
- `report.md`: readable report with methodology limitations.

Unsupported-claim screening checks payment assertions, invoice/order references, amounts and dates against retrieved records. It is a **limited heuristic**, not proof of truth: qualified statements may be flagged, and unsupported claims outside those patterns may be missed. Overall semantic unsupported-claim rate is `null` until measured by human adjudication. Review per-case drafts/evidence manually for a substantive factual audit. Offline rule scores must not be presented as LLM performance.

## Reliability, security and limits

- Individual accounts use hashed passwords and revocable one-hour sessions. API-enforced Admin, Reviewer and Viewer roles control actions; human review identities come from the authenticated account. Role changes, account disabling, password resets and self-service password changes revoke sessions. The private service token remains only for trusted CLI integration and cannot manage accounts. See `ACCOUNTS.md` for implementation details. Before handling real customer information add MFA/federated identity, stronger perimeter abuse protection, tenant isolation where needed, and managed secrets. HTTPS previews use the optional tunnel profile.
- No mailbox sync, SMTP/send integration, OCR, PDF or Word parsing is included. Text documents and `.eml` text attachments are supported. HTML-only email is rejected; binary attachments are rejected. Total email content is limited to 50,000 characters; attached text documents to 10,000 characters. Attachments are never executed or extracted to disk.
- Demo classification and summaries are simple rules; live AI quality requires your own evaluation. Summaries can consider up to five prior messages from the same explicitly supplied thread reference, bounded to 5,000 characters each. Demo summaries only indicate thread availability.
- Processing is synchronous. For large volumes add a durable queue and workers. Requests atomically claim emails before model calls. If a worker is killed, a run can stay `processing`. Stop **all** API workers, then recover runs older than 30 minutes with `python -m scripts.recover_processing --workers-stopped`; restart and retry. Never recover while workers are active.
- PostgreSQL queries have a five-second statement timeout; SQLite lock timeout is five seconds. Live tools are read-only, results are bounded, and model-requested tool rounds are limited to five. SDK timeouts/retries bound individual network calls, though a full tool loop can take longer than the dashboard's HTTP timeout. Refresh results before retrying.
- Failure codes and field/type validation errors are saved without raw exceptions or secret-bearing output. Tool search arguments are hashed in audit logs. Required business evidence is stored for reviewer visibility and can contain customer details; protect and retain that database appropriately.
- Duplicate identity is a SHA-256 hash of normalized sender/subject/body/thread. It is exact-content deduplication rather than mailbox Message-ID semantics. Successful processing is immutable; draft edits are separately revisioned.
- Schema compliance and prompts do not guarantee factual truth. Human review is always required. Sending is deliberately unavailable; adding it requires provider-confirmed delivery, authorization and approval for the exact reviewed revision.

## Important files

`app/main.py`, `app/api/routes.py`, `app/models/__init__.py`, `app/schemas/__init__.py`, `app/services/`, `frontend/streamlit_app.py`, `alembic/versions/`, `scripts/`, `tests/`, `evaluation/`, `.env.example`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `requirements.lock.txt`.

The lock file captures the dependency versions installed during verification. Use it as constraints with `requirements.txt` for repeatable installs. Secrets belong only in ignored `.env` or your deployment's environment; never commit them.
