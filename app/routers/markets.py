"""Gestion des marchés opérationnels."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlmodel import Session, select

from app.core.database import get_session
from app.core.security import require_login, require_role, verify_csrf
from app.core.templating import templates
from app.core.time_utils import utc_now
from app.models.market import Market
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.market import MarketInput
from app.services.workforce_service import validate_timezone_name

router = APIRouter(prefix="/markets", tags=["markets"])
WRITE_ROLES = (UserRole.ADMIN, UserRole.WFM_ANALYST)


@router.get("")
def list_markets(
    request: Request,
    current_user: User = Depends(require_login),
    session: Session = Depends(get_session),
):
    markets = list(session.exec(select(Market).order_by(Market.code)).all())
    return templates.TemplateResponse(
        request,
        "markets/index.html",
        {
            "active_nav": "markets",
            "current_user": current_user,
            "markets": markets,
            "errors": [],
            "can_edit": current_user.role in WRITE_ROLES,
        },
    )


@router.post("/new", dependencies=[Depends(verify_csrf)])
def create_market(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    language_code: str = Form(...),
    timezone_name: str = Form(...),
    current_user: User = Depends(require_role(*WRITE_ROLES)),
    session: Session = Depends(get_session),
):
    errors = []
    try:
        payload = MarketInput(
            code=code.strip().upper(),
            name=name.strip(),
            language_code=language_code.strip().lower(),
            timezone_name=timezone_name.strip(),
        )
        validate_timezone_name(payload.timezone_name)
        if session.exec(select(Market).where(Market.code == payload.code)).first() is not None:
            raise ValueError(f"Le marché {payload.code} existe déjà.")
        session.add(
            Market(
                code=payload.code,
                name=payload.name,
                language_code=payload.language_code,
                timezone_name=payload.timezone_name,
                is_active=True,
            )
        )
        session.commit()
    except (ValidationError, ValueError) as exc:
        errors = [str(item["msg"]) for item in exc.errors()] if isinstance(exc, ValidationError) else [str(exc)]

    if errors:
        markets = list(session.exec(select(Market).order_by(Market.code)).all())
        return templates.TemplateResponse(
            request,
            "markets/index.html",
            {
                "active_nav": "markets",
                "current_user": current_user,
                "markets": markets,
                "errors": errors,
                "can_edit": True,
            },
            status_code=400,
        )
    return RedirectResponse(url="/markets", status_code=303)
