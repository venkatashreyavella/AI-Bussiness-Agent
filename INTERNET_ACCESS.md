# Internet access and device support

The dashboard supports current browsers on desktop, tablet and phone. No client installation is needed. Navigation is at the top of every authenticated page; on narrow screens columns stack vertically and buttons have larger touch targets. Inbox cards, extraction fields, business evidence and chart counts have readable text alternatives. Keyboard focus is visible and labels remain attached to controls. These are accessibility improvements, not a claim of a full WCAG or screen-reader certification.

## Sign in

The dashboard requires an individual username/password before any inbox data is requested. The first Admin is `owner`, bootstrapped once from `DASHBOARD_PASSWORD`. Set that initial password to at least 16 characters, distinct from `APP_API_TOKEN`. Generate one before first startup with:

Visitors can now select **Create account** and register their own username/password. New accounts receive Reviewer permissions and immediate access to the shared workspace, including email processing and reply approvals. Account administration remains restricted to Admins. Public registration can be disabled with `PUBLIC_SIGNUP_ENABLED=false` followed by an API restart. This open-registration mode is intended for the fictional demonstration, not confidential inbox data.

```powershell
.\.venv\Scripts\python.exe -m scripts.configure_dashboard
```

The script saves initial owner login instructions to ignored `artifacts/dashboard-access.txt`. Keep the owner's credentials private. Under **Users**, create a separate account and role for each colleague, and share only their individual credentials. Passwords and API tokens must never be put into URLs. The API verifies each user's session and role, including direct requests. See [Accounts and permissions](ACCOUNTS.md).

Failed sign-ins are tracked in PostgreSQL with per-username and global limits across API workers. Sessions last one hour. Sign-out revokes the session; password resets/changes, role changes and account disabling revoke that user's sessions. Existing account passwords live only as hashes in PostgreSQL: editing the bootstrap password in `.env` does not change them. MFA and federated identity are not included.

## Start the HTTPS preview

```powershell
docker compose up --build -d
docker compose --profile public up -d tunnel
docker compose logs tunnel --tail 50
```

Open the generated `https://…trycloudflare.com` URL from another device or network, then sign in. Only the dashboard is routed publicly; the API remains bound to localhost and PostgreSQL has no host port. Cloudflare proxies the connection and terminates public HTTPS. No router port-forwarding or firewall weakening is used.

The link is a **temporary preview**, not permanent cloud hosting. Your computer, Docker Desktop, app containers and tunnel must stay running and online. The hostname changes if the tunnel is recreated; quick tunnels have no uptime guarantee. See [Cloudflare's official Quick Tunnel documentation](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). For a permanent domain and unattended uptime, deploy the containers on an always-on host and use a named tunnel or a managed HTTPS reverse proxy. That requires choosing a hosting account/domain.

To stop internet access without deleting stored data:

```powershell
docker compose --profile public stop tunnel
```

To stop the whole app:

```powershell
docker compose --profile public down
```

The PostgreSQL named volume remains unless explicitly deleted. `restart: unless-stopped` keeps the tunnel process running across Docker restarts, but a restarted quick-tunnel process can obtain a new URL; check its logs again.

## Device checks and limitations

The layout uses a light theme with dark text, visible focus outlines, native labeled controls, a skip-to-main-content link, wrapping navigation, reduced-motion preferences and a single-column layout below 800 pixels. Inbox canvas tables are optional; the default card list is readable without a data grid. Charts have textual count summaries. Forms and reply review remain available by keyboard.

Browser regression tests cover login, incorrect passwords, missing configuration, sign-out, one-hour expiry, password rotation, card navigation and all four app pages. Physical iOS/Android devices and assistive technology combinations have not all been tested. Internet access depends on outbound access to Cloudflare and may be blocked by some organizations or networks.
