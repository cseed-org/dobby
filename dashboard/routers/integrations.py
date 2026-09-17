"""Dobby's service accounts.

One Composio entity (COMPOSIO_ENTITY_ID) owns the Google Calendar, Notion, Instagram and
LinkedIn connections the bot acts through. Nobody links a personal account here, so every route
is admin-only and the table holds one row per provider.
"""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin
from ..database import get_db
from ..models import Integration, User
from ..schemas import IntegrationOut

logger = logging.getLogger(__name__)
router = APIRouter()

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:3000")
COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
# Must match the bot's COMPOSIO_ENTITY_ID so tool calls find these connections.
ENTITY_ID = os.environ.get("COMPOSIO_ENTITY_ID", "dobby")

# Supported providers mapped to Composio App enum values. Mirrors bot/integrations/*: one folder each.
SUPPORTED_PROVIDERS = {"google_calendar", "notion", "instagram", "linkedin"}


def _get_composio_app(provider: str):
    """Return the Composio App enum for a given provider string."""
    from composio import App  # import at call time so app still loads without composio

    mapping = {
        "google_calendar": App.GOOGLECALENDAR,
        "notion": App.NOTION,
        "instagram": App.INSTAGRAM,
        "linkedin": App.LINKEDIN,
    }
    app = mapping.get(provider)
    if app is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider '{provider}'. Supported: {sorted(SUPPORTED_PROVIDERS)}",
        )
    return app


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[IntegrationOut])
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """List the providers Dobby's service entity is connected to."""
    try:
        result = await db.execute(
            select(Integration).order_by(Integration.connected_at.desc())
        )
        integrations = result.scalars().all()
    except Exception:
        logger.exception("Failed to list integrations")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    return [IntegrationOut.model_validate(i) for i in integrations]


@router.get("/{provider}/connect")
async def connect_integration(
    provider: str,
    request: Request,
    _admin: User = Depends(require_admin),
):
    """Initiate Composio OAuth flow for the given provider under the service entity."""
    if not COMPOSIO_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Composio is not configured",
        )

    composio_app = _get_composio_app(provider)

    try:
        from composio import ComposioToolSet

        toolset = ComposioToolSet(api_key=COMPOSIO_API_KEY)
        entity = toolset.get_entity(entity_id=ENTITY_ID)
        # After the provider's OAuth screen, Composio sends the browser back here so the
        # connection is recorded; without redirect_url it would stop on Composio's own page.
        connection_req = entity.initiate_connection(
            app_name=composio_app,
            redirect_url=str(request.url_for("integration_callback", provider=provider)),
        )
        redirect_url = connection_req.redirectUrl
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to initiate Composio connection for entity %s provider %s",
            ENTITY_ID,
            provider,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach Composio",
        )

    return RedirectResponse(url=redirect_url)


@router.get("/{provider}/callback", name="integration_callback")
async def integration_callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Handle Composio OAuth callback — record the provider as connected."""
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported provider '{provider}'",
        )

    try:
        result = await db.execute(
            select(Integration).where(Integration.provider == provider)
        )
        integration = result.scalar_one_or_none()

        async with db.begin():
            if integration is None:
                integration = Integration(
                    provider=provider,
                    composio_entity_id=ENTITY_ID,
                    connected_by=admin.id,
                )
            else:
                integration.composio_entity_id = ENTITY_ID
                integration.connected_by = admin.id
            db.add(integration)
    except Exception:
        logger.exception("Failed to store integration for provider %s", provider)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")

    return RedirectResponse(url=f"{DASHBOARD_URL}/dashboard/integrations")


@router.delete("/{provider}", status_code=204)
async def disconnect_integration(
    provider: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Forget a provider connection for the service entity."""
    try:
        result = await db.execute(
            select(Integration).where(Integration.provider == provider)
        )
        integration = result.scalar_one_or_none()
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No '{provider}' integration found",
            )
        async with db.begin():
            await db.delete(integration)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to delete integration for provider %s", provider)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")
