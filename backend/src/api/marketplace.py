# backend/src/api/marketplace.py
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()
logger = logging.getLogger(__name__)


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


def validate_uuid(value: str, field_name: str = "id") -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")


def json_dumps(value: Any) -> str:
    return json.dumps(value, default=str)


def normalize_payload(payload: Any) -> Dict[str, Any]:
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {}
    return {}


class MarketplaceItemCreate(BaseModel):
    type: str = Field(..., pattern="^(template|block|placeholder)$")
    source_id: str
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    owner: str = Field(default="dev_user")
    license: str = "Community"
    tags: List[str] = Field(default_factory=list)
    is_public: bool = True


class MarketplaceItemResponse(BaseModel):
    item_id: str
    type: str
    source_id: str
    name: str
    description: Optional[str]
    owner: str
    license: str
    rating: Optional[float]
    downloads: int
    tags: List[str]
    is_public: bool
    created_at: str


class RateItemRequest(BaseModel):
    rating: float = Field(..., ge=1.0, le=5.0)


def row_to_item(row) -> Dict[str, Any]:
    return {
        "item_id":     str(row[0]),
        "type":        row[1],
        "source_id":   str(row[2]),
        "name":        row[3],
        "description": row[4],
        "owner":       row[5],
        "license":     row[6],
        "rating":      float(row[7]) if row[7] is not None else None,
        "downloads":   row[8] or 0,
        "tags":        row[9] or [],
        "is_public":   bool(row[10]),
        "created_at":  row[11].isoformat() if row[11] else "",
    }


async def fetch_source_payload(conn, item_type: str, source_id: str) -> Optional[str]:
    """Fetch and store source data as payload for future import fallback."""
    try:
        if item_type == "placeholder":
            result = await conn.execute(text("""
                SELECT name, sql_text, sample_value, generation_mode,
                       datasource_id, format_json, value_type, cardinality, classification
                FROM template_builder.placeholders_registry
                WHERE registry_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if not row:
                return None
            return json_dumps({
                "name":            row[0],
                "sql_text":        row[1],
                "sample_value":    row[2],
                "generation_mode": row[3] or "manual_sql",
                "datasource_id":   row[4],  # integer — store as-is
                "format_json":     row[5] or {},
                "value_type":      row[6] or "string",
                "cardinality":     row[7] or "scalar",
                "classification":  row[8] or "internal",
            })

        elif item_type == "block":
            result = await conn.execute(text("""
                SELECT name, description, block_json, tags, industry
                FROM template_builder.blocks_library
                WHERE block_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if not row:
                return None
            return json_dumps({
                "name":        row[0],
                "description": row[1],
                "block_json":  row[2] or {},
                "tags":        row[3] or [],
                "industry":    row[4],
            })

        elif item_type == "template":
            result = await conn.execute(text("""
                SELECT name, description, layout_json, output_target,
                       default_locale, supported_locales, industry, tags
                FROM template_builder.templates
                WHERE template_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if not row:
                return None
            return json_dumps({
                "name":              row[0],
                "description":       row[1],
                "layout_json":       row[2] or {},
                "output_target":     row[3],
                "default_locale":    row[4],
                "supported_locales": row[5] or [],
                "industry":          row[6],
                "tags":              row[7] or [],
            })
    except Exception as e:
        logger.warning(f"fetch_source_payload failed: {e}")
    return None


# =============================================================================
# GET / — list
# =============================================================================

@router.get("/", response_model=List[MarketplaceItemResponse])
async def list_marketplace_items(
    request: Request,
    item_type: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    public_only: bool = True,
):
    engine = get_engine(request)
    sql = """
        SELECT item_id, type, source_id, name, description, owner,
               license, rating, downloads, tags, is_public, created_at
        FROM template_builder.marketplace_items WHERE 1=1
    """
    params: Dict[str, Any] = {}
    if public_only:
        sql += " AND is_public = TRUE"
    if item_type:
        sql += " AND type = :item_type"
        params["item_type"] = item_type
    if tag:
        sql += " AND :tag = ANY(tags)"
        params["tag"] = tag
    if search:
        sql += " AND (name ILIKE :search OR COALESCE(description,'') ILIKE :search)"
        params["search"] = f"%{search}%"
    sql += " ORDER BY downloads DESC, created_at DESC"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()
    return [row_to_item(r) for r in rows]


# =============================================================================
# POST / — publish
# =============================================================================

@router.post("/", response_model=MarketplaceItemResponse, status_code=201)
async def publish_item(item: MarketplaceItemCreate, request: Request):
    engine = get_engine(request)
    source_id = validate_uuid(item.source_id, "source_id")

    verify_queries = {
        "template":    "SELECT template_id FROM template_builder.templates WHERE template_id = CAST(:id AS uuid)",
        "block":       "SELECT block_id FROM template_builder.blocks_library WHERE block_id = CAST(:id AS uuid)",
        "placeholder": "SELECT registry_id FROM template_builder.placeholders_registry WHERE registry_id = CAST(:id AS uuid)",
    }

    async with engine.begin() as conn:
        # Verify source exists
        result = await conn.execute(text(verify_queries[item.type]), {"id": source_id})
        if not result.fetchone():
            raise HTTPException(status_code=400, detail=f"Source {item.type} not found")

        # Check duplicate
        dup = await conn.execute(text("""
            SELECT item_id FROM template_builder.marketplace_items
            WHERE source_id = CAST(:id AS uuid) AND type = :type
        """), {"id": source_id, "type": item.type})
        if dup.fetchone():
            raise HTTPException(status_code=409, detail="This item is already published to the marketplace")

        # Store payload for fallback import
        payload = await fetch_source_payload(conn, item.type, source_id)
        item_id = str(uuid.uuid4())

        # Insert without payload first (payload column may not exist)
        await conn.execute(text("""
            INSERT INTO template_builder.marketplace_items
                (item_id, type, source_id, name, description, owner,
                 license, rating, downloads, tags, is_public, created_at)
            VALUES
                (CAST(:item_id AS uuid), :type, CAST(:source_id AS uuid),
                 :name, :description, :owner, :license, NULL, 0,
                 :tags, :is_public, NOW())
        """), {
            "item_id":     item_id,
            "type":        item.type,
            "source_id":   source_id,
            "name":        item.name,
            "description": item.description,
            "owner":       item.owner,
            "license":     item.license,
            "tags":        item.tags,
            "is_public":   item.is_public,
        })

        # Try to store payload (only works if payload column exists)
        if payload:
            try:
                await conn.execute(text("""
                    UPDATE template_builder.marketplace_items
                    SET payload = CAST(:payload AS jsonb)
                    WHERE item_id = CAST(:item_id AS uuid)
                """), {"payload": payload, "item_id": item_id})
            except Exception as pe:
                logger.warning(f"Could not store payload (column may not exist): {pe}")

        result = await conn.execute(text("""
            SELECT item_id, type, source_id, name, description, owner,
                   license, rating, downloads, tags, is_public, created_at
            FROM template_builder.marketplace_items
            WHERE item_id = CAST(:item_id AS uuid)
        """), {"item_id": item_id})
        row = result.fetchone()

    # Audit log
    try:
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO template_builder.audit_events
                    (event_id, entity_type, entity_id, action, actor, summary, details_json, created_at)
                VALUES
                    (uuid_generate_v4(), 'marketplace', CAST(:eid AS uuid), 'publish',
                     :actor, :summary, CAST(:details AS jsonb), NOW())
            """), {
                "eid":     item_id,
                "actor":   item.owner,
                "summary": f"{item.type.capitalize()} '{item.name}' published to marketplace",
                "details": json.dumps({"type": item.type, "source_id": item.source_id}),
            })
    except Exception:
        pass

    logger.info(f"Published {item.type} '{item.name}' to marketplace")
    return row_to_item(row)


# =============================================================================
# GET /{item_id}
# =============================================================================

@router.get("/{item_id}", response_model=MarketplaceItemResponse)
async def get_marketplace_item(item_id: str, request: Request):
    engine = get_engine(request)
    item_id = validate_uuid(item_id, "item_id")
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT item_id, type, source_id, name, description, owner,
                   license, rating, downloads, tags, is_public, created_at
            FROM template_builder.marketplace_items
            WHERE item_id = CAST(:item_id AS uuid)
        """), {"item_id": item_id})
        row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Marketplace item not found")
    return row_to_item(row)


# =============================================================================
# POST /{item_id}/rate
# =============================================================================

@router.post("/{item_id}/rate", response_model=MarketplaceItemResponse)
async def rate_marketplace_item(item_id: str, payload: RateItemRequest, request: Request):
    engine = get_engine(request)
    item_id = validate_uuid(item_id, "item_id")
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            SELECT rating, downloads FROM template_builder.marketplace_items
            WHERE item_id = CAST(:item_id AS uuid)
        """), {"item_id": item_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Marketplace item not found")

        current_rating = float(row[0]) if row[0] is not None else None
        downloads      = row[1] or 0
        if current_rating is None:
            new_rating = round(payload.rating, 1)
        else:
            total_votes = max(downloads, 1)
            new_rating  = round((current_rating * total_votes + payload.rating) / (total_votes + 1), 1)

        await conn.execute(text("""
            UPDATE template_builder.marketplace_items
            SET rating = :rating WHERE item_id = CAST(:item_id AS uuid)
        """), {"rating": new_rating, "item_id": item_id})

        result = await conn.execute(text("""
            SELECT item_id, type, source_id, name, description, owner,
                   license, rating, downloads, tags, is_public, created_at
            FROM template_builder.marketplace_items
            WHERE item_id = CAST(:item_id AS uuid)
        """), {"item_id": item_id})
    # Audit log
    try:
        async with engine.begin() as conn2:
            await conn2.execute(text("""
                INSERT INTO template_builder.audit_events
                    (event_id, entity_type, entity_id, action, actor, summary, details_json, created_at)
                VALUES
                    (uuid_generate_v4(), 'marketplace', CAST(:eid AS uuid), 'rate',
                     'dev_user', :summary, CAST(:details AS jsonb), NOW())
            """), {
                "eid":     item_id,
                "summary": f"Item rated {payload.rating} stars (new avg: {new_rating})",
                "details": json.dumps({"rating": payload.rating, "new_avg": new_rating}),
            })
    except Exception:
        pass

    logger.info(f"Item {item_id} rated {payload.rating} → new avg {new_rating}")
    return row_to_item(result.fetchone())


# =============================================================================
# POST /{item_id}/import
# =============================================================================

@router.post("/{item_id}/import")
async def import_marketplace_item(item_id: str, request: Request):
    engine = get_engine(request)
    item_id = validate_uuid(item_id, "item_id")

    async with engine.connect() as conn:
        # Try to select with payload, fallback without
        try:
            result = await conn.execute(text("""
                SELECT type, source_id, name, description, tags, payload
                FROM template_builder.marketplace_items
                WHERE item_id = CAST(:item_id AS uuid) AND is_public = TRUE
            """), {"item_id": item_id})
        except Exception:
            result = await conn.execute(text("""
                SELECT type, source_id, name, description, tags, NULL
                FROM template_builder.marketplace_items
                WHERE item_id = CAST(:item_id AS uuid) AND is_public = TRUE
            """), {"item_id": item_id})
        item = result.fetchone()

    if not item:
        raise HTTPException(status_code=404, detail="Public item not found")

    item_type       = item[0]
    source_id       = str(item[1])
    item_desc       = item[3]
    stored_payload  = normalize_payload(item[5])

    # ── TEMPLATE ──────────────────────────────────────────────────
    if item_type == "template":
        tmpl = None
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT name, description, layout_json, output_target,
                       default_locale, supported_locales, industry, tags
                FROM template_builder.templates
                WHERE template_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if row:
                tmpl = {
                    "name": row[0], "description": row[1],
                    "layout_json": row[2] or {}, "output_target": row[3],
                    "default_locale": row[4], "supported_locales": row[5] or [],
                    "industry": row[6], "tags": row[7] or [],
                }
        if not tmpl:
            tmpl = stored_payload
        if not tmpl:
            raise HTTPException(status_code=404, detail="Source template not found and no backup available")

        new_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO template_builder.templates (
                    template_id, name, description, status, output_target,
                    layout_json, default_locale, supported_locales, industry, tags,
                    created_by, created_at, updated_at
                ) VALUES (
                    CAST(:id AS uuid), :name, :description, 'draft', :output_target,
                    CAST(:layout_json AS jsonb), :default_locale, :supported_locales,
                    :industry, :tags, :created_by, NOW(), NOW()
                )
            """), {
                "id":                new_id,
                "name":              f"{tmpl.get('name','Template')} (from Marketplace)",
                "description":       item_desc or tmpl.get("description") or "Imported from marketplace",
                "output_target":     tmpl.get("output_target") or "html",
                "layout_json":       json_dumps(tmpl.get("layout_json") or {}),
                "default_locale":    tmpl.get("default_locale") or "en",
                "supported_locales": tmpl.get("supported_locales") or ["en"],
                "industry":          tmpl.get("industry"),
                "tags":              tmpl.get("tags") or [],
                "created_by":        "dev_user",
            })
            await conn.execute(text("""
                UPDATE template_builder.marketplace_items
                SET downloads = downloads + 1
                WHERE item_id = CAST(:item_id AS uuid)
            """), {"item_id": item_id})
        return {"detail": "Template imported successfully", "type": "template",
                "new_id": new_id, "name": f"{tmpl.get('name')} (from Marketplace)"}

    # ── BLOCK ─────────────────────────────────────────────────────
    elif item_type == "block":
        block = None
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT name, description, block_json, tags, industry
                FROM template_builder.blocks_library
                WHERE block_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if row:
                block = {"name": row[0], "description": row[1],
                         "block_json": row[2] or {}, "tags": row[3] or [], "industry": row[4]}
        if not block:
            block = stored_payload
        if not block:
            raise HTTPException(status_code=404, detail="Source block not found and no backup available")

        new_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO template_builder.blocks_library
                    (block_id, name, description, block_json, tags, industry,
                     created_by, created_at, updated_at)
                VALUES
                    (CAST(:id AS uuid), :name, :description,
                     CAST(:block_json AS jsonb), :tags, :industry,
                     :created_by, NOW(), NOW())
            """), {
                "id":          new_id,
                "name":        f"{block.get('name','Block')} (from Marketplace)",
                "description": block.get("description") or "",
                "block_json":  json_dumps(block.get("block_json") or {}),
                "tags":        block.get("tags") or [],
                "industry":    block.get("industry"),
                "created_by":  "dev_user",
            })
            await conn.execute(text("""
                UPDATE template_builder.marketplace_items
                SET downloads = downloads + 1
                WHERE item_id = CAST(:item_id AS uuid)
            """), {"item_id": item_id})
        return {"detail": "Block imported to your library successfully", "type": "block",
                "new_id": new_id, "name": f"{block.get('name')} (from Marketplace)"}

    # ── PLACEHOLDER ───────────────────────────────────────────────
    elif item_type == "placeholder":
        ph = None
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT name, sql_text, sample_value, generation_mode,
                       datasource_id, format_json, value_type, cardinality, classification
                FROM template_builder.placeholders_registry
                WHERE registry_id = CAST(:id AS uuid)
            """), {"id": source_id})
            row = result.fetchone()
            if row:
                ph = {
                    "name": row[0], "sql_text": row[1], "sample_value": row[2],
                    "generation_mode": row[3] or "manual_sql",
                    "datasource_id": row[4],  # integer
                    "format_json": row[5] or {}, "value_type": row[6] or "string",
                    "cardinality": row[7] or "scalar", "classification": row[8] or "internal",
                }
        if not ph:
            ph = stored_payload
        if not ph:
            raise HTTPException(status_code=404, detail="Source placeholder not found and no backup available")

        # Check if already exists
        async with engine.connect() as conn:
            existing = await conn.execute(text("""
                SELECT registry_id FROM template_builder.placeholders_registry
                WHERE name = :name
            """), {"name": ph.get("name")})
            existing_row = existing.fetchone()

        if existing_row:
            async with engine.begin() as conn:
                await conn.execute(text("""
                    UPDATE template_builder.marketplace_items
                    SET downloads = downloads + 1
                    WHERE item_id = CAST(:item_id AS uuid)
                """), {"item_id": item_id})
            return {
                "detail": f"Placeholder '{ph.get('name')}' is already in your registry",
                "type": "placeholder", "new_id": str(existing_row[0]),
                "name": ph.get("name"), "already_exists": True,
            }

        new_id = str(uuid.uuid4())
        async with engine.begin() as conn:
            await conn.execute(text("""
                INSERT INTO template_builder.placeholders_registry
                    (registry_id, name, sql_text, sample_value,
                     generation_mode, datasource_id, format_json,
                     value_type, cardinality, classification,
                     is_active, created_by, created_at, updated_at)
                VALUES
                    (CAST(:id AS uuid), :name, :sql_text, :sample_value,
                     :generation_mode, :datasource_id, CAST(:format_json AS jsonb),
                     :value_type, :cardinality, :classification,
                     TRUE, :created_by, NOW(), NOW())
            """), {
                "id":              new_id,
                "name":            ph.get("name"),
                "sql_text":        ph.get("sql_text"),
                "sample_value":    ph.get("sample_value"),
                "generation_mode": ph.get("generation_mode") or "manual_sql",
                "datasource_id":   ph.get("datasource_id"),  # integer — no cast needed
                "format_json":     json_dumps(ph.get("format_json") or {}),
                "value_type":      ph.get("value_type") or "string",
                "cardinality":     ph.get("cardinality") or "scalar",
                "classification":  ph.get("classification") or "internal",
                "created_by":      "dev_user",
            })
            await conn.execute(text("""
                UPDATE template_builder.marketplace_items
                SET downloads = downloads + 1
                WHERE item_id = CAST(:item_id AS uuid)
            """), {"item_id": item_id})
        return {"detail": "Placeholder imported to your registry successfully",
                "type": "placeholder", "new_id": new_id, "name": ph.get("name")}

    raise HTTPException(status_code=400, detail=f"Unknown item type: {item_type}")


# =============================================================================
# DELETE /{item_id}
# =============================================================================

@router.delete("/{item_id}", status_code=204)
async def delete_marketplace_item(item_id: str, request: Request):
    engine = get_engine(request)
    item_id = validate_uuid(item_id, "item_id")
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            DELETE FROM template_builder.marketplace_items
            WHERE item_id = CAST(:item_id AS uuid)
        """), {"item_id": item_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Item not found")