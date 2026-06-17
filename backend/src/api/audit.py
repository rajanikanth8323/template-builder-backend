# src/api/audit.py
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()
logger = logging.getLogger(__name__)


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


@router.get("/audit/events", response_model=list)
async def list_audit_events(
    request: Request,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 100,
) -> list:
    """List all audit events, newest first."""
    engine = get_engine(request)

    sql = """
        SELECT
            event_id,
            entity_type,
            entity_id,
            action,
            actor,
            summary,
            details_json,
            created_at
        FROM template_builder.audit_events
        WHERE 1=1
    """
    params: Dict[str, Any] = {"limit": limit}

    if entity_type:
        sql += " AND entity_type = :entity_type"
        params["entity_type"] = entity_type

    if action:
        sql += " AND action = :action"
        params["action"] = action

    if actor:
        sql += " AND actor = :actor"
        params["actor"] = actor

    sql += " ORDER BY created_at DESC LIMIT :limit"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()
        return [
            {
                "event_id": str(r[0]),
                "entity_type": r[1],
                "entity_id": str(r[2]),
                "action": r[3],
                "actor": r[4],
                "summary": r[5],
                "details_json": r[6] if isinstance(r[6], dict) else {},
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]