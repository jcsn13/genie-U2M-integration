# Genie Chat Demo — OAuth U2M

A simple localhost web app that authenticates to Databricks using OAuth U2M (on behalf of user) and provides a chat interface to a Genie space. Unity Catalog permissions are enforced per user.

## Architecture

```
Browser → FastAPI (localhost:8000) → OAuth U2M → Databricks Genie API
```

- **oauth.py** — OAuth Authorization Code flow with PKCE using the Databricks SDK
- **genie_client.py** — Genie REST API wrapper (start conversation, follow-up, poll results)
- **main.py** — FastAPI app wiring auth + Genie + static frontend
- **static/index.html** — Chat UI (vanilla HTML/CSS/JS)

The user authenticates via browser redirect to Databricks. The app receives the user's token and uses it to call the Genie API — all queries run as the authenticated user.

## Example usage

The following recording shows signing in with Databricks and chatting with Genie in the local UI.

![Genie Chat integration demo](genie_integration.gif)

## Prerequisites

### 1. Register an OAuth App in Databricks

Go to your **Databricks Account Console** → **Settings** → **App Connections** → **Add Connection**:

- **Name**: `genie-chat-demo` (or any name)
- **Redirect URL**: `http://localhost:8000/auth/callback`
- **Access scopes**: `all-apis`
- **Generate a client secret**

Note the **Client ID** and **Client Secret**.

### 2. Have a Genie Space

You need an existing Genie space in your workspace. Copy the **Space ID** from the Genie room URL:

```
https://<workspace>/genie/rooms/<SPACE_ID>?o=...
```

### 3. Python 3.10+

Ensure Python 3.10 or later is installed.

## Setup

```bash
# Clone / navigate to the project
cd genie-integration

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

Edit `.env` with your values:

```
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_CLIENT_ID=<your-client-id>
DATABRICKS_CLIENT_SECRET=<your-client-secret>
GENIE_SPACE_ID=<your-genie-space-id>
```

## Run

```bash
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

## Usage

1. Click **Sign in with Databricks** — you'll be redirected to Databricks for consent
2. After login, you'll return to the chat interface
3. Type a question and press Enter or click Send
4. Genie responds with text, SQL queries, and result tables
5. Follow-up questions continue in the same conversation
6. Click suggested questions to ask them directly

## Verify User Identity

To confirm the app is authenticating as you (not a service principal), visit while logged in:

```
http://localhost:8000/auth/whoami
```

This calls the Databricks SCIM `/Me` endpoint and returns your username, confirming U2M auth is working.

## How It Works

### OAuth U2M Flow

1. User clicks Login → app redirects to Databricks authorization endpoint
2. User consents → Databricks redirects back with an authorization code
3. App exchanges the code for access + refresh tokens (PKCE-protected)
4. Tokens are cached in memory per session
5. The Databricks SDK auto-refreshes expired tokens using the refresh token

### Genie API Calls

1. `POST /api/2.0/genie/spaces/{space_id}/start-conversation` — starts a new chat
2. `GET .../messages/{message_id}` — polls until Genie finishes (COMPLETED/FAILED)
3. `GET .../query-result/{attachment_id}` — fetches SQL query results
4. `POST .../conversations/{conv_id}/messages` — sends follow-up questions

All API calls use `Authorization: Bearer <user_token>`, so UC permissions and Genie space access are enforced per user.

## Project Structure

```
genie-integration/
├── main.py              # FastAPI app — routes and wiring
├── oauth.py             # OAuth U2M manager (uses databricks-sdk)
├── genie_client.py      # Genie REST API wrapper
├── static/
│   └── index.html       # Chat UI
├── .env.example         # Environment variable template
├── requirements.txt     # Python dependencies
└── README.md
```
