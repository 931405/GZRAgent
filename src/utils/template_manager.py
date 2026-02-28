"""
NSFC 申请书模板管理器
支持预设模板和自定义模板的管理
"""
import json
import os

TEMPLATE_DIR = "data/templates"

KNOWN_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]

# ========== 内置模板 ==========

BUILTIN_TEMPLATES = {
    "通用科研模板": {
        "description": "适用于大多数基础研究方向的通用框架",
        "sections": {
            "立项依据": "请围绕以下结构撰写立项依据：\n1. 研究背景与意义（国际/国内现状）\n2. 国内外研究进展与关键科学问题\n3. 本项目拟解决的关键问题\n4. 参考文献",
            "研究目标与内容": "请围绕以下结构撰写：\n1. 研究目标（总目标+分目标）\n2. 研究内容（分条列出2-4项核心研究内容）\n3. 拟解决的关键科学问题",
            "研究方案与可行性": "请围绕以下结构撰写：\n1. 研究方案（技术路线图描述）\n2. 实验方案或计算方案\n3. 可行性分析（理论依据、技术方法、研究条件）\n4. 项目的创新性",
            "特色与创新": "请简明扼要地列出本项目的2-3项特色与创新之处（每项不超过200字）。",
            "研究基础": "请围绕以下结构撰写：\n1. 工作基础（与本项目相关的前期研究成果）\n2. 工作条件（实验设备、计算资源等）\n3. 申请人简历与代表性成果"
        }
    },
    "AI+交叉学科模板": {
        "description": "适用于人工智能与其他学科交叉的项目",
        "sections": {
            "立项依据": "请围绕以下结构撰写：\n1. 交叉学科背景与痛点分析\n2. AI 技术在该领域的应用现状与瓶颈\n3. 数据驱动与知识驱动方法的融合趋势\n4. 本项目的核心切入点",
            "研究目标与内容": "请围绕以下结构撰写：\n1. 总体目标：构建什么样的AI系统/方法\n2. 研究内容：数据层、模型层、应用层\n3. 拟解决的关键技术瓶颈",
            "研究方案与可行性": "请围绕以下结构撰写：\n1. 数据获取与预处理方案\n2. 模型架构设计\n3. 训练与验证策略\n4. 基准对比实验设计\n5. 可行性论证",
            "特色与创新": "请从以下角度阐述创新性：\n1. 方法论创新（新算法/新架构）\n2. 应用场景创新（首次将AI应用于...）\n3. 数据/知识融合创新",
            "研究基础": "请强调：\n1. 团队在AI和交叉领域的研究积累\n2. 已有的数据资源和算力条件\n3. 代表性论文和项目经验"
        }
    },
    "药物化学模板": {
        "description": "适用于药物设计、药物化学相关研究",
        "sections": {
            "立项依据": "请围绕以下结构撰写：\n1. 疾病背景与临床需求\n2. 靶点研究进展与构效关系\n3. 现有药物/先导化合物的局限性\n4. 本项目的分子设计策略",
            "研究目标与内容": "请围绕以下结构撰写：\n1. 总体目标（设计并优化系列候选化合物）\n2. 分子设计策略\n3. 合成路线规划\n4. 生物活性评价体系",
            "研究方案与可行性": "请围绕以下结构撰写：\n1. 计算辅助药物设计方案\n2. 化学合成方案\n3. 体外/体内活性评价方案\n4. ADMET性质评估\n5. 技术路线图",
            "特色与创新": "请阐述：\n1. 分子设计理念创新\n2. 合成方法学创新\n3. 评价体系创新",
            "研究基础": "请强调：\n1. 课题组在药物化学领域的研究积累\n2. 化学合成与生物评价平台\n3. 已发表的相关论文和专利"
        }
    }
}


def get_template_list() -> list:
    """获取所有可用模板（内置 + 自定义）"""
    templates = list(BUILTIN_TEMPLATES.keys())
    
    # 加载自定义模板
    if os.path.exists(TEMPLATE_DIR):
        for fname in os.listdir(TEMPLATE_DIR):
            if fname.endswith(".json"):
                name = fname.replace(".json", "")
                if name not in templates:
                    templates.append(f"[自定义] {name}")
    
    return templates


def get_template(name: str) -> dict:
    """获取指定模板的内容"""
    # 先查内置
    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]
    
    # 再查自定义
    clean_name = name.replace("[自定义] ", "")
    custom_path = os.path.join(TEMPLATE_DIR, f"{clean_name}.json")
    if os.path.exists(custom_path):
        with open(custom_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    return None


def save_custom_template(name: str, description: str, sections: dict):
    """保存自定义模板"""
    if not os.path.exists(TEMPLATE_DIR):
        os.makedirs(TEMPLATE_DIR)
    
    template = {
        "description": description,
        "sections": sections
    }
    
    filepath = os.path.join(TEMPLATE_DIR, f"{name}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(template, f, ensure_ascii=False, indent=2)
    
    return filepath


def _match_section(text: str) -> str | None:
    """将标题文字模糊匹配到已知章节名，返回匹配到的章节名或 None。"""
    text = text.strip()
    for sec in KNOWN_SECTIONS:
        # 直接包含关键词即命中
        if any(kw in text for kw in sec.split("与")):
            return sec
    return None


def parse_docx_as_template(file_bytes: bytes, name: str) -> dict:
    """解析 .docx 文件，提取各章节内容，返回可直接保存的模板 dict。"""
    try:
        from docx import Document
        import io
        doc = Document(io.BytesIO(file_bytes))
    except Exception as e:
        raise ValueError(f"无法解析 Word 文件: {e}")

    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        # 标题段落（Heading 1/2）或文字能匹配已知章节 → 切换当前章节
        is_heading = para.style.name.startswith("Heading") or para.style.name.startswith("标题")
        matched = _match_section(text)

        if is_heading or matched:
            sec = matched or text
            if sec not in sections:
                sections[sec] = []
            current_section = sec
        elif current_section:
            sections[current_section].append(text)

    # 将列表合并为字符串，作为写作提示
    result_sections = {k: "\n".join(v)[:2000] for k, v in sections.items() if v}
    return {
        "name": name,
        "description": f"从 Word 文档「{name}」解析",
        "sections": result_sections,
    }


def parse_txt_as_template(text: str, name: str) -> dict:
    """解析纯文本文件，按章节名分割内容。"""
    sections: dict[str, list[str]] = {}
    current_section: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        matched = _match_section(stripped)
        if matched:
            current_section = matched
            if current_section not in sections:
                sections[current_section] = []
        elif current_section:
            sections[current_section].append(stripped)

    result_sections = {k: "\n".join(v)[:2000] for k, v in sections.items() if v}
    return {
        "name": name,
        "description": f"从文本文件「{name}」解析",
        "sections": result_sections,
    }
