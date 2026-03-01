"""
skill_loader.py — 技能渐进式加载引擎

借鉴 AgentSkills/OpenClaw 的 Skills 机制，实现：
  1. Discover: 扫描 src/skills/ 目录，找到每个子目录中的 SKILL.md
  2. Index:    仅加载 YAML frontmatter 中的 name/description/triggers 作为元数据
  3. Activate: 按需加载 SKILL.md 正文内容（减少 Prompt 初始 Token 消耗）
  4. 生成紧凑的 Skills 清单 XML，供 Decision Agent 使用

目录结构约定:
  src/skills/
    ├── formula_skill/
    │   └── SKILL.md          # YAML frontmatter + Markdown 指令
    ├── diagram_skill/
    │   └── SKILL.md
    └── search_skill/
        ├── SKILL.md
        └── references/
            └── section_search_intent.md
"""
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ============= 数据结构 =============

@dataclass
class SkillMeta:
    """Skill 的元数据索引项（轻量级，启动时加载）"""
    name: str
    description: str
    agent_type: str
    triggers: List[str] = field(default_factory=list)
    requires: Dict[str, list] = field(default_factory=dict)
    path: str = ""             # SKILL.md 所在目录
    _body_cache: Optional[str] = field(default=None, repr=False)


# ============= YAML Frontmatter 解析 =============

def _parse_frontmatter(content: str) -> Dict:
    """
    解析 SKILL.md 开头的 YAML frontmatter (--- ... ---) 块。
    轻量实现：不依赖 PyYAML，简单地逐行解析 key: value。
    支持多行 description（用 > 折叠标记）和列表（- item）。
    """
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return {}

    raw_yaml = match.group(1)
    result = {}
    current_key = None
    current_list = None

    for line in raw_yaml.split("\n"):
        stripped = line.strip()

        # 列表项
        if stripped.startswith("- ") and current_key:
            item = stripped[2:].strip().strip('"').strip("'")
            if current_list is not None:
                current_list.append(item)
            continue

        # 顶级 key: value
        kv_match = re.match(r'^(\w[\w_-]*):\s*(.*)', line)
        if kv_match:
            key = kv_match.group(1)
            val = kv_match.group(2).strip()

            # 保存上一个列表
            if current_list is not None and current_key:
                result[current_key] = current_list

            current_key = key
            current_list = None

            if val == ">" or val == "|":
                # 多行文本，后续行拼接
                result[key] = ""
            elif val.startswith("[") and val.endswith("]"):
                # 内联列表 [a, b, c]
                items = [i.strip().strip('"').strip("'") for i in val[1:-1].split(",")]
                result[key] = [i for i in items if i]
            elif val == "":
                # 可能是列表的开头
                current_list = []
            else:
                result[key] = val.strip('"').strip("'")
        elif current_key and current_key in result and isinstance(result[current_key], str):
            # 多行文本的续行（> 标记）
            if stripped:
                result[current_key] = (result[current_key] + " " + stripped).strip()

    # 保存最后一个列表
    if current_list is not None and current_key:
        result[current_key] = current_list

    return result


def _parse_body(content: str) -> str:
    """提取 SKILL.md 中 --- frontmatter --- 之后的 Markdown 正文"""
    match = re.match(r'^---\s*\n.*?\n---\s*\n', content, re.DOTALL)
    if match:
        return content[match.end():].strip()
    return content.strip()


# ============= 核心引擎 =============

_skill_index: Dict[str, SkillMeta] = {}


def discover_skills(skills_dirs: Optional[List[str]] = None) -> Dict[str, SkillMeta]:
    """
    发现并索引所有 Skills（Phase 1: Discover + Index）
    
    只加载 YAML frontmatter 中的元数据，不加载正文内容。
    
    Args:
        skills_dirs: 技能目录列表，默认为 src/skills/
    
    Returns:
        {skill_name: SkillMeta} 字典
    """
    global _skill_index

    if skills_dirs is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        skills_dirs = [os.path.join(base, "skills")]

    index = {}
    for skills_dir in skills_dirs:
        if not os.path.isdir(skills_dir):
            continue
        for entry in os.listdir(skills_dir):
            skill_path = os.path.join(skills_dir, entry)
            skill_md = os.path.join(skill_path, "SKILL.md")
            if not os.path.isfile(skill_md):
                continue

            try:
                with open(skill_md, "r", encoding="utf-8") as f:
                    content = f.read()

                meta = _parse_frontmatter(content)
                name = meta.get("name", entry)
                desc = meta.get("description", "")
                agent_type = meta.get("agent_type", name)

                triggers = meta.get("triggers", [])
                if isinstance(triggers, str):
                    triggers = [triggers]

                requires = meta.get("requires", {})
                if isinstance(requires, str):
                    requires = {"tools": [requires]}

                index[name] = SkillMeta(
                    name=name,
                    description=desc,
                    agent_type=agent_type,
                    triggers=triggers,
                    requires=requires,
                    path=skill_path,
                )
            except Exception as e:
                print(f"[SkillLoader] 加载 Skill '{entry}' 失败: {e}")

    _skill_index = index
    print(f"[SkillLoader] 发现 {len(index)} 个 Skills: {list(index.keys())}")
    return index


def get_skill_index() -> Dict[str, SkillMeta]:
    """获取当前的 Skill 索引（如果尚未初始化则自动发现）"""
    if not _skill_index:
        discover_skills()
    return _skill_index


def activate_skill(skill_name: str) -> Optional[str]:
    """
    激活指定 Skill — 加载 SKILL.md 正文内容
    
    这是渐进式披露的第二层：只有在确认需要使用某个 Skill 时才加载其完整指令。
    
    Args:
        skill_name: Skill 名称
    
    Returns:
        SKILL.md 的 Markdown 正文内容，或 None
    """
    index = get_skill_index()
    skill = index.get(skill_name)
    if not skill:
        print(f"[SkillLoader] Skill '{skill_name}' 不存在")
        return None

    if skill._body_cache is not None:
        return skill._body_cache

    skill_md = os.path.join(skill.path, "SKILL.md")
    try:
        with open(skill_md, "r", encoding="utf-8") as f:
            content = f.read()
        body = _parse_body(content)
        skill._body_cache = body
        print(f"[SkillLoader] 已激活 Skill '{skill_name}' (正文 {len(body)} 字符)")
        return body
    except Exception as e:
        print(f"[SkillLoader] 激活 Skill '{skill_name}' 失败: {e}")
        return None


def load_reference(skill_name: str, ref_path: str) -> Optional[str]:
    """
    加载 Skill 的参考资料文件（渐进式披露第三层）
    
    Args:
        skill_name: Skill 名称
        ref_path: 相对于 Skill 目录的路径，如 "references/section_search_intent.md"
    """
    index = get_skill_index()
    skill = index.get(skill_name)
    if not skill:
        return None

    full_path = os.path.join(skill.path, ref_path)
    if not os.path.isfile(full_path):
        print(f"[SkillLoader] Reference '{ref_path}' 不存在于 Skill '{skill_name}'")
        return None

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[SkillLoader] 加载 Reference 失败: {e}")
        return None


# ============= Skills 清单 XML（注入系统提示词） =============

def build_skills_index_prompt() -> str:
    """
    构建紧凑的 Skills 清单（XML 格式），用于注入到 Decision Agent 的系统提示词中。
    
    仅包含 name + description + agent_type + triggers，不包含 SKILL.md 正文。
    Token 开销极低，让模型在规划阶段知道"有哪些技能可用"。
    """
    index = get_skill_index()
    if not index:
        return ""

    lines = ["<available_skills>"]
    for name, skill in index.items():
        triggers_str = ", ".join(skill.triggers) if skill.triggers else ""
        lines.append(f'  <skill name="{name}" agent_type="{skill.agent_type}">')
        lines.append(f'    <description>{skill.description}</description>')
        if triggers_str:
            lines.append(f'    <triggers>{triggers_str}</triggers>')
        lines.append(f'  </skill>')
    lines.append("</available_skills>")

    return "\n".join(lines)


def match_skills(user_message: str) -> List[SkillMeta]:
    """
    基于触发词匹配可用 Skills（简单关键词匹配，后续可升级为 embedding 匹配）
    
    Args:
        user_message: 用户输入/任务描述
    
    Returns:
        匹配到的 SkillMeta 列表
    """
    index = get_skill_index()
    matched = []
    msg_lower = user_message.lower()

    for name, skill in index.items():
        for trigger in skill.triggers:
            if trigger.lower() in msg_lower:
                matched.append(skill)
                break

    return matched
