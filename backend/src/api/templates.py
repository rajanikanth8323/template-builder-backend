# --------------------------------------------------------------
# src/api/templates.py – Template CRUD, Publishing, Binding + Audit
# --------------------------------------------------------------
from fastapi import APIRouter, HTTPException, Request, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
import uuid
import json
import re
from datetime import datetime, date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncConnection
from sqlalchemy.exc import IntegrityError

def to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)

def maybe_isoformat(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value

def as_json(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    return value

class TemplateResponse(BaseModel):
    template_id: str
    name: str
    description: Optional[str]
    status: str
    output_target: str
    layout_json: Dict[str, Any]
    default_locale: str
    supported_locales: List[str]
    industry: Optional[str]
    tags: List[str]
    created_by: str
    created_at: Optional[str]

def row_to_response(row) -> TemplateResponse:
    return TemplateResponse(
        template_id=str(row[0]),
        name=row[1],
        description=row[2],
        status=row[3],
        output_target=row[4],
        layout_json=row[5],
        default_locale=row[6],
        supported_locales=row[7],
        industry=row[8],
        tags=row[9],
        created_by=row[10],
        created_at=row[11].isoformat() if row[11] else None,
    )

class TemplatePublishResponse(BaseModel):
    version_id: str
    template_id: str
    status: str
    created_at: str

class TemplateCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    output_target: str = Field(..., description="html|docx|pdf|xlsx|md")
    layout_json: Dict[str, Any]
    default_locale: str = "en"
    supported_locales: List[str] = Field(default_factory=lambda: ["en"])
    industry: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    created_by: str
    is_prebuilt: bool = False

    @validator("supported_locales", pre=True)
    def coerce_locales(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                raise ValueError("supported_locales must be a JSON array or list")
        return v

    @validator("tags", pre=True)
    def coerce_tags(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                raise ValueError("tags must be a JSON array or list")
        return v

class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    output_target: Optional[str] = None
    layout_json: Optional[Dict[str, Any]] = None
    default_locale: Optional[str] = None
    supported_locales: Optional[List[str]] = None
    industry: Optional[str] = None
    tags: Optional[List[str]] = None

    @validator("supported_locales", pre=True)
    def coerce_locales(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                raise ValueError("supported_locales must be a JSON array or list")
        return v

    @validator("tags", pre=True)
    def coerce_tags(cls, v):
        if v is None:
            return v
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                raise ValueError("tags must be a JSON array or list")
        return v

class PlaceholderBindRequest(BaseModel):
    registry_id: str
    override_sample_value: Optional[str] = None

router = APIRouter()

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
        )
        VALUES (
            uuid_generate_v4(), :etype, CAST(:eid AS uuid), :act, :actor, :summary, :details, NOW()
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

@router.post("/templates", status_code=status.HTTP_201_CREATED, response_model=TemplateResponse)
async def create_template(req: TemplateCreateRequest, request: Request):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    template_id = str(uuid.uuid4())
    sql_insert = """
        INSERT INTO template_builder.templates (
            template_id, name, description, status, output_target, layout_json,
            default_locale, supported_locales, industry, tags, created_by, created_at
        ) VALUES (
            CAST(:template_id AS uuid), :name, :description, 'draft', :output_target,
            CAST(:layout_json AS jsonb), :default_locale, :supported_locales,
            :industry, :tags, :created_by, NOW()
        )
    """
    try:
        async with engine.begin() as conn:
            await conn.execute(text(sql_insert), {
                "template_id": template_id,
                "name": req.name,
                "description": req.description,
                "output_target": req.output_target,
                "layout_json": json.dumps(req.layout_json),
                "default_locale": req.default_locale,
                "supported_locales": req.supported_locales,
                "industry": req.industry,
                "tags": req.tags,
                "created_by": req.created_by,
            })
            if req.is_prebuilt:
                await _insert_audit_event(conn, entity_type="template", entity_id=template_id,
                    action="use_prebuilt", actor=req.created_by,
                    summary=f"Prebuilt template '{req.name}' used",
                    details={"output_target": req.output_target, "industry": req.industry})
            else:
                await _insert_audit_event(conn, entity_type="template", entity_id=template_id,
                    action="create", actor=req.created_by,
                    summary=f"Template '{req.name}' created",
                    details={"output_target": req.output_target, "industry": req.industry})
            result = await conn.execute(
                text("SELECT * FROM template_builder.templates WHERE template_id = :tid"),
                {"tid": template_id})
            row = result.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to read created template")
            return row_to_response(row)
    except IntegrityError as exc:
        if getattr(exc.orig, "pgcode", None) == "23514":
            raise HTTPException(status_code=422, detail="Invalid output_target – allowed values are: html, docx, pdf, xlsx, md") from exc
        if getattr(exc.orig, "pgcode", None) == "23505":
            async with engine.begin() as conn:
                existing = await conn.execute(text("SELECT * FROM template_builder.templates WHERE name = :nm"), {"nm": req.name})
                row = existing.fetchone()
                if row:
                    return row_to_response(row)
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

@router.get("/templates/{template_id}", response_model=TemplateResponse)
async def get_template_by_id(template_id: str, request: Request):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    sql = """
        SELECT template_id, name, description, status, output_target, layout_json,
               default_locale, supported_locales, industry, tags, created_by, created_at, updated_at
        FROM template_builder.templates WHERE template_id = :template_id
    """
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), {"template_id": template_id})
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found")
        return {
            "template_id": to_str(row[0]),
            "name": row[1], "description": row[2], "status": row[3],
            "output_target": row[4], "layout_json": as_json(row[5]),
            "default_locale": row[6], "supported_locales": row[7],
            "industry": row[8], "tags": row[9] or [], "created_by": row[10],
            "created_at": maybe_isoformat(row[11]), "updated_at": maybe_isoformat(row[12]),
        }

@router.put("/templates/{template_id}", status_code=status.HTTP_200_OK, response_model=TemplateResponse)
async def update_template(template_id: str, req: TemplateUpdateRequest, request: Request, skip_audit: bool = False):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    try:
        async with engine.begin() as conn:
            status_res = await conn.execute(
                text("SELECT status FROM template_builder.templates WHERE template_id = :tid"),
                {"tid": template_id})
            status_row = status_res.fetchone()
            if status_row is None:
                raise HTTPException(status_code=404, detail="Template not found")
            if status_row[0] == "published":
                raise HTTPException(status_code=400, detail="Cannot modify a published template; create a new version instead")

            updates: List[str] = []
            params: Dict[str, Any] = {"template_id": template_id}

            if req.name is not None:
                updates.append("name = :name"); params["name"] = req.name
            if req.description is not None:
                updates.append("description = :description"); params["description"] = req.description
            if req.output_target is not None:
                updates.append("output_target = :output_target"); params["output_target"] = req.output_target
            if req.layout_json is not None:
                updates.append("layout_json = CAST(:layout_json AS jsonb)"); params["layout_json"] = json.dumps(req.layout_json)
            if req.default_locale is not None:
                updates.append("default_locale = :default_locale"); params["default_locale"] = req.default_locale
            if req.supported_locales is not None:
                updates.append("supported_locales = :supported_locales"); params["supported_locales"] = req.supported_locales
            if req.industry is not None:
                updates.append("industry = :industry"); params["industry"] = req.industry
            if req.tags is not None:
                updates.append("tags = :tags"); params["tags"] = req.tags

            if not updates:
                raise HTTPException(status_code=400, detail="No fields to update")

            updates.append("updated_at = NOW()")
            sql = f"UPDATE template_builder.templates SET {', '.join(updates)} WHERE template_id = :template_id"
            await conn.execute(text(sql), params)

            if not skip_audit:
                try:
                    await _insert_audit_event(
                        conn, entity_type="template", entity_id=template_id,
                        action="update", actor="dev_user",
                        summary="Template updated",
                        details={"fields_updated": [k for k in params.keys() if k != "template_id"]},
                    )
                except Exception:
                    pass

    except IntegrityError as exc:
        if getattr(exc.orig, "pgcode", None) == "23514":
            raise HTTPException(status_code=422, detail="Invalid output_target – allowed values are: html, docx, pdf, xlsx, md") from exc
        raise HTTPException(status_code=500, detail=f"Database error: {exc}") from exc

    return await get_template_by_id(template_id, request)

@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, request: Request):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    sql = "UPDATE template_builder.templates SET status = 'archived' WHERE template_id = :tid"
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), {"tid": template_id})
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Template not found")
        try:
            await _insert_audit_event(
                conn, entity_type="template", entity_id=template_id,
                action="delete", actor="dev_user",
                summary="Template deleted (archived)",
                details={},
            )
        except Exception:
            pass

    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)

@router.post("/templates/{template_id}/publish", status_code=status.HTTP_201_CREATED, response_model=TemplatePublishResponse)
async def publish_template(template_id: str, request: Request, change_summary: Optional[str] = None):
    actor = request.headers.get("x-user-id", "system")
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    async with engine.begin() as conn:
        fetch_sql = """
            SELECT template_id, name, layout_json, output_target, created_by
            FROM template_builder.templates
            WHERE template_id = :tid AND status = 'draft'
        """
        result = await conn.execute(text(fetch_sql), {"tid": template_id})
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found or not in draft status")

        layout_json_value = row[2]
        if isinstance(layout_json_value, dict):
            layout_json_value = json.dumps(layout_json_value)

        version_id_str = str(uuid.uuid4())
        version_sql = """
            INSERT INTO template_builder.template_versions (
                version_id, template_id, version_number, layout_json, output_target, change_summary, created_at
            ) VALUES (
                :version_id, :template_id,
                (SELECT COALESCE(MAX(version_number), 0) + 1 FROM template_builder.template_versions WHERE template_id = :template_id),
                :layout_json, :output_target, :change_summary, NOW()
            )
        """
        await conn.execute(text(version_sql), {
            "version_id": version_id_str, "template_id": row[0],
            "layout_json": layout_json_value, "output_target": row[3],
            "change_summary": change_summary or "Initial publish",
        })
        await conn.execute(text("UPDATE template_builder.templates SET status = 'published' WHERE template_id = :tid"), {"tid": template_id})
        await _insert_audit_event(conn, entity_type="template", entity_id=template_id,
            action="publish", actor=actor,
            summary=f"Template '{row[1]}' published",
            details={"version_id": version_id_str, "output_target": row[3]})

    return {"version_id": version_id_str, "template_id": template_id, "status": "published", "created_at": datetime.utcnow().isoformat()}

@router.get("/templates", response_model=List[TemplateResponse], status_code=status.HTTP_200_OK)
async def list_templates(
    request: Request,
    status_filter: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    sql = """
        SELECT template_id, name, description, status, output_target, layout_json,
               default_locale, supported_locales, industry, tags, created_by, created_at, updated_at
        FROM template_builder.templates WHERE 1=1
    """
    params: Dict[str, Any] = {}
    if status_filter:
        sql += " AND status = :status_filter"; params["status_filter"] = status_filter
    if industry:
        sql += " AND industry = :industry"; params["industry"] = industry
    if tag:
        sql += " AND :tag = ANY (tags)"; params["tag"] = tag
    if search:
        sql += " AND (name ILIKE :search OR description ILIKE :search)"; params["search"] = f"%{search}%"
    sql += " ORDER BY created_at DESC"

    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()
    return [{
        "template_id": to_str(r[0]), "name": r[1], "description": r[2], "status": r[3],
        "output_target": r[4], "layout_json": as_json(r[5]), "default_locale": r[6],
        "supported_locales": r[7], "industry": r[8], "tags": r[9] or [],
        "created_by": r[10], "created_at": maybe_isoformat(r[11]), "updated_at": maybe_isoformat(r[12]),
    } for r in rows]

@router.post("/templates/{template_id}/placeholders", status_code=status.HTTP_201_CREATED)
async def bind_placeholder(template_id: str, bind_req: PlaceholderBindRequest, request: Request):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT 1 FROM template_builder.templates WHERE template_id = :tid"), {"tid": template_id})
        if result.fetchone() is None:
            raise HTTPException(status_code=404, detail="Template not found")
        result = await conn.execute(text("SELECT 1 FROM template_builder.placeholders_registry WHERE registry_id = :rid"), {"rid": bind_req.registry_id})
        if result.fetchone() is None:
            raise HTTPException(status_code=404, detail="Placeholder not found")

        binding_id_str = str(uuid.uuid4())
        await conn.execute(text("""
            INSERT INTO template_builder.template_placeholders (template_placeholder_id, template_id, registry_id, override_sample_value)
            VALUES (:bid, :tid, :rid, :sample)
        """), {"bid": binding_id_str, "tid": template_id, "rid": bind_req.registry_id, "sample": bind_req.override_sample_value})

    return {"template_placeholder_id": binding_id_str, "template_id": template_id, "registry_id": bind_req.registry_id}

@router.post("/templates/{template_id}/revert-to-draft", response_model=TemplateResponse)
async def revert_to_draft(template_id: str, request: Request):
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    async with engine.begin() as conn:
        result = await conn.execute(
            text("UPDATE template_builder.templates SET status = 'draft', updated_at = NOW() WHERE template_id = CAST(:tid AS uuid) RETURNING template_id"),
            {"tid": template_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Template not found")

    return await get_template_by_id(template_id, request)

@router.get("/templates/{template_id}/versions")
async def list_template_versions(template_id: str, request: Request):
    engine = request.app.state.engine
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT version_id, template_id, version_number, layout_json, output_target, change_summary, created_at
            FROM template_builder.template_versions
            WHERE template_id = CAST(:tid AS uuid)
            ORDER BY version_number DESC
        """), {"tid": template_id})
        rows = result.fetchall()
        return [{
            "version_id": str(r[0]), "template_id": str(r[1]), "version_number": r[2],
            "layout_json": r[3], "output_target": r[4], "change_summary": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        } for r in rows]

# -----------------------------------------------------------------
# NEW: GET /templates/{id}/placeholders
# List all placeholders used in a specific template
# -----------------------------------------------------------------

@router.get("/templates/{template_id}/placeholders")
async def list_template_placeholders(template_id: str, request: Request):
    """
    List all placeholders used in a specific template.
    Scans the template layout_json for {{token}} patterns
    and matches them against the placeholders registry.
    """
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    async with engine.connect() as conn:
        # 1. Load template layout_json
        result = await conn.execute(text("""
            SELECT layout_json FROM template_builder.templates
            WHERE template_id = :tid
        """), {"tid": template_id})
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found")

        layout_json = row[0]
        if isinstance(layout_json, str):
            layout_json = json.loads(layout_json)
        if not isinstance(layout_json, dict):
            layout_json = {"blocks": []}

        # 2. Extract all {{token}} names from all blocks recursively
        def extract_tokens(blocks):
            tokens = set()
            for block in blocks:
                # Text block content
                content = block.get("content", "")
                if content:
                    found = re.findall(r"\{\{([^}]+)\}\}", content)
                    tokens.update(t.strip() for t in found)
                # Table column bindings
                for col in block.get("columns", []):
                    binding = col.get("binding", "")
                    if binding:
                        found = re.findall(r"\{\{([^}]+)\}\}", binding)
                        tokens.update(t.strip() for t in found)
                # Image src
                src = block.get("src", "")
                if src:
                    found = re.findall(r"\{\{([^}]+)\}\}", src)
                    tokens.update(t.strip() for t in found)
                # Section children (recursive)
                children = block.get("children", [])
                if children:
                    tokens.update(extract_tokens(children))
            return tokens

        blocks = layout_json.get("blocks", [])
        token_names = extract_tokens(blocks)

        if not token_names:
            return []

        # 3. Match token names against registry
        result = await conn.execute(text("""
            SELECT
                registry_id, name, category, sample_value,
                generation_mode, datasource_id, is_active, created_at
            FROM template_builder.placeholders_registry
            WHERE name = ANY(:names) AND is_active = true
            ORDER BY name
        """), {"names": list(token_names)})
        rows = result.fetchall()

        return [
            {
                "registry_id":     str(r[0]),
                "name":            r[1],
                "category":        r[2],
                "sample_value":    r[3],
                "generation_mode": r[4],
                "datasource_id":   r[5],
                "is_active":       r[6],
                "created_at":      r[7].isoformat() if r[7] else None,
            }
           for r in rows
        ]   # ← end of return statement


# -----------------------------------------------------------------
# GET /templates/{id}/inputs

        # -----------------------------------------------------------------
# GET /templates/{id}/inputs
# Tells external systems exactly what runtime params this template needs
# -----------------------------------------------------------------
# ─────────────────────────────────────────────────────────────────────────
# REPLACE the existing get_template_inputs() function in templates.py
# (around lines 565-687) with this fixed version.
#
# WHAT THIS FIX DOES:
#   1. AI Prompt placeholders are added INDIVIDUALLY (one input per placeholder)
#      with the correct name and the real saved prompt from DB.
#   2. SQL placeholders still work (with {{params}} extraction) — unchanged.
#   3. Adds a "prompt" field to every AI-mode input so the caller sees
#      the saved prompt directly (your manager wants this).
#   4. Adds a "mode" field so the caller knows whether to send a prompt
#      or just a parameter value.
#   5. Logs what's happening so you can debug if a placeholder isn't found.
# ─────────────────────────────────────────────────────────────────────────

@router.get("/templates/{template_id}/inputs")
async def get_template_inputs(template_id: str, request: Request):
    """
    Returns the required runtime_params for a specific template.
    External systems call this BEFORE calling /documents/generate
    so they know exactly what parameters to pass.

    Behavior:
      - For each {{token}} in the template:
          * If placeholder is in 'llm_prompt' (AI) mode → expose as runtime
            input named after the placeholder, with `prompt` field showing
            the saved AI prompt.
          * If placeholder is in 'manual_sql' mode → extract {{params}}
            from the SQL and expose those as runtime inputs.
    """
    engine: AsyncEngine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")

    async with engine.connect() as conn:

        # ───────────────────────────────────────────────────────────────
        # 1. Load template
        # ───────────────────────────────────────────────────────────────
        result = await conn.execute(text("""
            SELECT template_id, name, description, output_target, layout_json
            FROM template_builder.templates
            WHERE template_id = :tid
        """), {"tid": template_id})
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Template not found")

        tmpl_id       = str(row[0])
        tmpl_name     = row[1]
        tmpl_desc     = row[2]
        output_target = row[3]
        layout_json   = row[4]

        if isinstance(layout_json, str):
            layout_json = json.loads(layout_json)
        if not isinstance(layout_json, dict):
            layout_json = {"blocks": []}

        # ───────────────────────────────────────────────────────────────
        # 2. Extract all {{token}} names from template blocks
        # ───────────────────────────────────────────────────────────────
        def extract_tokens(blocks):
            tokens = set()
            for block in blocks:
                content = block.get("content", "")
                if content:
                    found = re.findall(r"\{\{([^}]+)\}\}", content)
                    tokens.update(t.strip() for t in found)
                for col in block.get("columns", []):
                    binding = col.get("binding", "")
                    if binding:
                        found = re.findall(r"\{\{([^}]+)\}\}", binding)
                        tokens.update(t.strip() for t in found)
                children = block.get("children", [])
                if children:
                    tokens.update(extract_tokens(children))
            return tokens

        blocks = layout_json.get("blocks", [])
        token_names = extract_tokens(blocks)

        # ───────────────────────────────────────────────────────────────
        # 3. For each token — look up placeholder, decide what to expose
        # ───────────────────────────────────────────────────────────────
        inputs = []
        seen_input_names = set()      # avoid duplicates
        unresolved_tokens = []        # tokens that have no placeholder in registry

        if token_names:
            result = await conn.execute(text("""
                SELECT name, sql_text, prompt, sample_value, value_type, generation_mode
                FROM template_builder.placeholders_registry
                WHERE name = ANY(:names) AND is_active = true
                ORDER BY name
            """), {"names": list(token_names)})
            ph_rows = result.fetchall()

            # Build a quick lookup so we can detect missing placeholders
            ph_by_name = {ph[0]: ph for ph in ph_rows}

            for token in sorted(token_names):
                ph = ph_by_name.get(token)
                if ph is None:
                    unresolved_tokens.append(token)
                    continue

                ph_name         = ph[0]
                sql_text        = ph[1] or ""
                ph_prompt       = ph[2] or ""
                sample_value    = ph[3] or ""
                value_type      = ph[4] or "string"
                generation_mode = ph[5]

                # ────────────────────────────────────────────────────
                # AI PROMPT MODE → expose this placeholder as a runtime
                # input with the saved prompt visible to the caller.
                # ────────────────────────────────────────────────────
                if generation_mode == "llm_prompt":
                    if ph_name in seen_input_names:
                        continue
                    seen_input_names.add(ph_name)
                    inputs.append({
                        "name":                ph_name,
                        "mode":                "ai_prompt",
                        "required":            True,
                        "type":                value_type,
                        "prompt":              ph_prompt,        # ← SAVED PROMPT FROM DB
                        "example":             ph_prompt or sample_value or "",
                        "description":         f"AI prompt for placeholder '{ph_name}' — sent to webhook to fetch value at generation time",
                        "used_in_placeholder": ph_name,
                    })

                # ────────────────────────────────────────────────────
                # SQL MODE → extract {{params}} from the SQL and expose
                # each one as its own runtime input.
                # ────────────────────────────────────────────────────
                elif generation_mode == "manual_sql":
                    sql_params = re.findall(r"\{\{([^}]+)\}\}", sql_text)
                    for sp in sql_params:
                        sp = sp.strip()
                        if sp in seen_input_names:
                            continue
                        seen_input_names.add(sp)
                        inputs.append({
                            "name":                sp,
                            "mode":                "sql_param",
                            "required":            True,
                            "type":                "string",
                            "example":             _guess_example(sp),
                            "description":         f"Required by placeholder '{ph_name}' — injected into SQL at generation time",
                            "used_in_placeholder": ph_name,
                        })

        # ───────────────────────────────────────────────────────────────
        # 4. Build example request body for /documents/generate
        # ───────────────────────────────────────────────────────────────
        example_runtime_params = {
            inp["name"]: inp["example"] for inp in inputs
        }

        return {
            "template_id":          tmpl_id,
            "template_name":        tmpl_name,
            "description":          tmpl_desc or "",
            "output_target":        output_target,
            "total_placeholders":   len(token_names),
            "total_runtime_inputs": len(inputs),
            "inputs":               inputs,
            "unresolved_tokens":    unresolved_tokens,   # NEW: helps debug missing placeholders
            "usage": {
                "description":     "Pass these params when calling POST /v1/documents/generate",
                "endpoint":        "POST /v1/documents/generate",
                "example_request": {
                    "template_id":    tmpl_id,
                    "output_target":  output_target,
                    "locale":         "en",
                    "runtime_params": example_runtime_params or {"note": "No runtime params needed"},
                }
            }
        }

def _guess_example(param_name: str) -> str:
    name = param_name.lower()
    if "loan" in name:        return "LN12345"
    if "customer_id" in name: return "1"
    if "customer" in name:    return "John Valid"
    if "from_date" in name:   return "2026-01-01"
    if "to_date" in name:     return "2026-03-31"
    if "date" in name:        return "2026-04-01"
    if "month" in name:       return "March 2026"
    if "year" in name:        return "2026"
    if "amount" in name:      return "50000"
    if "account" in name:     return "AC-88451"
    if "email" in name:       return "customer@example.com"
    if "phone" in name:       return "+91-9000000001"
    if "name" in name:        return "John Valid"
    if "id" in name:          return "1"
    return "value"