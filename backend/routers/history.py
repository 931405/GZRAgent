"""
history.py — 历史记录 API
"""
from fastapi import APIRouter
from pydantic import BaseModel
from src.utils.history_manager import load_history_list, load_history_data, save_history

router = APIRouter()


@router.get("/list")
def list_history():
    return {"files": load_history_list()}


@router.get("/{filename}")
def get_history(filename: str):
    data = load_history_data(filename)
    if data is None:
        return {"error": "not found"}
    return data


class SaveRequest(BaseModel):
    graph_state: dict


@router.post("/save")
def save(req: SaveRequest):
    p_type = req.graph_state.get("project_type", "")
    p_name = req.graph_state.get("research_topic", "")[:10]
    path = save_history(req.graph_state, f"{p_type}_{p_name}")
    return {"path": path}
