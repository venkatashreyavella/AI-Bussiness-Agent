# Individual accounts and permissions

Each person signs in with their own username and password. Manual demo emails use a shared business workspace. Gmail and Outlook imports are private to their owner, including from other Admins; see `GMAIL_SETUP.md` and `OUTLOOK_SETUP.md`. Each user can connect both providers at once.

## Create your own account

Anyone with the dashboard URL can select **Create account** on the sign-in screen. Choose a unique username and password of at least 16 characters, confirm the password, and optionally provide a display name. Submission creates an enabled Reviewer account and signs you in immediately; no Admin-created login or email invitation is required. Reviewers can read, add and process shared emails, edit drafts, and approve or reject replies. They cannot administer users or reset other people's passwords.

The server always assigns the Reviewer role for public registration. Supplying `role=admin` or account-status fields is rejected. Existing accounts cannot be claimed, overwritten or re-enabled through registration, and usernames are unique without regard to case. Registration is limited to ten attempts per minute globally, including duplicate attempts. PostgreSQL serializes those checks across workers; rate-limit failures return 429 with a Retry-After header.

Public registration is enabled by default for this explicitly open demonstration. **Anyone who registers can see and modify the shared fictional business inbox.** Do not use open signup for confidential customer data. To close signup, set `PUBLIC_SIGNUP_ENABLED=false` and recreate/restart the API; existing accounts remain available and Admins can still create users under Users. Registration does not open until an active Admin has been bootstrapped.

| Permission | Viewer | Reviewer | Admin |
|---|---|---|---|
| Read inbox, results, drafts and analytics | Yes | Yes | Yes |
| Add/import/process emails | No | Yes | Yes |
| Edit, approve or reject drafts | No | Yes | Yes |
| Change own password | Yes | Yes | Yes |
| Create/disable accounts, assign roles, reset passwords | No | No | Yes |
| View account and review audit events | No | No | Yes |
| Send an explicitly confirmed approved reply from own Gmail or Outlook | No | When configured | When configured |

## Owner's first sign-in

The initial administrator username is **owner**, or the value of `BOOTSTRAP_ADMIN_USERNAME` if configured. Its initial password is your existing dashboard password, saved privately in ignored `artifacts/dashboard-access.txt`. Sign in at the existing dashboard URL with both fields. Old shared-password-only sessions are no longer accepted.

The migration bootstrap creates the first admin only when there are no accounts. It never resets existing passwords or restores disabled accounts. `DASHBOARD_PASSWORD` is now an initial bootstrap value, not an ongoing login backdoor. Once you change your account password, the old bootstrap credential stops working for that account.

## Administrator-managed accounts (optional)

1. Sign in as an Admin and select **Users** in Workspace navigation.
2. Under **Create an account**, enter their username, display name, initial password (at least 16 characters), and role. New accounts default to Viewer.
3. Click **Create account**. Share that person's username, password and public dashboard URL privately. The app does not send email invitations or publish passwords.
4. They sign in with their own account. Under **My Account** they can change their password.

Do not share the owner's credentials with colleagues. Usernames are case-insensitive, 3–80 characters, using letters, numbers, dots, underscores, `@`, `+`, or hyphens. Accounts are disabled rather than deleted, preserving identity in historical review/audit records.

## Manage access

Under **Users**, select an existing account to change its role or enabled status. Changes revoke that person's sessions; their next request requires a fresh sign-in. The last enabled Admin cannot be disabled or demoted. Password reset also revokes all sessions, and the replacement must be shared privately with the intended person.

**My Account → Change my password** requires the existing password and signs out all sessions. A signed-in Reviewer/Admin's username is recorded on review decisions by the API; editing the submitted `reviewer` label cannot impersonate someone else.

## Security implementation

- Passwords are salted PBKDF2-HMAC-SHA256 hashes with 600,000 iterations; plaintext passwords are not stored in the account database. See [OWASP password-storage guidance](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
- Login creates a random 256-bit opaque session token. Only its SHA-256 digest is stored in PostgreSQL. The dashboard retains the token in server-side Streamlit session state, sends it to the private API in an Authorization header, and never puts it into browser storage or URLs.
- Sessions expire after one hour and can be revoked by logout, password changes/resets, disabling accounts or changing roles. The API checks account status and role on every request. See [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
- Permission checks are enforced on API endpoints, including direct requests. Hiding/disabling dashboard controls is supplemental.
- Failed sign-ins are tracked in PostgreSQL: at most ten failures per username per minute and one hundred globally. PostgreSQL advisory locks serialize the counter checks across API workers. Limits do not rely on spoofable caller IP headers. An attacker can temporarily exhaust the shared global allowance; a production deployment should add perimeter rate limiting and identity-provider protection.
- Security audit records include account creation/changes, password resets/changes, sign-in/out and draft edits/decisions. They contain actor, action, target and UTC timestamp, without passwords/session tokens. Admins can inspect the latest 100 events.
- The private `APP_API_TOKEN` remains available to trusted server-side CLI integrations for the existing email workflow. It has privileged workspace access and must not be shared. It cannot manage user accounts, and the dashboard no longer uses it for any request. Integration reviews are logged as `service`; human review decisions use authenticated usernames.

This is a single-workspace account system, not a multi-tenant platform. Public self-registration is included; MFA, federated identity, email verification and email password-reset links are not included. Admins recover accounts with the reset action. Keep public access over HTTPS and protect the database and environment files.

## Setup and verification

Docker Compose now applies migrations, seeds fictional business data, and runs `python -m scripts.bootstrap_admin` before starting the API. For local Python setup, run the bootstrap command after migrations. Existing accounts are preserved on restart.

```powershell
docker compose up --build -d
docker compose exec -T api python -m alembic check
docker compose exec -T api python -m pytest -q
```

To run tests against PostgreSQL rather than the default SQLite fixtures:

```powershell
docker compose run --rm --no-deps api python -c "import os,pytest; os.environ['TEST_DATABASE_URL']=os.environ['DATABASE_URL']; raise SystemExit(pytest.main(['-q','--tb=short','-p','no:cacheprovider']))"
```

Each database-backed test creates a randomly named `inbox_test_…` schema and drops only that schema afterwards. Existing workspace tables and user accounts are not modified by those test fixtures.

API endpoints: `GET /auth/registration`, `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/password`, `GET/POST /users`, `PATCH /users/{id}`, `POST /users/{id}/reset-password`, `GET /users/audit/events`. Registration options and registration are public; all `/users` endpoints require a human administrator session.
