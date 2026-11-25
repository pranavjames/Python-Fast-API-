from typing import Literal

from pydantic import BaseModel, Field


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Access token lifetime in seconds")


class RefreshTokenRequest(BaseModel):
    refresh_token: str = Field(min_length=1)
