# backend/src/api/blocks.py
# Blocks library — matches actual DB schema (no 'type' column, type is in block_json)

import uuid
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/blocks", tags=["blocks"])


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


class BlockCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str  # stored in block_json, not as a column
    block_json: Dict[str, Any]
    tags: List[str] = []
    industry: Optional[str] = None
    description: Optional[str] = None


class BlockResponse(BaseModel):
    block_id: str
    name: str
    type: str
    block_json: Dict[str, Any]
    tags: List[str]
    industry: Optional[str]
    created_at: str


def row_to_block(row) -> Dict[str, Any]:
    block_json = row[2]
    if isinstance(block_json, str):
        block_json = json.loads(block_json)
    return {
        "block_id":   str(row[0]),
        "name":       row[1],
        "type":       block_json.get("type", "text"),  # type comes from block_json
        "block_json": block_json,
        "tags":       row[3] or [],
        "industry":   row[4],
        "created_at": row[5].isoformat() if row[5] else "",
    }


# GET / — list all blocks
@router.get("/", response_model=List[BlockResponse])
async def list_blocks(
    request: Request,
    industry: Optional[str] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
):
    engine = get_engine(request)
    sql = """
        SELECT block_id, name, block_json, tags, industry, created_at
        FROM template_builder.blocks_library
        WHERE 1=1
    """
    params: Dict[str, Any] = {}

    if industry:
        sql += " AND industry = :industry"
        params["industry"] = industry
    if tag:
        sql += " AND :tag = ANY(tags)"
        params["tag"] = tag
    if search:
        sql += " AND (name ILIKE :search)"
        params["search"] = f"%{search}%"

    sql += " ORDER BY created_at DESC"

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    return [row_to_block(r) for r in rows]


# POST / — save a block to library
@router.post("/", response_model=BlockResponse, status_code=201)
async def create_block(block: BlockCreate, request: Request):
    engine = get_engine(request)
    block_id = str(uuid.uuid4())

    # Ensure type is in block_json
    block_data = dict(block.block_json)
    block_data["type"] = block.type

    async with engine.begin() as conn:
        await conn.execute(text("""
            INSERT INTO template_builder.blocks_library
                (block_id, name, description, block_json, tags, industry, created_by, created_at, updated_at)
            VALUES
                (CAST(:block_id AS uuid), :name, :description,
                 CAST(:block_json AS jsonb), :tags, :industry, :created_by, NOW(), NOW())
        """), {
            "block_id":    block_id,
            "name":        block.name,
            "description": block.description or "",
            "block_json":  json.dumps(block_data),
            "tags":        block.tags,
            "industry":    block.industry,
            "created_by":  "dev_user",
        })

        result = await conn.execute(text("""
            SELECT block_id, name, block_json, tags, industry, created_at
            FROM template_builder.blocks_library
            WHERE block_id = CAST(:block_id AS uuid)
        """), {"block_id": block_id})
        row = result.fetchone()

    return row_to_block(row)


# GET /{block_id}
@router.get("/{block_id}", response_model=BlockResponse)
async def get_block(block_id: str, request: Request):
    try:
        uuid.UUID(block_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    engine = get_engine(request)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT block_id, name, block_json, tags, industry, created_at
            FROM template_builder.blocks_library
            WHERE block_id = CAST(:block_id AS uuid)
        """), {"block_id": block_id})
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Block not found")
    return row_to_block(row)


# DELETE /{block_id}
@router.delete("/{block_id}", status_code=204)
async def delete_block(block_id: str, request: Request):
    engine = get_engine(request)
    async with engine.begin() as conn:
        result = await conn.execute(text("""
            DELETE FROM template_builder.blocks_library
            WHERE block_id = CAST(:block_id AS uuid)
        """), {"block_id": block_id})
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Block not found")