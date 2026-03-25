"""Genie Chat Demo — FastAPI app with OAuth U2M."""

import os
import logging
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, FileResponse, JSONResponse
from pydantic import BaseModel

from oauth import OAuthManager
from genie_client import GenieClient

load_dotenv()
logging.basicConfig(level=logging.INFO)

DATABRICKS_HOST = os.environ["DATABRICKS_HOST"]
CLIENT_ID = os.environ["DATABRICKS_CLIENT_ID"]
CLIENT_SECRET = os.environ["DATABRICKS_CLIENT_SECRET"]
GENIE_SPACE_ID = os.environ["GENIE_SPACE_ID"]
REDIRECT_URL = "http://localhost:8000/auth/callback"

app = FastAPI(title="Genie Chat Demo")

oauth = OAuthManager(
    host=DATABRICKS_HOST,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_url=REDIRECT_URL,
)

genie = GenieClient(host=DATABRICKS_HOST, space_id=GENIE_SPACE_ID)

SESSION_COOKIE = "genie_session"


def _get_token(request: Request) -> str:
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        raise HTTPException(401, "Not authenticated")
    token = oauth.get_token(session_id)
    if not token:
        raise HTTPException(401, "Session expired")
    return token


# ── Static ──


@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ── Auth ──


@app.get("/auth/login")
async def login():
    url = oauth.start_login()
    return RedirectResponse(url)


@app.get("/auth/callback")
async def callback(code: str, state: str):
    try:
        session_id = oauth.handle_callback(code, state)
    except ValueError as e:
        raise HTTPException(400, str(e))

    response = RedirectResponse("/")
    response.set_cookie(SESSION_COOKIE, session_id, httponly=True, samesite="lax")
    return response


@app.get("/auth/status")
async def auth_status(request: Request):
    session_id = request.cookies.get(SESSION_COOKIE)
    authenticated = session_id is not None and oauth.is_authenticated(session_id)
    return {"authenticated": authenticated}


@app.get("/auth/whoami")
async def whoami(request: Request):
    """Check the identity behind the token — proves U2M auth."""
    token = _get_token(request)
    import requests as req
    resp = req.get(
        f"{DATABRICKS_HOST}/api/2.0/preview/scim/v2/Me",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "user": data.get("userName"),
        "display_name": data.get("displayName"),
        "active": data.get("active"),
        "id": data.get("id"),
    }


@app.post("/auth/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE)
    return response


# ── Genie API ──


class AskRequest(BaseModel):
    question: str


class FollowupRequest(BaseModel):
    conversation_id: str
    question: str


@app.post("/api/ask")
async def ask(body: AskRequest, request: Request):
    token = _get_token(request)
    try:
        result = await genie.ask(token, body.question)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/followup")
async def followup(body: FollowupRequest, request: Request):
    token = _get_token(request)
    try:
        result = await genie.followup(token, body.conversation_id, body.question)
        return result
    except Exception as e:
        raise HTTPException(500, str(e))
