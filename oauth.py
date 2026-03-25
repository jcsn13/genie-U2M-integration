"""OAuth U2M manager for Databricks — web-based redirect flow."""

import uuid
import logging
from typing import Dict, Optional

from databricks.sdk.oauth import OAuthClient, Consent, SessionCredentials

logger = logging.getLogger(__name__)


class OAuthManager:
    """Manages OAuth U2M flow via browser redirects."""

    def __init__(self, host: str, client_id: str, client_secret: str, redirect_url: str):
        self._client = OAuthClient.from_host(
            host=host,
            client_id=client_id,
            client_secret=client_secret,
            redirect_url=redirect_url,
            scopes=["all-apis", "offline_access"],
        )
        self._pending: Dict[str, Consent] = {}  # state -> Consent
        self._sessions: Dict[str, SessionCredentials] = {}  # session_id -> creds

    def start_login(self) -> str:
        """Start OAuth flow. Returns the authorization URL to redirect the user to."""
        consent = self._client.initiate_consent()
        self._pending[consent.as_dict()["state"]] = consent
        logger.info("OAuth consent initiated")
        return consent.authorization_url

    def handle_callback(self, code: str, state: str) -> str:
        """Exchange auth code for tokens. Returns a session ID."""
        consent = self._pending.pop(state, None)
        if not consent:
            raise ValueError("Unknown OAuth state — login may have expired")

        creds = consent.exchange(code, state)
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = creds
        logger.info(f"OAuth session created: {session_id}")
        return session_id

    def get_token(self, session_id: str) -> Optional[str]:
        """Get a valid access token for a session. Auto-refreshes if expired."""
        creds = self._sessions.get(session_id)
        if not creds:
            return None
        return creds.token().access_token

    def is_authenticated(self, session_id: str) -> bool:
        return session_id in self._sessions
