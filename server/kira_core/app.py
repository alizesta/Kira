from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[2]
DB_URL = os.environ.get("KIRA_DATABASE_URL", f"sqlite:///{ROOT / 'server' / 'data' / 'kira_core.sqlite3'}")
if DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
if DB_URL.startswith("sqlite:///"):
    Path(DB_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)

_engine_options: dict[str, Any] = {"pool_pre_ping": True}
if DB_URL.startswith("sqlite:"):
    _engine_options["connect_args"] = {"check_same_thread": False}
engine = create_engine(DB_URL, **_engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(80), default="")
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountSettings(Base):
    __tablename__ = "account_settings"
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (UniqueConstraint("account_id", "provider_id", name="uq_account_provider"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    provider_id: Mapped[str] = mapped_column(String(100))
    ciphertext: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    route: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CharacterMemory(Base):
    __tablename__ = "character_memory"
    __table_args__ = (UniqueConstraint("account_id", "character_id", name="uq_account_character_memory"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(String(80))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("account_id", "device_id", name="uq_account_device"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str] = mapped_column(String(36))
    platform: Mapped[str] = mapped_column(String(20))
    device_name: Mapped[str] = mapped_column(String(120), default="")
    app_version: Mapped[str] = mapped_column(String(40), default="")
    local_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (UniqueConstraint("account_id", "import_id", name="uq_account_import"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    import_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Kira Core API",
    version="1.0.0",
    description="Shared account, brain, routing, memory and sync service for Kira Windows and Android clients.",
)

allowed_origins = [x.strip() for x in os.environ.get("KIRA_CORS_ORIGINS", "").split(",") if x.strip()]
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

bearer = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _token_secret() -> bytes:
    value = os.environ.get("KIRA_TOKEN_SECRET", "")
    if len(value) < 32:
        raise HTTPException(status_code=503, detail="Kira Core token secret is not configured.")
    return value.encode("utf-8")


def _fernet() -> Fernet:
    key = os.environ.get("KIRA_ENCRYPTION_KEY", "")
    try:
        return Fernet(key.encode("ascii"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Kira Core encryption key is not configured.") from exc


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return "pbkdf2_sha256$310000$" + _b64(salt) + "$" + _b64(digest)


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(digest, _unb64(expected))
    except Exception:
        return False


def _jwt(account_id: str, expires_seconds: int) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({"sub": account_id, "exp": int(time.time()) + expires_seconds, "iss": "kira-core"},
                              separators=(",", ":")).encode())
    signing = f"{header}.{payload}".encode("ascii")
    signature = _b64(hmac.new(_token_secret(), signing, hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}"


def _verify_jwt(token: str) -> str:
    try:
        header, payload, signature = token.split(".", 2)
        signing = f"{header}.{payload}".encode("ascii")
        expected = _b64(hmac.new(_token_secret(), signing, hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        data = json.loads(_unb64(payload))
        if data.get("iss") != "kira-core" or int(data.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired token")
        account_id = str(data.get("sub") or "")
        uuid.UUID(account_id)
        return account_id
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from exc


def _issue_session(db: Session, account: Account) -> dict:
    access_seconds = int(os.environ.get("KIRA_ACCESS_TOKEN_TTL", "900"))
    refresh_seconds = int(os.environ.get("KIRA_REFRESH_TOKEN_TTL", "2592000"))
    refresh = secrets.token_urlsafe(48)
    db.add(RefreshSession(
        token_hash=hashlib.sha256(refresh.encode()).hexdigest(),
        account_id=account.id,
        expires_at=utcnow() + timedelta(seconds=refresh_seconds),
    ))
    db.commit()
    return {
        "account_id": account.id,
        "access_token": _jwt(account.id, access_seconds),
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": access_seconds,
    }


def current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> Account:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    account_id = _verify_jwt(credentials.credentials)
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return account


def _email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 320 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise HTTPException(status_code=422, detail="A valid email address is required.")
    return normalized


def _safe_settings(data: dict) -> dict:
    """Strip every credential-like field recursively before account settings reach storage."""
    blocked = {
        "api_key", "apikey", "tavily_api_key", "password", "password_hash",
        "access_token", "refresh_token", "token", "secret", "authorization",
        "credential", "credentials", "private_key",
    }

    def clean(value):
        if isinstance(value, dict):
            safe = {}
            for key, item in value.items():
                name = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
                if name in blocked or name.endswith(("_api_key", "_password", "_secret", "_token", "_credential")):
                    continue
                safe[str(key)] = clean(item)
            return safe
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(data) if isinstance(data, dict) else {}


def _account_settings(db: Session, account_id: str) -> AccountSettings:
    state = db.get(AccountSettings, account_id)
    if state is None:
        state = AccountSettings(account_id=account_id, revision=0, settings={
            "active_character_id": "kira",
            "temperature": 0.7,
            "failover_enabled": True,
            "brain_mode": "auto",
            "brain_reflection": "rules",
            "providers": {},
            "routes": [],
        })
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


class SettingsRequest(BaseModel):
    revision: int = Field(ge=0)
    settings: dict


class CredentialRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=4096)
    account_id: str | None = Field(default=None, max_length=200)


class ConversationRequest(BaseModel):
    character_id: str = Field(min_length=1, max_length=80)
    title: str = Field(default="", max_length=200)


class ChatRequest(BaseModel):
    conversation_id: str
    character_id: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1, max_length=100_000)
    attachment_ids: list[str] = Field(default_factory=list)
    approved_screen_context: bool = False


class MemoryRequest(BaseModel):
    revision: int = Field(ge=0)
    items: list[dict] = Field(max_length=5000)


class DeviceRequest(BaseModel):
    device_id: str
    platform: str
    device_name: str = Field(default="", max_length=120)
    app_version: str = Field(default="", max_length=40)
    local_capabilities: list[str] = Field(default_factory=list, max_length=100)


class ImportRequest(BaseModel):
    import_id: str
    shared_data: dict
    provider_credentials: dict[str, dict] | None = None


@app.get("/v1/health")
def health():
    return {"status": "ok", "api_version": "1.0.0"}


@app.post("/v1/auth/register", status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    _token_secret()
    account = Account(
        email=_email(str(payload.email)),
        display_name=payload.display_name.strip(),
        password_hash=_hash_password(payload.password),
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists.") from exc
    return _issue_session(db, account)


@app.post("/v1/auth/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    _token_secret()
    account = db.scalar(select(Account).where(Account.email == _email(str(payload.email))))
    if account is None or not _verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    return _issue_session(db, account)


@app.post("/v1/auth/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
    row = db.get(RefreshSession, token_hash)
    if row is None or row.revoked or row.expires_at.replace(tzinfo=timezone.utc) <= utcnow():
        raise HTTPException(status_code=401, detail="Refresh token is invalid or expired.")
    account = db.get(Account, row.account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    row.revoked = True
    db.commit()
    return _issue_session(db, account)


@app.post("/v1/auth/logout", status_code=204)
def logout(payload: RefreshRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    token_hash = hashlib.sha256(payload.refresh_token.encode()).hexdigest()
    row = db.get(RefreshSession, token_hash)
    if row is not None and row.account_id == account.id:
        row.revoked = True
        db.commit()
    return None


@app.get("/v1/account")
def account_profile(account: Account = Depends(current_account)):
    return {
        "account_id": account.id,
        "email": account.email,
        "display_name": account.display_name,
        "linked_identities": ["email_password"],
        "created_at": account.created_at.isoformat(),
    }


@app.get("/v1/settings")
def get_settings(account: Account = Depends(current_account), db: Session = Depends(get_db)):
    state = _account_settings(db, account.id)
    credentials = db.scalars(select(ProviderCredential).where(ProviderCredential.account_id == account.id)).all()
    return {
        "account_id": account.id,
        "revision": state.revision,
        "settings": _safe_settings(state.settings),
        "cloud_routes": [
            {"provider_id": item.provider_id, "credential_configured": True, "updated_at": item.updated_at.isoformat()}
            for item in credentials
        ],
        "updated_at": state.updated_at.isoformat(),
    }


@app.put("/v1/settings")
def put_settings(payload: SettingsRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    state = _account_settings(db, account.id)
    if payload.revision != state.revision:
        raise HTTPException(status_code=409, detail={"message": "Settings revision conflict.", "current_revision": state.revision})
    state.settings = _safe_settings(payload.settings)
    state.revision += 1
    state.updated_at = utcnow()
    db.commit()
    return {"revision": state.revision, "updated_at": state.updated_at.isoformat()}


@app.put("/v1/settings/providers/{provider_id}/credential", status_code=204)
def put_provider_credential(
    provider_id: str,
    payload: CredentialRequest,
    account: Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", provider_id):
        raise HTTPException(status_code=422, detail="Invalid provider identifier.")
    encrypted = _fernet().encrypt(json.dumps({"api_key": payload.api_key, "account_id": payload.account_id},
                                             separators=(",", ":")).encode("utf-8")).decode("ascii")
    row = db.scalar(select(ProviderCredential).where(
        ProviderCredential.account_id == account.id, ProviderCredential.provider_id == provider_id))
    if row is None:
        db.add(ProviderCredential(account_id=account.id, provider_id=provider_id, ciphertext=encrypted))
    else:
        row.ciphertext = encrypted
        row.updated_at = utcnow()
    db.commit()
    return None


@app.delete("/v1/settings/providers/{provider_id}/credential", status_code=204)
def delete_provider_credential(provider_id: str, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    row = db.scalar(select(ProviderCredential).where(
        ProviderCredential.account_id == account.id, ProviderCredential.provider_id == provider_id))
    if row is not None:
        db.delete(row)
        db.commit()
    return None


@app.get("/v1/conversations")
def list_conversations(
    character_id: str | None = None,
    account: Account = Depends(current_account),
    db: Session = Depends(get_db),
):
    query = select(Conversation).where(Conversation.account_id == account.id)
    if character_id:
        query = query.where(Conversation.character_id == character_id)
    rows = db.scalars(query.order_by(Conversation.updated_at.desc()).limit(200)).all()
    return {"items": [
        {"id": row.id, "character_id": row.character_id, "title": row.title,
         "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat()}
        for row in rows
    ]}


@app.post("/v1/conversations", status_code=201)
def create_conversation(payload: ConversationRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    conversation = Conversation(
        account_id=account.id,
        character_id=payload.character_id,
        title=payload.title.strip() or payload.character_id.title(),
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return {"id": conversation.id, "character_id": conversation.character_id, "title": conversation.title}


@app.get("/v1/conversations/{conversation_id}/messages")
def list_messages(conversation_id: str, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.account_id != account.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    rows = db.scalars(select(Message).where(
        Message.account_id == account.id, Message.conversation_id == conversation_id
    ).order_by(Message.created_at.asc()).limit(5000)).all()
    return {"items": [
        {"id": row.id, "role": row.role, "content": row.content, "route": row.route,
         "created_at": row.created_at.isoformat()}
        for row in rows
    ]}


def _profile_for(character_id: str, settings: dict) -> dict:
    if character_id == "kira":
        from kira.characters.kira import PROFILE
        return PROFILE
    from kira.personas import all_profiles
    profile = all_profiles(settings).get(character_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Character profile not found.")
    prompt = "\n\n".join(x for x in (
        str(profile.get("prompt") or ""),
        str(profile.get("specialty_prompt") or ""),
    ) if x.strip())
    return {
        "id": character_id,
        "name": profile.get("name") or character_id.title(),
        "description": profile.get("description") or "",
        "notes": profile.get("notes") or "",
        "system_prompt": prompt,
    }


def _memory_block(db: Session, account_id: str, character_id: str) -> str:
    row = db.scalar(select(CharacterMemory).where(
        CharacterMemory.account_id == account_id, CharacterMemory.character_id == character_id))
    if row is None or not row.items:
        return ""
    lines = []
    for item in row.items[-80:]:
        text = str(item.get("text") or item.get("content") or "").strip() if isinstance(item, dict) else str(item).strip()
        if text:
            lines.append("- " + text[:500])
    return f"Shared account memory for {character_id}:\n" + "\n".join(lines) if lines else ""


def _server_router_settings(db: Session, account_id: str, stored: dict) -> dict:
    """Build a request-only router view: decrypt cloud keys in memory, never expose local routes to the server."""
    from kira import routes as route_model

    settings = json.loads(json.dumps(stored))
    settings.setdefault("providers", {})
    secret_rows = db.scalars(select(ProviderCredential).where(ProviderCredential.account_id == account_id)).all()
    for row in secret_rows:
        try:
            data = json.loads(_fernet().decrypt(row.ciphertext.encode("ascii")).decode("utf-8"))
        except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=503, detail=f"Provider credential for {row.provider_id} cannot be decrypted.") from exc
        provider = settings["providers"].setdefault(row.provider_id, {})
        provider["api_key"] = data.get("api_key", "")
        if data.get("account_id"):
            provider["account_id"] = data["account_id"]
    routes = settings.get("routes") if isinstance(settings.get("routes"), list) else []
    enabled_routes = []
    for route in routes:
        if not isinstance(route, dict):
            continue
        provider_id = str(route.get("provider") or "")
        provider = settings["providers"].get(provider_id) or {}
        if route_model.provider_kind(provider_id, provider) != "cloud":
            continue
        if not provider.get("enabled", True) or not provider.get("api_key") or not route.get("model"):
            continue
        enabled_routes.append(route)
    settings["routes"] = enabled_routes
    return settings


def _core_chat_sync(db: Session, account: Account, payload: ChatRequest):
    if payload.attachment_ids:
        raise HTTPException(status_code=501, detail="Attachment storage is not enabled on this Core deployment yet.")
    conversation = db.get(Conversation, payload.conversation_id)
    if conversation is None or conversation.account_id != account.id:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    if conversation.character_id != payload.character_id:
        raise HTTPException(status_code=409, detail="Character does not match this conversation.")
    state = _account_settings(db, account.id)
    settings = _server_router_settings(db, account.id, state.settings)
    if not settings.get("routes"):
        raise HTTPException(status_code=409, detail="No Cloud Route with a configured provider credential is available.")
    from kira.hybrid_ai import HybridRouter
    from kira.personality import build_system_prompt

    history = db.scalars(select(Message).where(
        Message.account_id == account.id,
        Message.conversation_id == conversation.id
    ).order_by(Message.created_at.desc()).limit(30)).all()
    messages = [{"role": row.role, "content": row.content} for row in reversed(history)]
    messages.append({"role": "user", "content": payload.content})
    memory_block = _memory_block(db, account.id, payload.character_id)
    profile = _profile_for(payload.character_id, settings)
    system_prompt = build_system_prompt(settings, memory_block=memory_block, character_profile=profile)
    router = HybridRouter(settings)
    # Server-side usage telemetry is account-scoped elsewhere; never append shared-user requests
    # to the desktop's machine-local usage ledger or provider log.
    router._ledger = lambda *args, **kwargs: None
    router._write_telemetry = lambda *args, **kwargs: None
    answer = router.chat(messages, system_prompt, float(settings.get("temperature", 0.7)))
    route = {"provider": router.last_provider, "model": router.last_model, "route_id": router.last_route_id}
    user_message = Message(account_id=account.id, conversation_id=conversation.id, role="user", content=payload.content)
    assistant_message = Message(account_id=account.id, conversation_id=conversation.id, role="assistant", content=answer, route=route)
    conversation.updated_at = utcnow()
    if not conversation.title or conversation.title == conversation.character_id.title():
        conversation.title = payload.content.strip().splitlines()[0][:80]
    db.add(user_message)
    db.add(assistant_message)
    db.commit()
    return {
        "user_message_id": user_message.id,
        "assistant_message_id": assistant_message.id,
        "conversation_id": conversation.id,
        "character_id": conversation.character_id,
        "content": answer,
        "route": route,
        "created_at": assistant_message.created_at.isoformat(),
    }


@app.post("/v1/chat/messages")
async def send_chat_message(payload: ChatRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    return await run_in_threadpool(_core_chat_sync, db, account, payload)


@app.get("/v1/memory/{character_id}")
def get_memory(character_id: str, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    row = db.scalar(select(CharacterMemory).where(
        CharacterMemory.account_id == account.id, CharacterMemory.character_id == character_id))
    return {"character_id": character_id, "revision": row.revision if row else 0, "items": row.items if row else []}


@app.put("/v1/memory/{character_id}")
def put_memory(character_id: str, payload: MemoryRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    row = db.scalar(select(CharacterMemory).where(
        CharacterMemory.account_id == account.id, CharacterMemory.character_id == character_id))
    if row is None:
        if payload.revision != 0:
            raise HTTPException(status_code=409, detail={"message": "Memory revision conflict.", "current_revision": 0})
        row = CharacterMemory(account_id=account.id, character_id=character_id, revision=0, items=[])
        db.add(row)
        db.flush()
    if row.revision != payload.revision:
        raise HTTPException(status_code=409, detail={"message": "Memory revision conflict.", "current_revision": row.revision})
    row.items = payload.items
    row.revision += 1
    row.updated_at = utcnow()
    db.commit()
    return {"revision": row.revision, "updated_at": row.updated_at.isoformat()}


@app.post("/v1/devices", status_code=201)
def register_device(payload: DeviceRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    try:
        uuid.UUID(payload.device_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="device_id must be a UUID.") from exc
    if payload.platform not in ("windows", "android"):
        raise HTTPException(status_code=422, detail="Unsupported device platform.")
    row = db.scalar(select(Device).where(Device.account_id == account.id, Device.device_id == payload.device_id))
    if row is None:
        row = Device(account_id=account.id, device_id=payload.device_id, platform=payload.platform)
        db.add(row)
    row.device_name = payload.device_name
    row.app_version = payload.app_version
    row.local_capabilities = payload.local_capabilities
    row.last_seen_at = utcnow()
    db.commit()
    return {"device_id": row.device_id, "platform": row.platform, "last_seen_at": row.last_seen_at.isoformat()}


@app.get("/v1/devices")
def list_devices(account: Account = Depends(current_account), db: Session = Depends(get_db)):
    rows = db.scalars(select(Device).where(Device.account_id == account.id).order_by(Device.last_seen_at.desc())).all()
    return {"items": [
        {"device_id": row.device_id, "platform": row.platform, "device_name": row.device_name,
         "app_version": row.app_version, "last_seen_at": row.last_seen_at.isoformat()}
        for row in rows
    ]}


@app.get("/v1/sync/snapshot")
def sync_snapshot(account: Account = Depends(current_account), db: Session = Depends(get_db)):
    """Return all account-scoped data needed to restore a second client. Provider secrets are never included."""
    state = _account_settings(db, account.id)
    conversations = db.scalars(select(Conversation).where(
        Conversation.account_id == account.id).order_by(Conversation.updated_at.desc())).all()
    message_rows = db.scalars(select(Message).where(
        Message.account_id == account.id).order_by(Message.created_at.asc())).all()
    messages_by_conversation: dict[str, list[dict]] = {}
    for message in message_rows:
        messages_by_conversation.setdefault(message.conversation_id, []).append({
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "route": message.route,
            "created_at": message.created_at.isoformat(),
        })
    memory_rows = db.scalars(select(CharacterMemory).where(CharacterMemory.account_id == account.id)).all()
    return {
        "account_id": account.id,
        "settings_revision": state.revision,
        "settings": state.settings,
        "conversations": [
            {"id": c.id, "character_id": c.character_id, "title": c.title,
             "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
             "messages": messages_by_conversation.get(c.id, [])}
            for c in conversations
        ],
        "memory": [
            {"character_id": m.character_id, "revision": m.revision, "items": m.items}
            for m in memory_rows
        ],
        "provider_credentials": [
            {"provider_id": x.provider_id, "configured": True} for x in
            db.scalars(select(ProviderCredential).where(ProviderCredential.account_id == account.id)).all()
        ],
    }


@app.post("/v1/sync/import")
def sync_import(payload: ImportRequest, account: Account = Depends(current_account), db: Session = Depends(get_db)):
    """Idempotently import one explicit user-approved desktop backup into the account."""
    try:
        uuid.UUID(payload.import_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="import_id must be a UUID.") from exc
    existing = db.scalar(select(ImportBatch).where(
        ImportBatch.account_id == account.id, ImportBatch.import_id == payload.import_id))
    if existing:
        return {"import_id": payload.import_id, "status": "already_imported"}
    shared = payload.shared_data
    settings = shared.get("settings")
    if isinstance(settings, dict):
        state = _account_settings(db, account.id)
        if state.revision != 0:
            raise HTTPException(status_code=409, detail="Account already contains settings; import conflict needs user review.")
        state.settings = _safe_settings(settings)
        state.revision = 1
        state.updated_at = utcnow()

    memories = shared.get("memory")
    if isinstance(memories, list):
        for item in memories:
            if not isinstance(item, dict) or not item.get("character_id") or not isinstance(item.get("items"), list):
                continue
            character_id = str(item["character_id"])[:80]
            row = db.scalar(select(CharacterMemory).where(
                CharacterMemory.account_id == account.id, CharacterMemory.character_id == character_id))
            if row is None:
                db.add(CharacterMemory(account_id=account.id, character_id=character_id,
                                       revision=1, items=item["items"][:5000]))

    def imported_time(value):
        if not value:
            return utcnow()
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        except (TypeError, ValueError):
            return utcnow()

    conversation_id_map = {}
    conversations = shared.get("conversations")
    if isinstance(conversations, list):
        for item in conversations:
            if not isinstance(item, dict):
                continue
            character_id = str(item.get("character_id") or "kira")[:80]
            local_id = str(item.get("id") or item.get("local_id") or "")
            requested_id = local_id
            try:
                uuid.UUID(requested_id)
                collision = db.get(Conversation, requested_id)
                conversation_id = requested_id if collision is None else str(uuid.uuid4())
            except (ValueError, AttributeError):
                conversation_id = str(uuid.uuid4())
            conversation = Conversation(
                id=conversation_id,
                account_id=account.id,
                character_id=character_id,
                title=str(item.get("title") or character_id.title())[:200],
                created_at=imported_time(item.get("created_at")),
                updated_at=imported_time(item.get("updated_at")),
            )
            db.add(conversation)
            if local_id:
                conversation_id_map[local_id] = conversation_id
            messages = item.get("messages")
            if isinstance(messages, list):
                for message in messages:
                    if not isinstance(message, dict):
                        continue
                    role = str(message.get("role") or "").lower()
                    message_text = str(message.get("content") or "")
                    if role not in ("user", "assistant") or not message_text:
                        continue
                    db.add(Message(
                        account_id=account.id,
                        conversation_id=conversation_id,
                        role=role,
                        content=message_text[:100000],
                        route=message.get("route") if isinstance(message.get("route"), dict) else None,
                        created_at=imported_time(message.get("created_at")),
                    ))

    credentials = payload.provider_credentials or {}
    for provider_id, value in credentials.items():
        if not isinstance(value, dict) or not value.get("api_key"):
            continue
        # Each secret import is a separate opt-in and is encrypted before the database write.
        provider_id = str(provider_id)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", provider_id):
            continue
        encrypted = _fernet().encrypt(json.dumps({
            "api_key": str(value["api_key"]),
            "account_id": value.get("account_id"),
        }, separators=(",", ":")).encode()).decode("ascii")
        row = db.scalar(select(ProviderCredential).where(
            ProviderCredential.account_id == account.id, ProviderCredential.provider_id == provider_id))
        if row is None:
            db.add(ProviderCredential(account_id=account.id, provider_id=provider_id, ciphertext=encrypted))
        else:
            row.ciphertext = encrypted
            row.updated_at = utcnow()
    db.add(ImportBatch(account_id=account.id, import_id=payload.import_id))
    db.commit()
    return {
        "import_id": payload.import_id,
        "status": "imported",
        "imported_conversations": len(conversation_id_map),
        "conversation_id_map": conversation_id_map,
        "source_data_deleted": False,
    }
