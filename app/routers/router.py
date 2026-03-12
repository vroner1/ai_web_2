import logging

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import app.main as main_app
from app.ml_model.ml_model import MockLLM
from app.schemas.schemas import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter()
security = HTTPBearer()

VALID_API_KEYS = {"secret-key"}


def verify_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    if credentials.credentials not in VALID_API_KEYS:
        raise HTTPException(status_code=401, detail="Not valid auth key.")
    return credentials.credentials


def get_llm() -> MockLLM:
    return main_app.ml_model_state["ml_model"]


@router.post("/chat")
async def chat(
    request: ChatRequest,
    model: MockLLM = Depends(get_llm),
    api_key: str = Depends(verify_key),
):
    user_prompt = request.messages[-1].message

    if len(user_prompt) > 5000:
        raise main_app.ContextLengthExceeded()

    response_text = await model.generate(
        prompt=user_prompt,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )
    return {"response": response_text}


@router.post("/chat/stream")
async def chat_streaming(
    request: ChatRequest,
    model: MockLLM = Depends(get_llm),
    api_key: str = Depends(verify_key),
):
    user_prompt = request.messages[-1].message

    if len(user_prompt) > 5000:
        raise main_app.ContextLengthExceeded()

    return StreamingResponse(
        model.generate_stream(
            prompt=user_prompt,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
    )


@router.get("/health")
async def health():
    if "ml_model" in main_app.ml_model_state:
        return {"status": "ok"}
