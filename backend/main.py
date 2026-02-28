"""
FastAPI Backend — NSFC 智能撰写系统
运行: uvicorn backend.main:app --reload --port 8000
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from backend.routers import workflow, knowledge, history, template, export as export_router, preferences

app = FastAPI(title="NSFC Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflow.router,  prefix="/api/workflow",  tags=["workflow"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(history.router,   prefix="/api/history",   tags=["history"])
app.include_router(template.router,  prefix="/api/templates", tags=["templates"])
app.include_router(export_router.router, prefix="/api/export", tags=["export"])
app.include_router(preferences.router, prefix="/api/preferences", tags=["preferences"])

@app.get("/")
def root():
    return {"status": "ok", "service": "NSFC Agent API"}
