import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.ml_model.ml_model import MockLLM
from app.routers.router import router

logger = logging.getLogger(__name__)

ml_model_state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    ml_model_state["ml_model"] = MockLLM()
    logger.info("Server is ready to accept connections.")
    yield
    ml_model_state.clear()
    logger.info("Memory is successfully freed.")


app = FastAPI(title="DEMO API", lifespan=lifespan)
app.include_router(router)


class ContextLengthExceeded(Exception):
    pass


@app.exception_handler(ContextLengthExceeded)
async def context_length_handler(request: Request, exc: ContextLengthExceeded):
    logger.error("LLM context overflow")

    return JSONResponse(
        status_code=400,
        content={"error": "Input message is greater than 5000 symbols."},
    )
