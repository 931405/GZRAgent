"""
preferences.py — 用户偏好 API
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from src.utils.user_memory import load_preferences, save_preferences, update_preference, add_to_list

router = APIRouter()


class PreferencesUpdate(BaseModel):
    research_field: Optional[str] = None
    writing_style: Optional[str] = None
    frequent_keywords: Optional[List[str]] = None
    preferred_journals: Optional[List[str]] = None
    avoided_patterns: Optional[List[str]] = None
    custom_instructions: Optional[str] = None
    notes: Optional[str] = None


@router.get("/")
def get_preferences():
    return load_preferences()


@router.post("/")
def set_preferences(data: PreferencesUpdate):
    prefs = load_preferences()
    update_dict = data.model_dump(exclude_none=True)
    prefs.update(update_dict)
    ok = save_preferences(prefs)
    return {"status": "ok" if ok else "error", "preferences": prefs}


@router.post("/keyword")
def add_keyword(keyword: str):
    ok = add_to_list("frequent_keywords", keyword)
    return {"status": "ok" if ok else "error"}
