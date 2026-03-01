"""
src/skills/__init__.py

Skills 包入口。导出核心加载器 API。
"""
from src.skills.skill_loader import (
    discover_skills,
    get_skill_index,
    activate_skill,
    load_reference,
    build_skills_index_prompt,
    match_skills,
    SkillMeta,
)

__all__ = [
    "discover_skills",
    "get_skill_index",
    "activate_skill",
    "load_reference",
    "build_skills_index_prompt",
    "match_skills",
    "SkillMeta",
]
