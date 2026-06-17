# src/api/documents.py – Document generation with real datasource rendering
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List
import uuid
import json
import logging
import os
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "/app/results"))
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------
# Models
# -----------------------------------------------------------------

class GenerateRequest(BaseModel):
    template_id: str = Field(..., description="UUID of the template to render")
    output_target: str = Field(..., pattern=r"^(html|docx|pdf|xlsx|md)$")
    locale: str = Field(default="en", pattern=r"^[a-z]{2}$")
    runtime_params: Dict[str, Any] = Field(default_factory=dict)

class GenerateResponse(BaseModel):
    status: str
    job_id: str

class PreviewRequest(BaseModel):
    template_id: str = Field(..., description="UUID of the template to preview")
    sample_overrides: Dict[str, str] = Field(default_factory=dict)

class PreviewResponse(BaseModel):
    html: str
    template_name: str
    placeholder_count: int

# -----------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------

def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine

def get_current_user(request: Request) -> str:
    return request.headers.get("x-user-id", "system")

async def _insert_generic_audit(conn, entity_type, entity_id, action, actor, summary=None, details=None):
    sql = text("""
        INSERT INTO template_builder.audit_events (
            event_id, entity_type, entity_id, action, actor, summary, details_json, created_at
        ) VALUES (
            uuid_generate_v4(), :etype, :eid, :act, :actor, :summary, :details, NOW()
        )
    """)
    await conn.execute(sql, {
        "etype": entity_type, "eid": entity_id, "act": action,
        "actor": actor, "summary": summary, "details": json.dumps(details or {})
    })

# -----------------------------------------------------------------
# Resolve prompt via webhook
# Returns dict of {placeholder_name: value} to inject into context
# -----------------------------------------------------------------

async def _resolve_prompt_via_webhook(
    prompt_text: str,
    placeholder_names: List[str],
) -> Dict[str, str]:
    """
    Send prompt to LLM_WEBHOOK_URL.
    Webhook returns: { "sql": "...", "value": "John Valid", "error": "" }
    We use the VALUE directly — no SQL execution against DB.
    We inject the value into ALL placeholder_names provided.
    """
    result_values: Dict[str, str] = {}

    webhook_url = os.getenv("LLM_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("LLM_WEBHOOK_URL not set — cannot resolve prompt")
        return result_values

    try:
        import httpx as _httpx
        logger.info(f"Sending prompt to webhook: {prompt_text[:100]}")
        async with _httpx.AsyncClient(timeout=30) as client:
            webhook_resp = await client.post(
                webhook_url,
                json={
                    "prompt": prompt_text,
                    "datasource_schema": "",
                    "cardinality": "scalar"
                },
            )
            webhook_data = webhook_resp.json()

        webhook_value = webhook_data.get("value", "")
        webhook_error = webhook_data.get("error", "")

        if webhook_error:
            logger.warning(f"Webhook error: {webhook_error}")
        elif webhook_value:
            # Inject webhook value into all placeholder_names
            for ph_name in placeholder_names:
                result_values[ph_name] = webhook_value
                logger.info(f"Webhook value '{webhook_value}' → placeholder '{ph_name}'")
        else:
            logger.warning("Webhook returned empty value")

    except Exception as exc:
        logger.error(f"Prompt webhook call failed: {exc}")

    return result_values

# -----------------------------------------------------------------
# Build context
# -----------------------------------------------------------------
#
# ★★★ FIXED VERSION ★★★
#
# For each AI Prompt placeholder, the prompt to send to the webhook
# is picked in this priority order:
#
#   1. runtime_params[<placeholder_name>]   ← caller overrides per placeholder
#   2. runtime_params["prompt"]             ← legacy single-prompt for all
#   3. saved prompt from placeholders_registry  ← default from UI
#
# The webhook is called ONCE PER AI placeholder, so different placeholders
# can produce different values from different prompts.
# -----------------------------------------------------------------

async def _build_context(
    conn,
    template_id: str,
    runtime_params: Dict[str, Any],
    layout_json: Dict,
) -> Dict[str, Any]:
    from core.resolver import Resolver
    from collections import defaultdict

    resolver  = Resolver()
    context_values: Dict[str, str]    = {}
    context_datasets: Dict[str, List] = {}

    # ───────────────────────────────────────────────────────────────
    # Load all active placeholders from registry
    # NOTE: now also fetches `pr.prompt` (saved AI prompt)
    # ───────────────────────────────────────────────────────────────
    sql = text("""
        SELECT
            pr.name,
            pr.sql_text,
            pr.sample_value,
            pr.format_json,
            pr.generation_mode,
            ds.connection_key,
            pr.prompt
        FROM template_builder.placeholders_registry pr
        LEFT JOIN eivs.datasources ds ON ds.datasource_id = pr.datasource_id
        WHERE pr.is_active = true
        ORDER BY pr.datasource_id, pr.name
    """)
    result = await conn.execute(sql)
    rows   = result.fetchall()

    grouped: Dict[str, list] = defaultdict(list)

    # ───────────────────────────────────────────────────────────────
    # Build a lookup of all AI Prompt placeholders → saved prompt
    # ───────────────────────────────────────────────────────────────
    ai_prompt_placeholders: Dict[str, str] = {
        row[0]: (row[6] or "")
        for row in rows
        if row[4] == "llm_prompt"
    }

    placeholder_name_set = {row[0] for row in rows}

    # ───────────────────────────────────────────────────────────────
    # ★ For each AI placeholder, resolve via webhook
    # ───────────────────────────────────────────────────────────────
    generic_prompt = runtime_params.get("prompt")  # legacy single-prompt

    for ph_name, saved_prompt in ai_prompt_placeholders.items():

        # Pick the prompt to use
        prompt_text: Optional[str] = None
        if ph_name in runtime_params and runtime_params[ph_name]:
            prompt_text = str(runtime_params[ph_name])
            logger.info(f"AI placeholder '{ph_name}': using prompt from runtime_params['{ph_name}']")
        elif generic_prompt:
            prompt_text = str(generic_prompt)
            logger.info(f"AI placeholder '{ph_name}': using generic 'prompt' from runtime_params")
        elif saved_prompt:
            prompt_text = saved_prompt
            logger.info(f"AI placeholder '{ph_name}': using saved prompt from registry")
        else:
            logger.warning(f"AI placeholder '{ph_name}': no prompt available — will fall back to sample_value")
            continue

        # Call the webhook with this specific prompt
        webhook_values = await _resolve_prompt_via_webhook(
            prompt_text, [ph_name]
        )
        if ph_name in webhook_values:
            context_values[ph_name] = webhook_values[ph_name]
        else:
            logger.warning(f"AI placeholder '{ph_name}': webhook returned no value")

    # ───────────────────────────────────────────────────────────────
    # Process all placeholders for SQL mode + fallbacks
    # ───────────────────────────────────────────────────────────────
    for row in rows:
        name            = row[0]
        sql_text        = row[1]
        sample_value    = row[2] or ""
        format_json     = row[3] or {}
        generation_mode = row[4]
        connection_key  = row[5]

        # Already resolved via webhook → skip
        if name in context_values:
            continue

        # SQL mode → batch resolve (unchanged behaviour)
        if generation_mode == "manual_sql" and sql_text and sql_text.strip() and connection_key:
            grouped[connection_key].append({
                "name":         name,
                "sql_text":     sql_text,
                "sample_value": sample_value,
                "format_json":  format_json,
            })
        elif generation_mode == "llm_prompt":
            # Webhook didn't resolve this one → fall back to sample_value
            context_values[name] = sample_value
            logger.info(f"AI Prompt placeholder '{name}': falling back to sample_value '{sample_value}'")
        else:
            # Other modes → fallback to sample value
            context_values[name] = sample_value

    # ───────────────────────────────────────────────────────────────
    # Batch resolve SQL placeholders (unchanged)
    # ───────────────────────────────────────────────────────────────
    logger.info(f"Batch resolution: {len(grouped)} datasource group(s)")
    for connection_key, ph_list in grouped.items():
        batch_results = await resolver.resolve_batch(ph_list, connection_key, runtime_params)
        context_values.update(batch_results)

    # ───────────────────────────────────────────────────────────────
    # Add remaining runtime_params to context
    #
    # IMPORTANT: skip keys that are placeholder names (those are already
    # resolved via webhook/SQL) and skip the legacy "prompt" key — we
    # don't want to stuff prompt text into the rendered output.
    # ───────────────────────────────────────────────────────────────
    for key, val in runtime_params.items():
        if key in placeholder_name_set:
            continue
        if key == "prompt":
            continue
        if key not in context_values:
            context_values[key] = str(val)

    # ───────────────────────────────────────────────────────────────
    # Resolve table datasets (unchanged)
    # ───────────────────────────────────────────────────────────────
    blocks = layout_json.get("blocks", [])
    for block in blocks:
        if block.get("type") != "table":
            continue
        repeat_sql = block.get("repeat", "").strip()
        block_id   = block.get("block_id", "unknown")
        if not repeat_sql:
            continue
        dataset_rows = await resolver.resolve_dataset(
            block_id=block_id, repeat_sql=repeat_sql, runtime_params=runtime_params,
        )
        if dataset_rows:
            context_datasets[block_id] = dataset_rows

    logger.info(f"Context built: {len(context_values)} values, {len(context_datasets)} dataset(s)")
    return {"values": context_values, "datasets": context_datasets}

# -----------------------------------------------------------------
# Build sample context
# -----------------------------------------------------------------

async def _build_sample_context(
    conn,
    sample_overrides: Dict[str, str],
    layout_json: Dict,
) -> Dict[str, Any]:
    from core.resolver import Resolver
    resolver = Resolver()

    context_values: Dict[str, str]    = {}
    context_datasets: Dict[str, List] = {}

    sql = text("""
        SELECT name, sample_value
        FROM template_builder.placeholders_registry
        WHERE is_active = true
        ORDER BY name
    """)
    result = await conn.execute(sql)
    rows   = result.fetchall()

    for row in rows:
        name         = row[0]
        sample_value = row[1] or ""
        if name in sample_overrides:
            context_values[name] = sample_overrides[name]
        else:
            context_values[name] = sample_value

    blocks = layout_json.get("blocks", [])
    for block in blocks:
        if block.get("type") != "table":
            continue
        repeat_sql = block.get("repeat", "").strip()
        block_id   = block.get("block_id", "unknown")
        if not repeat_sql:
            continue
        dataset_rows = await resolver.resolve_dataset(
            block_id=block_id, repeat_sql=repeat_sql,
        )
        if dataset_rows:
            context_datasets[block_id] = dataset_rows

    return {"values": context_values, "datasets": context_datasets}

# -----------------------------------------------------------------
# POST /preview
# -----------------------------------------------------------------

@router.post("/preview", response_model=PreviewResponse)
async def preview_template(payload: PreviewRequest, request: Request) -> PreviewResponse:
    engine = get_engine(request)

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT template_id, name, layout_json
            FROM template_builder.templates
            WHERE template_id = :tid
        """), {"tid": payload.template_id})
        tmpl_row = result.fetchone()
        if not tmpl_row:
            raise HTTPException(status_code=404, detail=f"Template {payload.template_id} not found")

    layout_json = tmpl_row[2]
    if isinstance(layout_json, str):
        layout_json = json.loads(layout_json)
    if not isinstance(layout_json, dict):
        layout_json = {"blocks": []}

    async with engine.connect() as conn:
        context = await _build_sample_context(conn, payload.sample_overrides, layout_json)

    from core.renderers.html import HtmlRenderer
    html = HtmlRenderer().render(layout_json, context)

    return PreviewResponse(
        html=html,
        template_name=tmpl_row[1],
        placeholder_count=len(context["values"]),
    )

# -----------------------------------------------------------------
# POST /generate
# -----------------------------------------------------------------

@router.post("/generate", status_code=status.HTTP_201_CREATED, response_model=GenerateResponse)
async def generate_document(
    payload: GenerateRequest,
    request: Request,
    user: str = Depends(get_current_user),
) -> GenerateResponse:
    engine = get_engine(request)

    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT template_id, name, layout_json, status
            FROM template_builder.templates
            WHERE template_id = :tid
        """), {"tid": payload.template_id})
        tmpl_row = result.fetchone()
        if not tmpl_row:
            raise HTTPException(status_code=404, detail=f"Template {payload.template_id} not found")

    layout_json = tmpl_row[2]
    if isinstance(layout_json, str):
        layout_json = json.loads(layout_json)
    if not isinstance(layout_json, dict):
        layout_json = {"blocks": []}

    job_id = str(uuid.uuid4())
    audit_details = {
        "template_id":         payload.template_id,
        "output_target":       payload.output_target,
        "locale":              payload.locale,
        "runtime_params_keys": list(payload.runtime_params.keys()),
    }

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO template_builder.render_jobs (
                job_id, template_id, status, output_target, locale, runtime_params, created_at, updated_at
            ) VALUES (
                :jid, :tid, 'running', :ot, :loc, :params, NOW(), NOW()
            )
        """), {
            "jid": job_id, "tid": payload.template_id,
            "ot": payload.output_target, "loc": payload.locale,
            "params": json.dumps(payload.runtime_params),
        })

    try:
        async with engine.begin() as conn:
            context = await _build_context(
                conn, payload.template_id, payload.runtime_params, layout_json
            )

        output_target   = payload.output_target
        result_filename = f"{job_id}.{output_target}"
        result_path     = RESULTS_DIR / result_filename

        if output_target == "html":
            from core.renderers.html import HtmlRenderer
            content_bytes = HtmlRenderer().render(layout_json, context).encode("utf-8")
            result_path.write_bytes(content_bytes)
        elif output_target == "docx":
            from core.renderers.docx import DocxRenderer
            content_bytes = DocxRenderer().render(layout_json, context)
            result_path.write_bytes(content_bytes)
        elif output_target == "pdf":
            from core.renderers.pdf import PdfRenderer
            content_bytes = PdfRenderer().render(layout_json, context)
            result_path.write_bytes(content_bytes)
        elif output_target == "xlsx":
            from core.renderers.xlsx import XlsxRenderer
            content_bytes = XlsxRenderer().render(layout_json, context)
            result_path.write_bytes(content_bytes)
        elif output_target == "md":
            from core.renderers.md import MdRenderer
            content_bytes = MdRenderer().render(layout_json, context).encode("utf-8")
            result_path.write_bytes(content_bytes)
        else:
            raise ValueError(f"Unsupported format: {output_target}")

        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE template_builder.render_jobs
                SET status = 'success', result_location = :loc, updated_at = NOW()
                WHERE job_id = :jid
            """), {"loc": str(result_path), "jid": job_id})
            await _insert_generic_audit(conn, "render_jobs", job_id, "generate", user,
                f"Document generated ({output_target}) → {result_filename}", audit_details)

        logger.info(f"Document rendered successfully: {result_path}")

    except Exception as exc:
        logger.error(f"Render failed for job {job_id}: {exc}")
        async with engine.begin() as conn:
            await conn.execute(text("""
                UPDATE template_builder.render_jobs
                SET status = 'error', logs = :logs, updated_at = NOW()
                WHERE job_id = :jid
            """), {"logs": str(exc), "jid": job_id})
            try:
                await _insert_generic_audit(
                    conn, "render_jobs", job_id, "error", user,
                    f"Document render failed: {str(exc)[:200]}",
                    {"output_target": payload.output_target, "error": str(exc)[:500]}
                )
            except Exception:
                pass

    return GenerateResponse(status="success", job_id=job_id)

# -----------------------------------------------------------------
# Get job status
# -----------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=dict)
async def get_job_status(job_id: str, request: Request) -> Dict[str, Any]:
    engine = get_engine(request)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT job_id, status, output_target, result_location, logs, created_at, updated_at
            FROM template_builder.render_jobs WHERE job_id = :jid
        """), {"jid": job_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
        return {
            "job_id":          str(row[0]),
            "status":          row[1],
            "output_target":   row[2],
            "result_location": row[3],
            "logs":            row[4],
            "created_at":      row[5].isoformat() if row[5] else None,
            "updated_at":      row[6].isoformat() if row[6] else None,
        }

# -----------------------------------------------------------------
# Download
# -----------------------------------------------------------------

@router.get("/jobs/{job_id}/download")
async def download_document(job_id: str, request: Request):
    engine = get_engine(request)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT result_location, output_target, status
            FROM template_builder.render_jobs WHERE job_id = :jid
        """), {"jid": job_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        if row[2] != "success":
            raise HTTPException(status_code=400, detail=f"Job status: {row[2]}")
        if not row[0]:
            raise HTTPException(status_code=404, detail="No file generated")

        file_path = Path(row[0])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="File not found on server")

        media_types = {
            "html": "text/html",
            "pdf":  "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "md":   "text/markdown",
        }
        return FileResponse(
            path=str(file_path),
            filename=f"document_{job_id[:8]}.{row[1]}",
            media_type=media_types.get(row[1], "application/octet-stream"),
        )

# -----------------------------------------------------------------
# List jobs
# -----------------------------------------------------------------

@router.get("/jobs", response_model=list)
async def list_jobs(request: Request, template_id: Optional[str] = None, limit: int = 50) -> list:
    engine = get_engine(request)
    async with engine.connect() as conn:
        if template_id:
            result = await conn.execute(text("""
                SELECT rj.job_id, rj.template_id, t.name,
                       rj.status, rj.output_target, rj.runtime_params,
                       rj.result_location, rj.created_at
                FROM template_builder.render_jobs rj
                LEFT JOIN template_builder.templates t ON rj.template_id = t.template_id
                WHERE rj.template_id = :tid
                ORDER BY rj.created_at DESC LIMIT :lim
            """), {"tid": template_id, "lim": limit})
        else:
            result = await conn.execute(text("""
                SELECT rj.job_id, rj.template_id, t.name,
                       rj.status, rj.output_target, rj.runtime_params,
                       rj.result_location, rj.created_at
                FROM template_builder.render_jobs rj
                LEFT JOIN template_builder.templates t ON rj.template_id = t.template_id
                ORDER BY rj.created_at DESC LIMIT :lim
            """), {"lim": limit})
        rows = result.fetchall()
        return [
            {
                "job_id":          str(r[0]),
                "template_id":     str(r[1]),
                "template_name":   r[2] or "Unknown",
                "status":          r[3],
                "output_target":   r[4],
                "runtime_params":  r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                "result_location": r[6],
                "created_at":      r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]

@router.get("/{job_id}", response_model=dict, include_in_schema=False)
async def get_job_status_alias(job_id: str, request: Request):
    return await get_job_status(job_id, request)

# =============================================================================
# APPEND THIS TO THE BOTTOM OF: backend/src/api/documents.py
#
# Adds GET /v1/documents/templates endpoint
# Returns all non-archived templates for the Run Console dropdown
# =============================================================================

@router.get("/templates", response_model=list)
async def list_templates_for_run_console(
    request: Request,
    status_filter: Optional[str] = None,
) -> list:
    """
    List templates for the Run Console dropdown.
    Frontend calls this to populate the template selector
    after a successful prompt run.

    Optional: ?status_filter=published (default: all non-archived)
    """
    engine = get_engine(request)
    async with engine.connect() as conn:
        if status_filter:
            result = await conn.execute(text("""
                SELECT
                    template_id,
                    name,
                    description,
                    status,
                    output_target,
                    industry,
                    created_at
                FROM template_builder.templates
                WHERE status = :status
                ORDER BY name ASC
            """), {"status": status_filter})
        else:
            result = await conn.execute(text("""
                SELECT
                    template_id,
                    name,
                    description,
                    status,
                    output_target,
                    industry,
                    created_at
                FROM template_builder.templates
                WHERE status != 'archived'
                ORDER BY name ASC
            """))

        rows = result.fetchall()
        return [
            {
                "template_id":   str(row[0]),
                "name":          row[1],
                "description":   row[2] or "",
                "status":        row[3],
                "output_target": row[4],
                "industry":      row[5] or "",
                "created_at":    row[6].isoformat() if row[6] else None,
            }
            for row in rows
        ]
    # -----------------------------------------------------------------
# Delete single job
# -----------------------------------------------------------------

@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, request: Request, user: str = Depends(get_current_user)):
    engine = get_engine(request)
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT job_id, result_location FROM template_builder.render_jobs WHERE job_id = :jid
        """), {"jid": job_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")

        # Delete the file from disk
        if row[1]:
            file_path = Path(row[1])
            if file_path.exists():
                file_path.unlink()

        # Delete from DB
        await conn.execute(text("""
            DELETE FROM template_builder.render_jobs WHERE job_id = :jid
        """), {"jid": job_id})
        await _insert_generic_audit(
            conn, "render_jobs", job_id, "delete", user,
            f"Document job deleted", {"job_id": job_id}
        )

    return {"deleted": job_id}