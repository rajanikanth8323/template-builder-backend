# backend/src/api/datasources.py
import json
import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()
logger = logging.getLogger(__name__)


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


# -----------------------------------------------------------------
# GET /v1/datasources — list all datasources
# -----------------------------------------------------------------

@router.get("/datasources", response_model=list)
async def list_datasources(request: Request) -> list:
    """List all available datasources from eivs.datasources."""
    engine = get_engine(request)
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT datasource_id, name, datasource_type, connection_key, description, is_active
            FROM eivs.datasources
            WHERE is_active = true
            ORDER BY datasource_id
        """))
        rows = result.fetchall()
        return [
            {
                "datasource_id": r[0],
                "name": r[1],
                "datasource_type": r[2],
                "connection_key": r[3],
                "description": r[4],
                "is_active": r[5],
            }
            for r in rows
        ]


# -----------------------------------------------------------------
# POST /v1/datasources/test-sql — run SQL and return value(s)
# -----------------------------------------------------------------

class TestSqlRequest(BaseModel):
    datasource_id: int
    sql_text: str
    cardinality: str = "scalar"  # scalar | list | table


@router.post("/datasources/test-sql", response_model=dict)
async def test_sql(payload: TestSqlRequest, request: Request) -> dict:
    """
    Run a SQL query against a datasource and return value(s).
    - scalar: returns first column of first row as a string
    - list:   returns all columns of all rows joined as 'col1 | col2'
    - table:  returns all rows and columns as a JSON array-of-objects
    """
    engine = get_engine(request)

    # Get connection URL from eivs.datasources
    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT connection_key FROM eivs.datasources
            WHERE datasource_id = :id AND is_active = true
        """), {"id": payload.datasource_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Datasource {payload.datasource_id} not found")
        connection_key = row[0]

    # Run SQL against the datasource
    try:
        conn_pg = await asyncpg.connect(connection_key)
        try:
            if payload.cardinality == "scalar":
                # First column of first row only
                db_row = await conn_pg.fetchrow(payload.sql_text)
                if db_row:
                    value = list(db_row.values())[0]
                    return {"value": str(value) if value is not None else "", "error": None}
                return {"value": "", "error": "Query returned no rows"}

            elif payload.cardinality == "list":
                # All columns of all rows joined as "col1 | col2"
                db_rows = await conn_pg.fetch(payload.sql_text)
                if db_rows:
                    values = []
                    for r in db_rows:
                        combined = " | ".join(str(c) for c in r.values() if c is not None)
                        values.append(combined)
                    return {"value": json.dumps(values), "error": None}
                return {"value": "[]", "error": "Query returned no rows"}

            elif payload.cardinality == "table":
                # All rows, all columns as JSON array-of-objects
                db_rows = await conn_pg.fetch(payload.sql_text)
                if db_rows:
                    result = [
                        {k: str(v) if v is not None else None for k, v in dict(r).items()}
                        for r in db_rows
                    ]
                    return {"value": json.dumps(result), "error": None}
                return {"value": "[]", "error": "Query returned no rows"}

            else:
                # Fallback to scalar
                db_row = await conn_pg.fetchrow(payload.sql_text)
                if db_row:
                    value = list(db_row.values())[0]
                    return {"value": str(value) if value is not None else "", "error": None}
                return {"value": "", "error": "Query returned no rows"}

        finally:
            await conn_pg.close()

    except Exception as exc:
        logger.error(f"test-sql failed: {exc}")
        return {"value": "", "error": str(exc)}