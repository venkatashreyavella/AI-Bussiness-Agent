# Connect Gmail and Outlook

Each application user can keep **one Gmail connection and one Outlook connection at the same time**. Imported messages appear in the same Inbox with their provider identified, and remain private to that user. Gmail setup continues to use [GMAIL_SETUP.md](GMAIL_SETUP.md).

Outlook uses Microsoft Graph delegated access for personal Outlook.com/Hotmail accounts and Microsoft 365 work/school accounts with Exchange Online mailboxes. Organization policies can require administrator approval. This integration targets Microsoft's global cloud; sovereign clouds and on-premises Exchange are not configured.

## Microsoft setup

1. Open [Microsoft Entra app registrations](https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) and choose **New registration**. Register an application you control.
2. To allow personal and work accounts, choose **Accounts in any organizational directory and personal Microsoft accounts**. Keep `MICROSOFT_TENANT=common` in the private `.env`.
3. Add the **Web** platform and the exact dashboard root as a redirect URI, including the trailing slash. The local alternative is `http://127.0.0.1:8501/`. Run `python -m scripts.configure_outlook` to write your current exact redirect into `artifacts/outlook-setup-checklist.txt`.
4. Under **API permissions**, add Microsoft Graph **Delegated** permissions: `User.Read`, `Mail.Read`, and `Mail.Send`. MSAL also requests OpenID identity/offline access scopes for sign-in and token renewal. This app does not use application-wide mailbox permissions or `Mail.ReadWrite`.
5. Under **Certificates & secrets**, create a client secret. Copy its **Value**, not its secret ID, into the private `.env`. Record its expiry privately and replace it before expiry. Never paste it into chat or GitHub.
6. Set the private configuration:

```dotenv
MICROSOFT_CLIENT_ID=your-application-client-id
MICROSOFT_CLIENT_SECRET=your-private-client-secret-value
MICROSOFT_TENANT=common
MICROSOFT_REDIRECT_URI=https://your-current-dashboard-host/
OUTLOOK_SEND_ENABLED=false
```

`TOKEN_ENCRYPTION_KEY` is shared with Gmail's credential encryption. The configuration script preserves it; do not replace an existing key. Configure `OPENAI_API_KEY`, `OPENAI_MODEL`, and `LLM_PROVIDER=openai` as described in the Gmail guide before processing real messages.

Restart from the project directory:

```powershell
docker compose up --build -d
```

## Connect and review

Sign in to your application account, open **Outlook**, click **Connect my Outlook**, then continue to Microsoft consent. Choose your Microsoft account and review permissions yourself. Your Microsoft password is entered only on Microsoft's sign-in page. The callback must finish under the same application account that initiated it. OAuth state is single-use, expires after ten minutes, and the MSAL flow uses PKCE. Pending flow secrets and saved token caches are encrypted before database storage.

Use **Sync latest 20 Outlook messages** to import recent Inbox mail. Sync is manual; existing messages are deduplicated using immutable provider identifiers, the mailbox, and the application user. Gmail and Outlook namespaces are separate. MIME is parsed into plain text; attachments and tracking images are not opened. Large or malformed messages are skipped. Sync does not mark mail as read or move it.

In Inbox, process a private message with live AI, review and edit the draft, save changes, and approve the current revision. Enable `OUTLOOK_SEND_ENABLED=true` and restart only when you are ready to allow explicit reviewed sends. Gmail sending is controlled separately by `GMAIL_SEND_ENABLED`.

The app confirms the exact recipient and revision, verifies the originating mailbox and user, and sends a single MIME reply with `In-Reply-To`/`References` through Graph `sendMail`. It does not use Reply All or include attachments. Microsoft returns **202 Accepted**, which the app records as **accepted**, not confirmed delivery. Check Outlook Sent Items for the outcome. The app never automatically retries a send. Ambiguous/interrupted sends lock the draft as `unknown`/`sending`; verify Sent Items manually before recovery. Accepted or attempted drafts cannot be edited or sent again.

**Disconnect Outlook** removes this application's saved token cache; imported messages remain private. It does not revoke Microsoft's grant. Withdraw consent separately in [personal Microsoft app permissions](https://account.live.com/consent/Manage) or your organization's My Apps permissions. Work-account policies can require an administrator to manage consent.

## Deployment and verification limits

A temporary Cloudflare hostname can expire or change. Update both Microsoft and Google redirect registrations and their private environment values when that happens. Use a stable HTTPS domain and an always-on host for ongoing operation. This project does not continuously monitor either inbox.

Automated tests mock Microsoft/Google and exercise OAuth identity binding, encrypted storage, mailbox privacy, MIME handling, duplicate import and sending locks. Live Outlook consent, refresh and real delivery remain unverified until credentials are supplied and you complete consent. No real email is sent during tests.

Official references: [MSAL Python token acquisition](https://learn.microsoft.com/en-us/entra/msal/python/getting-started/acquiring-tokens), [authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow), [Graph list messages](https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0), [immutable IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id), and [sendMail acceptance semantics](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).
