# backend/src/api/render.py
from fastapi import APIRouter, HTTPException, Body, Request
from typing import Dict, List

router = APIRouter()

@router.post("/generate", response_model=Dict)
def generate_document(payload: Dict = Body(...)):
    """Legacy endpoint — document generation now handled by /v1/documents/generate"""
    placeholder_ids: List[int] = payload.get("placeholder_ids", [])
    if not placeholder_ids:
        raise HTTPException(status_code=400, detail="No placeholder IDs supplied")
    return {"resolved": {}, "message": "Use /v1/documents/generate instead"}