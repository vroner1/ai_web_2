from __future__ import annotations

import logging
import secrets
from typing import Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Security,
    status,
)
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import desc, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.database.database import get_db
from app.ml_model.base import BaseLLM
from app.models.models import (
    APIKey,
    ChatHistory,
    ChatSession,
    DEFAULT_CHAT_SESSION_TITLE,
    User,
)
from app.schemas.schemas import (
    APIKeyCreatedResponse,
    APIKeyCreateRequest,
    APIKeyResponse,
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreateRequest,
    ChatSessionResponse,
    HealthResponse,
    UserCreateRequest,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()
api_key_header = APIKeyHeader(name=settings.API_KEY_HEADER_NAME, auto_error=False)
bearer_security = HTTPBearer(auto_error=False)


def get_llm(request: Request) -> BaseLLM:
    return request.app.state.ml_model


def raise_provider_http_error(exc: Exception) -> None:
    provider_status_code = getattr(exc, "status_code", None)
    provider_payload = getattr(exc, "payload", None)

    status_code = (
        provider_status_code
        if provider_status_code in {429, 503}
        else status.HTTP_502_BAD_GATEWAY
    )

    detail: dict[str, object] = {"message": str(exc)}
    if provider_status_code is not None:
        detail["provider_status_code"] = provider_status_code
    if provider_payload is not None:
        detail["provider_payload"] = provider_payload

    raise HTTPException(
        status_code=status_code,
        detail=detail,
    ) from exc


async def get_current_api_key(
    db: AsyncSession = Depends(get_db),
    header_api_key: Optional[str] = Security(api_key_header),
    bearer_credentials: Optional[HTTPAuthorizationCredentials] = Security(
        bearer_security
    ),
) -> APIKey:
    token = header_api_key
    if token is None and bearer_credentials is not None:
        token = bearer_credentials.credentials

    if token is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Provide `{settings.API_KEY_HEADER_NAME}` header or Bearer token.",
        )

    stmt = (
        select(APIKey).options(selectinload(APIKey.owner)).where(APIKey.token == token)
    )
    api_key = (await db.execute(stmt)).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not valid auth key.",
        )

    return api_key


async def get_user_or_404(
    user_id: UUID,
    db: AsyncSession,
    *,
    with_api_keys: bool = False,
) -> User:
    stmt = select(User).where(User.id == user_id)
    if with_api_keys:
        stmt = stmt.options(selectinload(User.api_keys))

    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User was not found.",
        )
    return user


async def get_chat_session_or_404(
    session_id: int,
    db: AsyncSession,
    *,
    with_history: bool = False,
) -> ChatSession:
    stmt = select(ChatSession).where(ChatSession.id == session_id)
    if with_history:
        stmt = stmt.options(selectinload(ChatSession.chat_history))

    chat_session = (await db.execute(stmt)).scalar_one_or_none()
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session was not found.",
        )
    return chat_session


def ensure_user_access(user_id: UUID, api_key: APIKey) -> None:
    if api_key.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key does not belong to requested user.",
        )


def ensure_session_access(chat_session: ChatSession, user_id: UUID) -> None:
    if chat_session.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chat session does not belong to requested user.",
        )


def schedule_chat_audit(
    chat_id: int,
    user_id: UUID,
    *,
    streamed: bool,
) -> None:
    logger.info(
        "Chat `%s` for user `%s` was stored. Streamed=%s",
        chat_id,
        user_id,
        streamed,
    )


def build_chat_metadata(
    request: ChatRequest,
    model: BaseLLM,
    *,
    streamed: bool,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "provider": model.provider_name,
        "model_name": model.model_name,
        "message_count": request.message_count,
        "streamed": streamed,
        "session_id": request.session_id,
    }
    if extra:
        metadata.update(extra)
    return metadata


def derive_session_title(user_prompt: str) -> str:
    cleaned = user_prompt.strip()
    return cleaned[:120] if cleaned else DEFAULT_CHAT_SESSION_TITLE


@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> HealthResponse:
    await db.execute(text("SELECT 1"))
    return HealthResponse(
        status="ok",
        model_loaded=hasattr(request.app.state, "ml_model"),
        database="ok",
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["users"],
)
async def create_user(
    request: UserCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = User(username=request.username, email=request.email)
    db.add(user)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("User creation failed because of unique constraint: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this username or email already exists.",
        ) from exc

    await db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=UserResponse, tags=["users"])
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> User:
    return await get_user_or_404(user_id, db)


@router.post(
    "/users/{user_id}/api-keys",
    response_model=APIKeyCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["api-keys"],
)
async def create_api_key(
    user_id: UUID,
    request: APIKeyCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    user = await get_user_or_404(user_id, db)
    api_key = APIKey(
        name=request.name,
        token=secrets.token_urlsafe(32),
        owner_id=user.id,
    )
    db.add(api_key)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.warning("API key creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not create API key. Please retry.",
        ) from exc

    await db.refresh(api_key)
    return api_key


@router.get(
    "/users/{user_id}/api-keys",
    response_model=list[APIKeyResponse],
    tags=["api-keys"],
)
async def list_api_keys(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[APIKey]:
    await get_user_or_404(user_id, db)
    stmt = (
        select(APIKey)
        .where(APIKey.owner_id == user_id)
        .order_by(desc(APIKey.created_at))
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get(
    "/users/{user_id}/chat-history",
    response_model=list[ChatHistoryResponse],
    tags=["chat"],
)
async def list_chat_history(
    user_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
) -> list[ChatHistory]:
    ensure_user_access(user_id, api_key)
    stmt = (
        select(ChatHistory)
        .where(ChatHistory.user_id == user_id)
        .order_by(desc(ChatHistory.created_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "/users/{user_id}/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["chat-sessions"],
)
async def create_chat_session(
    user_id: UUID,
    request: ChatSessionCreateRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
) -> ChatSession:
    await get_user_or_404(user_id, db)
    ensure_user_access(user_id, api_key)

    chat_session = ChatSession(user_id=user_id, title=request.title)
    db.add(chat_session)
    await db.commit()
    await db.refresh(chat_session)
    return chat_session


@router.get(
    "/users/{user_id}/sessions",
    response_model=list[ChatSessionResponse],
    tags=["chat-sessions"],
)
async def list_chat_sessions(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
) -> list[ChatSession]:
    ensure_user_access(user_id, api_key)
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(desc(ChatSession.created_at))
    )
    return list((await db.execute(stmt)).scalars().all())


@router.get(
    "/users/{user_id}/sessions/{session_id}",
    response_model=list[ChatHistoryResponse],
    tags=["chat-sessions"],
)
async def get_chat_session_history(
    user_id: UUID,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
) -> list[ChatHistory]:
    ensure_user_access(user_id, api_key)
    chat_session = await get_chat_session_or_404(session_id, db, with_history=True)
    ensure_session_access(chat_session, user_id)
    return list(chat_session.chat_history)


@router.post(
    "/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["chat"],
)
async def chat(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
    model: BaseLLM = Depends(get_llm),
) -> ChatResponse:
    chat_session = await get_chat_session_or_404(request.session_id, db)
    ensure_session_access(chat_session, api_key.owner_id)

    user_prompt = request.messages[-1].message

    if len(user_prompt) > settings.MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Input message is greater than {settings.MAX_PROMPT_LENGTH} symbols.",
        )

    payload_messages = [message.model_dump() for message in request.messages]

    try:
        result = await model.generate(
            messages=payload_messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    except Exception as exc:
        if hasattr(exc, "status_code"):
            raise_provider_http_error(exc)
        raise

    chat_entry = ChatHistory(
        user_id=api_key.owner_id,
        api_key_id=api_key.id,
        session_id=chat_session.id,
        messages=payload_messages,
        user_prompt=user_prompt,
        assistant_prompt=result.text,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        streamed=False,
        response_metadata=build_chat_metadata(
            request,
            model,
            streamed=False,
            extra=result.metadata,
        ),
    )

    if chat_session.title == DEFAULT_CHAT_SESSION_TITLE:
        chat_session.title = derive_session_title(user_prompt)

    db.add(chat_entry)
    await db.commit()
    await db.refresh(chat_entry)

    background_tasks.add_task(
        schedule_chat_audit,
        chat_entry.id,
        api_key.owner_id,
        streamed=False,
    )

    return ChatResponse(
        id=chat_entry.id,
        user_id=api_key.owner_id,
        session_id=chat_session.id,
        response=result.text,
        temperature=chat_entry.temperature,
        max_tokens=chat_entry.max_tokens,
        model_name=result.model_name,
        created_at=chat_entry.created_at,
    )


@router.post("/chat/stream", tags=["chat"])
async def chat_streaming(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    api_key: APIKey = Depends(get_current_api_key),
    model: BaseLLM = Depends(get_llm),
) -> StreamingResponse:
    chat_session = await get_chat_session_or_404(request.session_id, db)
    ensure_session_access(chat_session, api_key.owner_id)

    user_prompt = request.messages[-1].message

    if len(user_prompt) > settings.MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Input message is greater than {settings.MAX_PROMPT_LENGTH} symbols.",
        )

    payload_messages = [message.model_dump() for message in request.messages]

    async def stream_response():
        collected_tokens: list[str] = []
        final_metadata: dict[str, object] = {}

        try:
            async for event in model.generate_stream(
                messages=payload_messages,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            ):
                if event.token:
                    collected_tokens.append(event.token)
                    yield event.token

                if event.done:
                    final_metadata = event.metadata
        except Exception as exc:
            if hasattr(exc, "status_code"):
                logger.exception("Streaming provider error: %s", exc)
                raise_provider_http_error(exc)
            raise

        chat_entry = ChatHistory(
            user_id=api_key.owner_id,
            api_key_id=api_key.id,
            session_id=chat_session.id,
            messages=payload_messages,
            user_prompt=user_prompt,
            assistant_prompt="".join(collected_tokens).strip(),
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            streamed=True,
            response_metadata=build_chat_metadata(
                request,
                model,
                streamed=True,
                extra=final_metadata,
            ),
        )

        if chat_session.title == DEFAULT_CHAT_SESSION_TITLE:
            chat_session.title = derive_session_title(user_prompt)

        db.add(chat_entry)
        await db.commit()
        await db.refresh(chat_entry)
        schedule_chat_audit(chat_entry.id, api_key.owner_id, streamed=True)

    return StreamingResponse(stream_response(), media_type="text/plain")