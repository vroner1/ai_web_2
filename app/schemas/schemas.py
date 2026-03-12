from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    message: str
    role: Literal["system", "user", "assistant"]


class ChatRequest(BaseModel):
    messages: list[Message]
    temperature: float = Field(default=0.8, le=2.0, ge=0.0)
    max_tokens: int = Field(default=100, le=10000, ge=10)

    @field_validator("messages")
    @classmethod
    def check_messages(cls, v):
        if not v:
            raise ValueError("Messages should not be empty.")
        if v[-1].role != "user":
            raise ValueError(
                "User message is required to be the last message in chat sequence."
            )
        return v
