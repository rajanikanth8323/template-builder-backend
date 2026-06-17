# --------------------------------------------------------------
# src/api/placeholders.py – Global Placeholder Registry
# --------------------------------------------------------------
import json
import logging
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection, create_async_engine

# --------------------------------------------------------------
# Router & logger
# --------------------------------------------------------------
router = APIRouter()
logger = logging.getLogger(__name__)


# --------------------------------------------------------------
# Pydantic models
# --------------------------------------------------------------
class PlaceholderCreateRequest(BaseModel):
    name: str
    generation_mode: str = Field(..., description="manual_sql or llm_prompt")
    prompt: Optional[str] = None
    sql_text: Optional[str] = None
    datasource_id: int
    value_type: str = "string"
    cardinality: str = "scalar"
    format_json: Optional[Dict[str, Any]] = {}
    sample_value: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}
    is_active: bool = True
    created_by: str

    @validator("sql_text", always=True)
    def _check_sql(cls, v, values):
        if values.get("generation_mode") == "manual_sql" and not v:
            raise ValueError("sql_text required for manual_sql")
        return v

    @validator("prompt", always=True)
    def _check_prompt(cls, v, values):
        if values.get("generation_mode") == "llm_prompt" and not v:
            raise ValueError("prompt required for llm_prompt")
        return v


class PlaceholderResponse(BaseModel):
    registry_id: str
    name: str
    generation_mode: str
    prompt: Optional[str]
    sql_text: Optional[str]
    datasource_id: int
    value_type: str
    cardinality: str
    format_json: Optional[Dict[str, Any]]
    sample_value: Optional[str]
    metadata: Optional[Dict[str, Any]]
    is_active: bool
    created_by: str
    created_at: Optional[str]


# --------------------------------------------------------------
# DB engine dependency
# --------------------------------------------------------------
def get_engine(request: Request) -> AsyncEngine:
    engine: Optional[AsyncEngine] = getattr(request.app.state, "engine", None)
    if engine is not None:
        return engine
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/template_builder",
    )
    engine = create_async_engine(db_url, future=True, echo=False)
    request.app.state.engine = engine
    return engine


async def get_current_actor() -> str:
    return "system"


# --------------------------------------------------------------
# Helper utilities
# --------------------------------------------------------------
def _to_str(v: Any) -> Optional[str]:
    return str(v) if v is not None else None


def _as_json(v: Any) -> Dict[str, Any]:
    if not v:
        return {}
    if isinstance(v, (str, bytes, bytearray)):
        try:
            return json.loads(v)
        except json.JSONDecodeError as exc:
            logger.warning("JSON decode failed for %r: %s", v, exc)
            return {}
    return v


async def _ensure_uuid_ossp(conn: AsyncConnection) -> None:
    await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))


async def _insert_audit_event(
    conn: AsyncConnection,
    *,
    entity_type: str,
    entity_id: str,
    action: str,
    actor: str,
    summary: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    sql = text("""
        INSERT INTO template_builder.audit_events (
            event_id, entity_type, entity_id, action, actor, summary, details_json, created_at
        ) VALUES (
            uuid_generate_v4(), :etype, :eid, :act, :actor, :summary, :details, NOW()
        )
    """)
    await conn.execute(sql, {
        "etype": entity_type,
        "eid": entity_id,
        "act": action,
        "actor": actor,
        "summary": summary,
        "details": json.dumps(details or {}),
    })


# --------------------------------------------------------------
# CREATE placeholder
# --------------------------------------------------------------
@router.post(
    "/registry/placeholders",
    status_code=status.HTTP_201_CREATED,
    response_model=PlaceholderResponse,
    summary="Create a new global placeholder (idempotent on name)",
)
async def create_placeholder(
    req: PlaceholderCreateRequest,
    request: Request,
    engine: AsyncEngine = Depends(get_engine),
    actor: str = Depends(get_current_actor),
) -> PlaceholderResponse:
    sql_insert = """
        INSERT INTO template_builder.placeholders_registry (
            registry_id, name, description, generation_mode, prompt, sql_text,
            datasource_id, value_type, cardinality, classification, format_json,
            sample_value, metadata, created_by, created_at, updated_at, is_active
        ) VALUES (
            uuid_generate_v4(), :name, NULL, :generation_mode, :prompt, :sql_text,
            :datasource_id, :value_type, :cardinality, 'internal', :format_json,
            :sample_value, :metadata, :created_by, NOW(), NOW(), :is_active
        )
        RETURNING
            registry_id, name, generation_mode, prompt, sql_text, datasource_id,
            value_type, cardinality, format_json, sample_value, metadata,
            is_active, created_by, created_at
    """
    try:
        async with engine.begin() as conn:
            await _ensure_uuid_ossp(conn)
            result = await conn.execute(text(sql_insert), {
                "name": req.name,
                "generation_mode": req.generation_mode,
                "prompt": req.prompt,
                "sql_text": req.sql_text,
                "datasource_id": req.datasource_id,
                "value_type": req.value_type,
                "cardinality": req.cardinality,
                "format_json": json.dumps(req.format_json or {}),
                "sample_value": req.sample_value,
                "metadata": json.dumps(req.metadata or {}),
                "is_active": req.is_active,
                "created_by": req.created_by,
            })
            row = result.mappings().first()
            if not row:
                raise HTTPException(status_code=500, detail="Failed to insert placeholder")

        async with engine.begin() as conn:
            await _insert_audit_event(
                conn,
                entity_type="placeholders_registry",
                entity_id=_to_str(row["registry_id"]),
                action="create",
                actor=actor,
                summary=f"Placeholder '{req.name}' created",
                details={"name": req.name, "generation_mode": req.generation_mode},
            )

        return PlaceholderResponse(
            registry_id=_to_str(row["registry_id"]),
            name=row["name"],
            generation_mode=row["generation_mode"],
            prompt=row["prompt"],
            sql_text=row["sql_text"],
            datasource_id=row["datasource_id"],
            value_type=row["value_type"],
            cardinality=row["cardinality"],
            format_json=_as_json(row["format_json"]),
            sample_value=row["sample_value"],
            metadata=_as_json(row["metadata"]),
            is_active=row["is_active"],
            created_by=row["created_by"],
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )

    except IntegrityError as exc:
        pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
        if pgcode == "23505":
            logger.info("Placeholder '%s' already exists – returning existing record", req.name)
            async with engine.begin() as conn:
                sel_sql = """
                    SELECT registry_id, name, generation_mode, prompt, sql_text,
                           datasource_id, value_type, cardinality, format_json,
                           sample_value, metadata, is_active, created_by, created_at
                    FROM template_builder.placeholders_registry
                    WHERE name = :name
                """
                result = await conn.execute(text(sel_sql), {"name": req.name})
                row = result.mappings().first()
                if not row:
                    raise HTTPException(status_code=500, detail="DB inconsistency")

                await _insert_audit_event(
                    conn,
                    entity_type="placeholders_registry",
                    entity_id=_to_str(row["registry_id"]),
                    action="create_duplicate",
                    actor=actor,
                    summary=f"Placeholder '{req.name}' already exists",
                    details={"existing_id": _to_str(row["registry_id"])},
                )

                return PlaceholderResponse(
                    registry_id=_to_str(row["registry_id"]),
                    name=row["name"],
                    generation_mode=row["generation_mode"],
                    prompt=row["prompt"],
                    sql_text=row["sql_text"],
                    datasource_id=row["datasource_id"],
                    value_type=row["value_type"],
                    cardinality=row["cardinality"],
                    format_json=_as_json(row["format_json"]),
                    sample_value=row["sample_value"],
                    metadata=_as_json(row["metadata"]),
                    is_active=row["is_active"],
                    created_by=row["created_by"],
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                )

        logger.error("CREATE placeholder failed: %r", exc)
        raise HTTPException(status_code=500, detail=f"Database error: {repr(exc)}") from exc


# --------------------------------------------------------------
# LIST all placeholders
# --------------------------------------------------------------
@router.get(
    "/registry/placeholders",
    response_model=list,
    summary="List all placeholders",
)
async def list_placeholders(
    request: Request,
    name: Optional[str] = None,
) -> list:
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = get_engine(request)

    sql = """
        SELECT registry_id, name, generation_mode, prompt, sql_text,
               datasource_id, value_type, cardinality, format_json,
               sample_value, metadata, is_active, created_by, created_at
        FROM template_builder.placeholders_registry
        WHERE 1=1
    """
    params: Dict[str, Any] = {}
    if name:
        sql += " AND name ILIKE :name"
        params["name"] = f"%{name}%"
    sql += " ORDER BY created_at DESC"

    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.mappings().all()

    output = []
    for row in rows:
        output.append({
            "registry_id": _to_str(row["registry_id"]),
            "name": row["name"],
            "generation_mode": row["generation_mode"],
            "prompt": row["prompt"],
            "sql_text": row["sql_text"],
            "datasource_id": row["datasource_id"],
            "value_type": row["value_type"],
            "cardinality": row["cardinality"],
            "format_json": _as_json(row["format_json"]),
            "sample_value": row["sample_value"],
            "metadata": _as_json(row["metadata"]),
            "is_active": row["is_active"],
            "created_by": row["created_by"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        })
    return output


# --------------------------------------------------------------
# READ single placeholder
# --------------------------------------------------------------
@router.get(
    "/registry/placeholders/{registry_id}",
    response_model=PlaceholderResponse,
    summary="Get a placeholder by its registry_id",
)
async def get_placeholder_by_id(
    registry_id: str,
    request: Request,
) -> PlaceholderResponse:
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = get_engine(request)

    sql = """
        SELECT registry_id, name, generation_mode, prompt, sql_text,
               datasource_id, value_type, cardinality, format_json,
               sample_value, metadata, is_active, created_by, created_at
        FROM template_builder.placeholders_registry
        WHERE registry_id = :registry_id
    """

    async with engine.begin() as conn:
        result = await conn.execute(text(sql), {"registry_id": registry_id})
        row = result.mappings().first()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Placeholder not found")

        await _insert_audit_event(
            conn,
            entity_type="placeholders_registry",
            entity_id=registry_id,
            action="update",
            actor="dev_user",
            summary=f"Placeholder '{req.name}' updated",
            details={"name": req.name, "generation_mode": req.generation_mode},
        )

        return PlaceholderResponse(
            registry_id=_to_str(row["registry_id"]),
            name=row["name"],
            generation_mode=row["generation_mode"],
            prompt=row["prompt"],
            sql_text=row["sql_text"],
            datasource_id=row["datasource_id"],
            value_type=row["value_type"],
            cardinality=row["cardinality"],
            format_json=_as_json(row["format_json"]),
            sample_value=row["sample_value"],
            metadata=_as_json(row["metadata"]),
            is_active=row["is_active"],
            created_by=row["created_by"],
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )

@router.put(
    "/registry/placeholders/{registry_id}",
    response_model=PlaceholderResponse,
    summary="Update a placeholder",
)
async def update_placeholder(
    registry_id: str,
    req: PlaceholderCreateRequest,
    request: Request,
) -> PlaceholderResponse:
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = get_engine(request)

    sql = """
        UPDATE template_builder.placeholders_registry
        SET name = :name,
            generation_mode = :generation_mode,
            prompt = :prompt,
            sql_text = :sql_text,
            sample_value = :sample_value,
            value_type = :value_type,
            cardinality = :cardinality,
            updated_at = NOW()
        WHERE registry_id = :registry_id
        RETURNING
            registry_id, name, generation_mode, prompt, sql_text,
            datasource_id, value_type, cardinality, format_json,
            sample_value, metadata, is_active, created_by, created_at
    """
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), {
            "registry_id": registry_id,
            "name": req.name,
            "generation_mode": req.generation_mode,
            "prompt": req.prompt,
            "sql_text": req.sql_text,
            "sample_value": req.sample_value,
            "value_type": req.value_type,
            "cardinality": req.cardinality,
        })
        row = result.mappings().first()
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Placeholder not found")

        await _insert_audit_event(
            conn,
            entity_type="placeholders_registry",
            entity_id=registry_id,
            action="update",
            actor="dev_user",
            summary=f"Placeholder '{req.name}' updated",
            details={"name": req.name, "generation_mode": req.generation_mode},
        )

        return PlaceholderResponse(
            registry_id=_to_str(row["registry_id"]),
            name=row["name"],
            generation_mode=row["generation_mode"],
            prompt=row["prompt"],
            sql_text=row["sql_text"],
            datasource_id=row["datasource_id"],
            value_type=row["value_type"],
            cardinality=row["cardinality"],
            format_json=_as_json(row["format_json"]),
            sample_value=row["sample_value"],
            metadata=_as_json(row["metadata"]),
            is_active=row["is_active"],
            created_by=row["created_by"],
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )
# --------------------------------------------------------------
# DELETE placeholder
# --------------------------------------------------------------
@router.delete(
    "/registry/placeholders/{registry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a placeholder by registry_id",
)
async def delete_placeholder(
    registry_id: str,
    request: Request,
) -> None:
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        engine = get_engine(request)

    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM template_builder.placeholders_registry WHERE registry_id = :rid"),
            {"rid": registry_id}
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Placeholder not found")
        await _insert_audit_event(
            conn,
            entity_type="placeholders_registry",
            entity_id=registry_id,
            action="delete",
            actor="dev_user",
            summary=f"Placeholder deleted",
            details={"registry_id": registry_id},
        )