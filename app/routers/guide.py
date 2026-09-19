"""Mode d'emploi intégré de la plateforme WFM."""
from fastapi import APIRouter, Depends, Request
from app.core.security import require_login
from app.core.templating import templates
from app.models.user import User

router = APIRouter(prefix="/guide", tags=["guide"])


@router.get("")
def guide(request: Request, current_user: User = Depends(require_login)):
    return templates.TemplateResponse(
        request,
        "guide/index.html",
        {"active_nav": "guide", "current_user": current_user},
    )
