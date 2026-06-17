# backend/src/api/ai.py
#
# AI tools for template builder — Generate, Polish, Translate, Check
#
# Generate  → Cohere API  (unchanged)
# Polish    → Cohere API  (unchanged)
# Check     → Cohere API  (unchanged)
# Translate → Google Cloud Translation API v2  ← CHANGED from Cohere

import os
import re
import json
import logging
import httpx
import asyncpg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter()
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
COHERE_API_KEY       = os.getenv("COHERE_API_KEY", "")
GOOGLE_TRANSLATE_KEY = os.getenv("GOOGLE_TRANSLATE_KEY", "")

# If set, call_llm() routes there instead of Cohere.
# e.g. LLM_ENDPOINT=http://llm-service:8000/generate
LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "")

# Google Translate v2 REST endpoint
GOOGLE_TRANSLATE_URL = "https://translation.googleapis.com/language/translate/v2"

# UI language name → Google language code
LANGUAGE_CODE_MAP = {
    "Hindi":    "hi",
    "Tamil":    "ta",
    "Telugu":   "te",
    "Kannada":  "kn",
    "Marathi":  "mr",
    "Urdu":     "ur",
    "French":   "fr",
    "Spanish":  "es",
    "Arabic":   "ar",
    "German":   "de",
    "English":  "en",
    "Bengali":  "bn",
    "Gujarati": "gu",
    "Punjabi":  "pa",
    "Malayalam":"ml",
}


def get_engine(request: Request) -> AsyncEngine:
    engine = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(status_code=500, detail="DB engine not initialized")
    return engine


# =============================================================================
# call_llm() — used by Generate, Polish, Check  (UNCHANGED)
# =============================================================================
async def call_llm(prompt: str, system_hint: str = "") -> str:

    # ── Route 1: LLM microservice (future) ────────────────────────
    if LLM_ENDPOINT:
        logger.info(f"Routing to LLM microservice: {LLM_ENDPOINT}")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    LLM_ENDPOINT,
                    json={"prompt": prompt, "system": system_hint},
                    headers={"Content-Type": "application/json"},
                )
            if response.status_code != 200:
                raise ValueError(f"LLM service returned HTTP {response.status_code}")
            data = response.json()
            result = data.get("text") or data.get("response") or data.get("output") or ""
            if not result:
                raise ValueError("LLM service returned empty response")
            return result
        except Exception as exc:
            logger.error(f"LLM microservice error: {exc}")
            raise ValueError(f"LLM service error: {str(exc)}")

    # ── Route 2: Cohere API (current) ─────────────────────────────
    if not COHERE_API_KEY:
        raise ValueError(
            "COHERE_API_KEY is not set. Add it to your .env file: COHERE_API_KEY=your-key"
        )

    logger.info("Routing to Cohere API")

    full_prompt = f"{system_hint}\n\n{prompt}" if system_hint else prompt

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.cohere.com/v2/chat",
                headers={
                    "Authorization": f"Bearer {COHERE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "command-r-plus-08-2024",
                    "messages": [
                        {"role": "user", "content": full_prompt}
                    ],
                },
            )

        if response.status_code != 200:
            error_data = response.json()
            msg = error_data.get("message") or f"Cohere API error HTTP {response.status_code}"
            raise ValueError(msg)

        data = response.json()
        result = (
            data.get("message", {})
                .get("content", [{}])[0]
                .get("text", "")
        )
        if not result:
            raise ValueError("Cohere returned empty response")

        logger.info(f"LLM response: {result[:100]}...")
        return result.strip()

    except httpx.TimeoutException:
        raise ValueError("LLM request timed out. Please try again.")
    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"Cohere API error: {exc}")
        raise ValueError(f"LLM error: {str(exc)}")


# =============================================================================
# call_google_translate() — used ONLY by the Translate tool
#
# Problem: Google Translate will break {{placeholder}} tokens.
# Solution:
#   1. Replace every {{token}} with a safe sentinel  e.g. __PH_0__
#   2. Send sentinel text to Google Translate
#   3. Put the original {{tokens}} back in the translated result
# =============================================================================
async def call_google_translate(content: str, target_language: str) -> str:
    if not GOOGLE_TRANSLATE_KEY:
        raise ValueError(
            "GOOGLE_TRANSLATE_KEY is not set. "
            "Add GOOGLE_TRANSLATE_KEY=your-key to your .env file."
        )

    # Step 1: extract all {{placeholders}} and replace with sentinels
    placeholders = re.findall(r'\{\{[^}]+\}\}', content)
    protected = content
    for i, ph in enumerate(placeholders):
        protected = protected.replace(ph, f"__PH_{i}__", 1)

    logger.info(f"Translating to '{target_language}'. Protected placeholders: {placeholders}")

    # Step 2: resolve language name → language code
    lang_code = LANGUAGE_CODE_MAP.get(target_language, target_language.lower())

    # Step 3: call Google Translate v2
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                GOOGLE_TRANSLATE_URL,
                params={"key": GOOGLE_TRANSLATE_KEY},
                json={
                    "q": protected,
                    "target": lang_code,
                    "source": "en",
                    "format": "text",
                },
                headers={"Content-Type": "application/json"},
            )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = (
                error_data.get("error", {}).get("message")
                or f"Google Translate API error HTTP {response.status_code}"
            )
            raise ValueError(error_msg)

        data = response.json()
        translated = data["data"]["translations"][0]["translatedText"]
        logger.info(f"Google Translate result: {translated[:100]}...")

    except httpx.TimeoutException:
        raise ValueError("Google Translate request timed out. Please try again.")
    except ValueError:
        raise
    except Exception as exc:
        logger.error(f"Google Translate error: {exc}")
        raise ValueError(f"Translation error: {str(exc)}")

    # Step 4: restore {{placeholders}} — Google may add spaces around sentinels
    for i, ph in enumerate(placeholders):
        translated = re.sub(rf'\s*__PH_{i}__\s*', ph, translated)

    return translated.strip()


# =============================================================================
# AI Tool endpoint — single POST for all 4 tools
# =============================================================================

class AIToolRequest(BaseModel):
    tool: str                        # "generate" | "polish" | "translate" | "check"
    content: Optional[str] = ""     # selected block content (polish/translate/check)
    description: Optional[str] = "" # user description (generate)
    tone: Optional[str] = "Formal"  # for polish
    language: Optional[str] = ""    # for translate
    all_blocks: Optional[str] = ""  # all text blocks joined (check)

class AIToolResponse(BaseModel):
    result: str
    error: str = ""


@router.post("/ai/tools", response_model=AIToolResponse)
async def ai_tools(payload: AIToolRequest) -> AIToolResponse:
    """
    Single endpoint for all 4 AI tools.

    generate  → Cohere API
    polish    → Cohere API
    check     → Cohere API
    translate → Google Cloud Translation API v2  (placeholders are protected)
    """
    try:
        # ── GENERATE ──────────────────────────────────────────────
        if payload.tool == "generate":
            if not payload.description:
                return AIToolResponse(result="", error="Description is required")

            prompt = f"""A user wants to create a document template. Generate the TEXT CONTENT for a single text block based on this description:
"{payload.description}"

Rules:
- Use {{{{placeholder_name}}}} syntax for dynamic values (e.g. {{{{customer_name}}}}, {{{{loan_number}}}}, {{{{amount}}}}, {{{{date}}}})
- Write professional, clear content suitable for BFSI or medical industry
- Include relevant placeholders based on context
- Return ONLY the text content, no explanations or preamble
- Keep it concise (2-5 lines)"""

            system = "You are a document template builder assistant for BFSI and medical industries. You produce clean, professional document content with placeholder tokens in {{placeholder_name}} format."
            result = await call_llm(prompt, system)

        # ── POLISH ────────────────────────────────────────────────
        elif payload.tool == "polish":
            if not payload.content:
                return AIToolResponse(result="", error="No block content provided")

            prompt = f"""Rewrite the following document template text in a {payload.tone} tone.
Keep all {{{{placeholder}}}} tokens exactly as they are — do NOT modify them.
Return ONLY the rewritten text, no explanations.

Original text:
{payload.content}"""

            system = "You are a professional document editor. You rewrite content in the requested tone while preserving all {{placeholder}} tokens exactly as-is."
            result = await call_llm(prompt, system)

        # ── TRANSLATE — Google Translate API ──────────────────────
        elif payload.tool == "translate":
            if not payload.content:
                return AIToolResponse(result="", error="No block content provided")
            if not payload.language:
                return AIToolResponse(result="", error="Target language is required")

            result = await call_google_translate(payload.content, payload.language)

        # ── CHECK ─────────────────────────────────────────────────
        elif payload.tool == "check":
            if not payload.all_blocks:
                return AIToolResponse(result="", error="No template content to check")

            prompt = f"""Analyze the following template blocks and identify any issues:
- Broken or malformed {{{{placeholder}}}} tokens (e.g. missing closing braces)
- Grammar or spelling errors
- Inconsistent formatting
- Missing important fields for a professional document
- Unprofessional language

Template content:
{payload.all_blocks}

Return a numbered list of issues found. If no issues, say "✓ No anomalies found. Template looks good!"
Be concise — max 2 lines per issue."""

            system = "You are a document quality checker for BFSI and medical document templates."
            result = await call_llm(prompt, system)

        else:
            return AIToolResponse(result="", error=f"Unknown tool: {payload.tool}")

        return AIToolResponse(result=result)

    except ValueError as exc:
        return AIToolResponse(result="", error=str(exc))
    except Exception as exc:
        logger.error(f"AI tool '{payload.tool}' failed: {exc}")
        return AIToolResponse(result="", error=f"AI error: {str(exc)}")


# =============================================================================
# SQL generation endpoint (unchanged)
# =============================================================================

LLM_WEBHOOK_URL = os.getenv(
    "LLM_WEBHOOK_URL",
    "http://api:8080/v1/webhook/generate-sql"
)

class GenerateSQLRequest(BaseModel):
    prompt: str
    datasource_id: int = 1
    cardinality: str = "scalar"

class GenerateSQLResponse(BaseModel):
    sql: str
    value: str
    error: str = ""

@router.post("/ai/generate-sql", response_model=GenerateSQLResponse)
async def generate_sql(payload: GenerateSQLRequest, request: Request) -> GenerateSQLResponse:
    engine = get_engine(request)

    async with engine.connect() as conn:
        result = await conn.execute(text("""
            SELECT connection_key, name FROM eivs.datasources
            WHERE datasource_id = :id AND is_active = true
        """), {"id": payload.datasource_id})
        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Datasource not found")
        connection_url, ds_name = row[0], row[1]

    logger.info(f"Generating SQL for prompt: '{payload.prompt}' on datasource: {ds_name}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            webhook_response = await client.post(
                LLM_WEBHOOK_URL,
                json={"prompt": payload.prompt, "datasource_schema": "", "cardinality": payload.cardinality}
            )
            webhook_data = webhook_response.json()
    except Exception as exc:
        return GenerateSQLResponse(sql="", value="", error=f"Webhook error: {str(exc)}")

    sql = webhook_data.get("sql", "")
    webhook_error = webhook_data.get("error", "")
    if webhook_error or not sql:
        return GenerateSQLResponse(sql="", value="", error=webhook_error or "No SQL generated")

    try:
        conn_pg = await asyncpg.connect(connection_url)
        try:
            if payload.cardinality == "scalar":
                db_row = await conn_pg.fetchrow(sql)
                value = str(list(db_row.values())[0]) if db_row and db_row.values() else ""
            else:
                db_rows = await conn_pg.fetch(sql)
                value = json.dumps([dict(r) for r in db_rows], default=str) if db_rows else "[]"
        finally:
            await conn_pg.close()
    except Exception as exc:
        return GenerateSQLResponse(sql=sql, value="", error=f"SQL error: {str(exc)}")

    return GenerateSQLResponse(sql=sql, value=value)