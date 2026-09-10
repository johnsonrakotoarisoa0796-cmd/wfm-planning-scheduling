"""Schémas Pydantic pour l'authentification."""

from pydantic import BaseModel, EmailStr, Field


class LoginForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class TOTPVerifyForm(BaseModel):
    code: str = Field(min_length=6, max_length=6)


class CurrentUserRead(BaseModel):
    id: int
    email: str
    role: str
