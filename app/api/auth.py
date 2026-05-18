"""인증 엔드포인트 — Google OAuth + 세션 관리.

흐름:
  1. GET  /auth/google/login    → PKCE state 발급 후 Google authorize 화면으로 redirect
  2. GET  /auth/google/callback → Google이 호출, 토큰 교환 → user upsert → session 발급
  3. POST /auth/logout          → session 삭제 + cookie 제거
  4. GET  /me                   → 현재 user 정보

OAuth 라이브러리: Authlib (PKCE + JWKS 검증 자동 처리)
세션: 불투명 ID + HTTP-only cookie + DB sessions 테이블
"""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Annotated
from urllib.parse import urlencode, urlparse

import httpx
from authlib.jose import jwt
from fastapi import APIRouter, Cookie, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from app import db
from app.api.deps import CurrentUser
from app.config import (
    COOKIE_SECURE,
    FRONTEND_ORIGINS,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    SESSION_COOKIE_NAME,
    SESSION_TTL_DAYS,
)
from app.services import session_repo, user_repo

logger = logging.getLogger(__name__)

router = APIRouter()

# Google OAuth 표준 endpoint들 (변하지 않는 상수)
_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS_URL  = "https://www.googleapis.com/oauth2/v3/certs"

# OAuth state TTL — 사용자가 Google 화면에서 시간 끌어도 10분 안에 돌아오면 OK
_STATE_TTL = timedelta(minutes=10)


def init_schema() -> None:
    """oauth_states 테이블 생성 (PKCE verifier + CSRF state, 단명)."""
    with db.connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS oauth_states (
                state          TEXT PRIMARY KEY,
                code_verifier  TEXT NOT NULL,
                return_to      TEXT,
                created_at     TEXT NOT NULL
            )
        """)
        conn.commit()


# ────────────── /me, /logout ──────────────

@router.get("/me")
def me(user: CurrentUser) -> dict:
    """현재 로그인된 사용자 정보."""
    return {
        "id":            user["id"],
        "email":         user["email"],
        "name":          user["name"],
        "picture_url":   user["picture_url"],
        "created_at":    user["created_at"],
        "last_login_at": user["last_login_at"],
    }


@router.post("/auth/logout")
def logout(
    response: Response,
    tf_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE_NAME)] = None,
) -> dict:
    """세션 삭제 + 쿠키 정리. 멱등."""
    if tf_session:
        session_repo.delete(tf_session)
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        samesite="lax",
    )
    return {"ok": True}


# ────────────── Google OAuth ──────────────

@router.get("/auth/google/login")
def google_login(return_to: str | None = Query(default=None)) -> RedirectResponse:
    """OAuth 시작 — PKCE state 발급 후 Google authorize 화면으로 302."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID not configured")

    # return_to 검증 — open-redirect 방지
    safe_return_to = _validate_return_to(return_to)

    # PKCE — code_verifier 생성 후 code_challenge = SHA256(verifier) (Authlib이 자동 처리 가능하지만 명시적으로)
    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = _pkce_challenge(code_verifier)

    # state + verifier 저장 (10분 후 callback에서 매칭)
    now_iso = datetime.utcnow().isoformat()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, code_verifier, return_to, created_at) "
            "VALUES (?, ?, ?, ?)",
            (state, code_verifier, safe_return_to, now_iso),
        )
        # 오래된 state 일괄 정리 (opportunistic GC)
        cutoff = (datetime.utcnow() - _STATE_TTL).isoformat()
        conn.execute("DELETE FROM oauth_states WHERE created_at < ?", (cutoff,))
        conn.commit()

    # Google authorize URL 조립
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",       # refresh token 안 받음 (세션 30일 + 슬라이딩으로 충분)
        "prompt": "select_account",    # 매번 계정 선택 화면 (단일 user 가정 시 'consent' 제거)
    }
    authorize_url = f"{_GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(authorize_url, status_code=302)


@router.get("/auth/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Google이 호출 — code를 토큰으로 교환, user upsert, 세션 발급, 프론트로 redirect."""
    if error:
        logger.warning("oauth callback error: %s", error)
        raise HTTPException(400, f"oauth error: {error}")
    if not code or not state:
        raise HTTPException(400, "missing code or state")

    # state 검증 + 소비 (1회용)
    saved = _consume_state(state)
    if not saved:
        raise HTTPException(400, "invalid or expired state")

    code_verifier = saved["code_verifier"]
    return_to = saved["return_to"] or FRONTEND_ORIGINS[0]

    # 토큰 교환
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code_verifier": code_verifier,
            },
        )
        if token_resp.status_code != 200:
            logger.error("token exchange failed: %s %s", token_resp.status_code, token_resp.text)
            raise HTTPException(400, "token exchange failed")
        token_data = token_resp.json()

        id_token = token_data.get("id_token")
        if not id_token:
            raise HTTPException(400, "no id_token in response")

        # JWKS 조회 + ID 토큰 검증
        jwks_resp = await client.get(_GOOGLE_JWKS_URL)
        jwks = jwks_resp.json()

    claims = jwt.decode(
        id_token, jwks,
        claims_options={
            "iss": {"essential": True, "values": ["https://accounts.google.com", "accounts.google.com"]},
            "aud": {"essential": True, "value": GOOGLE_CLIENT_ID},
            "exp": {"essential": True},
        },
    )
    claims.validate()

    # user upsert
    user = user_repo.upsert_from_google(
        google_sub=claims["sub"],
        email=claims.get("email", ""),
        email_verified=bool(claims.get("email_verified", False)),
        name=claims.get("name"),
        picture_url=claims.get("picture"),
    )

    # 세션 발급
    session_id = session_repo.create(
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )

    # 프론트로 redirect (쿠키 첨부)
    redirect = RedirectResponse(return_to, status_code=302)
    redirect.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    logger.info("login success: user_id=%d email=%s", user["id"], user["email"])
    return redirect


# ────────────── 내부 헬퍼 ──────────────

def _pkce_challenge(verifier: str) -> str:
    """SHA256(verifier) → base64url (padding 제거). RFC 7636."""
    import base64
    import hashlib
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _consume_state(state: str) -> dict | None:
    """state 조회 + 즉시 삭제 (1회용). TTL 초과 시 None.

    반환: {"code_verifier": ..., "return_to": ...} 또는 None.
    """
    cutoff = (datetime.utcnow() - _STATE_TTL).isoformat()
    with db.connection() as conn:
        row = conn.execute(
            "SELECT code_verifier, return_to FROM oauth_states "
            "WHERE state = ? AND created_at >= ?",
            (state, cutoff),
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
        conn.commit()
        return dict(row)


def _validate_return_to(return_to: str | None) -> str:
    """open-redirect 방지 — FRONTEND_ORIGINS의 origin과 일치하는 URL만 허용.

    경로만 (예: '/projects') 들어오면 FRONTEND_ORIGINS[0]와 합쳐 절대 URL로 변환.
    """
    if not return_to:
        return FRONTEND_ORIGINS[0] + "/"

    # 절대 경로만 (예: "/projects") → 기본 frontend origin과 합침
    if return_to.startswith("/"):
        return FRONTEND_ORIGINS[0].rstrip("/") + return_to

    # 절대 URL이면 origin이 허용 목록에 있는지 확인
    parsed = urlparse(return_to)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in FRONTEND_ORIGINS:
        logger.warning("rejected return_to (origin not allowlisted): %s", return_to)
        return FRONTEND_ORIGINS[0] + "/"
    return return_to
