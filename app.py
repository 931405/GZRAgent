import streamlit as st
import time
import os
from src.orchestrator import build_orchestrator
from src.utils.diff_engine import get_html_diff

st.set_page_config(page_title="NSFC 智能撰写系统", page_icon="N", layout="wide")

# ================= 自定义样式 =================
st.markdown("""
<style>
    .main-title { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.2rem; }
    .sub-desc { color: #666; font-size: 0.9rem; margin-bottom: 1rem; }
    .section-label { font-size: 0.85rem; font-weight: 600; color: #444; margin-bottom: 4px; }
    div[data-testid="stSidebar"] { background-color: #fafafa; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">NSFC 基金申请书智能撰写系统</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-desc">4+1 Agent 协作架构 — 文献专员 / 基金策略师 / 首席研究员 / 科学评论家</div>', unsafe_allow_html=True)

# ================= Session State =================
if "graph_state" not in st.session_state:
    st.session_state.graph_state = None
if "workflow_running" not in st.session_state:
    st.session_state.workflow_running = False
if "messages" not in st.session_state:
    st.session_state.messages = []
if "generate_all_running" not in st.session_state:
    st.session_state.generate_all_running = False
if "pending_sections" not in st.session_state:
    st.session_state.pending_sections = []

ALL_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"]

# ================= 侧边栏 =================
with st.sidebar:
    # ---- 项目基本设置 ----
    st.subheader("项目设置")
    project_type = st.selectbox("项目类型", ["面上项目", "青年科学基金", "重点项目", "杰青/优青"])
    research_topic = st.text_area("研究主题", value="大语言模型多智能体协作机制研究", height=68)
    current_focus = st.selectbox("单章节撰写目标", ALL_SECTIONS)
    max_iterations = st.slider("最大迭代轮次", min_value=1, max_value=5, value=2)
    
    st.divider()
    
    # ---- 模板选择 ----
    st.subheader("写作模板")
    from src.utils.template_manager import get_template_list, get_template, save_custom_template
    
    template_list = get_template_list()
    selected_template = st.selectbox("选择模板", ["不使用模板"] + template_list)
    
    template_hint = ""
    if selected_template != "不使用模板":
        tpl = get_template(selected_template)
        if tpl:
            st.caption(f"*{tpl.get('description', '')}*")
            template_hint = tpl.get("sections", {}).get(current_focus, "")
            if template_hint:
                with st.expander("查看模板提示"):
                    st.text(template_hint)
    
    # 保存自定义模板
    with st.expander("保存当前草稿为模板"):
        custom_name = st.text_input("模板名称", key="tpl_name")
        custom_desc = st.text_input("模板描述", key="tpl_desc")
        if st.button("保存模板") and custom_name:
            drafts = st.session_state.graph_state.get("draft_sections", {}) if st.session_state.graph_state else {}
            if drafts:
                save_custom_template(custom_name, custom_desc, drafts)
                st.success(f"模板 '{custom_name}' 已保存")
            else:
                st.warning("当前无草稿可保存")
    
    st.divider()
    
    # ---- AI 模型分配 ----
    st.subheader("模型分配")
    PROVIDERS = ["deepseek", "moonshot", "doubao"]
    col_l, col_r = st.columns(2)
    with col_l:
        model_searcher = st.selectbox("Searcher", PROVIDERS, index=0)
        model_writer = st.selectbox("Writer", PROVIDERS, index=0)
    with col_r:
        model_designer = st.selectbox("Designer", PROVIDERS, index=0)
        model_reviewer = st.selectbox("Reviewer", PROVIDERS, index=0)
    
    st.divider()
    
    # ---- 知识库管理 ----
    st.subheader("本地知识库")
    st.caption("Embedding: Qwen/Qwen3-Embedding-8B (SiliconFlow)")
    
    from src.utils.rag_engine import get_kb_stats
    kb_stats = get_kb_stats()
    if kb_stats["total_files"] > 0:
        st.success(f"已收录 {kb_stats['total_files']} 份文档")
        with st.expander("已入库文件"):
            for fname in kb_stats["file_names"]:
                st.text(f"  {fname}")
    else:
        st.info("知识库为空")
    
    uploaded_files = st.file_uploader("上传文件 (PDF/Docx/TXT, 上限 700MB)", accept_multiple_files=True)
    if st.button("注入知识库（文件）", type="secondary") and uploaded_files:
        from src.utils.rag_engine import add_document_to_kb
        import tempfile
        with st.spinner("向量化中..."):
            total_chunks = 0
            for file in uploaded_files:
                ext = os.path.splitext(file.name)[1]
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(file.getvalue())
                    tmp_path = tmp.name
                chunks_added = add_document_to_kb(tmp_path)
                total_chunks += chunks_added
                os.unlink(tmp_path)
            st.success(f"{len(uploaded_files)} 份文档, {total_chunks} 个片段已注入")
    
    folder_path = st.text_input("或输入文件夹路径", placeholder=r"D:\论文\参考文献")
    if st.button("扫描文件夹注入") and folder_path:
        from src.utils.rag_engine import add_document_to_kb
        if not os.path.isdir(folder_path):
            st.error("路径不存在")
        else:
            SUPPORTED = {".pdf", ".docx", ".txt", ".md"}
            all_files = [os.path.join(r, f) for r, _, fs in os.walk(folder_path) for f in fs if os.path.splitext(f)[1].lower() in SUPPORTED]
            if not all_files:
                st.warning("未找到支持的文件")
            else:
                bar = st.progress(0)
                total, skipped = 0, 0
                for i, fp in enumerate(all_files):
                    try:
                        c = add_document_to_kb(fp)
                        total += c
                        if c == 0: skipped += 1
                    except:
                        skipped += 1
                    bar.progress((i+1)/len(all_files))
                st.success(f"新增 {total} 片段, 跳过 {skipped} 个")
    
    st.divider()
    
    # ---- 操作按钮 ----
    def _build_init_state(focus, drafts=None, clear_all=False):
        return {
            "project_type": project_type,
            "research_topic": research_topic,
            "current_focus": focus,
            "draft_sections": {} if clear_all else (drafts or {}),
            "reference_documents": [],
            "review_feedbacks": [] if clear_all else (st.session_state.graph_state.get("review_feedbacks", []) if st.session_state.graph_state else []),
            "discussion_history": [] if clear_all else (st.session_state.graph_state.get("discussion_history", []) if st.session_state.graph_state else []),
            "iteration_count": 0,
            "max_iterations": max_iterations,
            "status": "INITIALIZED",
            "final_document_path": None,
            "reviewer_score": 0,
            "template_hint": template_hint,
            "model_config": {
                "searcher": model_searcher,
                "writer": model_writer,
                "designer": model_designer,
                "reviewer": model_reviewer
            }
        }
    
    if st.button("开始单章节撰写", type="primary", use_container_width=True):
        old_drafts = st.session_state.graph_state.get("draft_sections", {}) if st.session_state.graph_state else {}
        st.session_state.graph_state = _build_init_state(current_focus, drafts=old_drafts)
        st.session_state.workflow_running = True
        st.session_state.generate_all_running = False

    if st.button("一键生成完整申请书", type="primary", use_container_width=True):
        st.session_state.graph_state = _build_init_state(ALL_SECTIONS[0], clear_all=True)
        st.session_state.messages = []
        st.session_state.generate_all_running = True
        st.session_state.pending_sections = ALL_SECTIONS.copy()
        st.session_state.workflow_running = False
    
    st.divider()
    
    # ---- 历史记录 ----
    st.subheader("历史记录")
    from src.utils.history_manager import load_history_list, load_history_data, save_history
    history_files = load_history_list()
    if history_files:
        sel = st.selectbox("选择记录", history_files)
        if st.button("加载"):
            data = load_history_data(sel)
            if data:
                st.session_state.graph_state = data
                st.session_state.messages = data.get("discussion_history", [])
                st.success(f"已加载: {sel}")
    else:
        st.caption("暂无历史记录")
    
    if st.session_state.graph_state and st.session_state.graph_state.get("draft_sections"):
        if st.button("保存当前状态"):
            p_type = st.session_state.graph_state.get("project_type", "")
            p_name = st.session_state.graph_state.get("research_topic", "")[:10]
            path = save_history(st.session_state.graph_state, f"{p_type}_{p_name}")
            st.success(f"已保存: {path}")


# ================= 主界面 =================
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("工作流监控")
    log_container = st.container(height=550)
    
    is_running = st.session_state.workflow_running or st.session_state.generate_all_running
    if is_running:
        app_workflow = build_orchestrator()
        from src.utils.logger import logger
        
        sections_to_run = st.session_state.pending_sections if st.session_state.generate_all_running else [current_focus]
        
        for sec in sections_to_run:
            st.session_state.graph_state["current_focus"] = sec
            st.session_state.graph_state["iteration_count"] = 0
            st.session_state.graph_state["status"] = "INITIALIZED"
            
            logger.info(f"=== Workflow: {sec} ===")
            
            with st.spinner(f"正在撰写「{sec}」..."):
                for output in app_workflow.stream(st.session_state.graph_state):
                    for node_name, state_update in output.items():
                        logger.info(f"[{node_name}]")
                        
                        if "discussion_history" in state_update:
                            for msg in state_update["discussion_history"]:
                                st.session_state.messages.append(f"**[{sec} / {node_name}]** {msg}")
                                
                        if "draft_sections" in state_update:
                            st.session_state.graph_state["draft_sections"] = state_update["draft_sections"]
                        if "review_feedbacks" in state_update:
                            old = st.session_state.graph_state.get("review_feedbacks", [])
                            st.session_state.graph_state["review_feedbacks"] = old + state_update["review_feedbacks"]
                        if "discussion_history" in state_update:
                            st.session_state.graph_state["discussion_history"] = st.session_state.messages
                        
                        with log_container:
                            st.empty()
                            for m in st.session_state.messages:
                                st.markdown(m)
            
            st.success(f"「{sec}」处理完成")
        
        st.session_state.workflow_running = False
        st.session_state.generate_all_running = False
        st.session_state.pending_sections = []
        
        # 全文连贯性审计
        if len(st.session_state.graph_state.get("draft_sections", {})) >= 2:
            with st.spinner("正在进行全文连贯性审计..."):
                from src.agents.coherence_checker import run_coherence_check
                result = run_coherence_check(st.session_state.graph_state)
                if "discussion_history" in result:
                    for msg in result["discussion_history"]:
                        st.session_state.messages.append(f"**[连贯性审计]** {msg}")
        
        with log_container:
            for m in st.session_state.messages:
                st.markdown(m)

# ---- 右侧面板 ----
with col2:
    st.subheader("内容审阅")
    
    if not st.session_state.graph_state or not st.session_state.graph_state.get("draft_sections"):
        st.info("尚无生成的草稿。请在左侧启动撰写流程。")
    else:
        draft_sections = st.session_state.graph_state.get("draft_sections", {})
        available = list(draft_sections.keys()) if draft_sections else [st.session_state.graph_state.get("current_focus")]
        view_focus = st.selectbox("选择查看章节", available, index=len(available)-1)
        draft = draft_sections.get(view_focus, "")
        
        tabs = st.tabs(["章节草稿", "修订建议", "完整预览"])
        
        with tabs[0]:
            st.markdown(draft if draft else "该章节尚无内容。")
        
        with tabs[1]:
            all_feedbacks = st.session_state.graph_state.get("review_feedbacks", [])
            feedbacks = [fb for fb in all_feedbacks if fb.get('section') == view_focus] if all_feedbacks else []
            
            if feedbacks:
                for idx, fb in enumerate(feedbacks):
                    with st.expander(f"建议 #{idx+1}  [评分: {fb.get('score', 0)}]"):
                        orig = fb.get('original_text', '')
                        sugg = fb.get('suggested_text', '')
                        html_diff = get_html_diff(orig, sugg)
                        st.markdown(f"**对比**: {html_diff}", unsafe_allow_html=True)
                        st.markdown(f"**理由**: {fb.get('reason')}")
                        c1, c2, _ = st.columns([2, 2, 6])
                        with c1:
                            st.button("接受", key=f"acc_{idx}")
                        with c2:
                            st.button("拒绝", key=f"rej_{idx}")
            else:
                st.caption("暂无修订建议。")
        
        with tabs[2]:
            st.markdown("#### 完整申请书预览")
            all_drafts = st.session_state.graph_state.get("draft_sections", {})
            if not all_drafts:
                st.info("尚无章节内容。")
            else:
                for sname in ALL_SECTIONS:
                    if sname in all_drafts:
                        st.markdown(f"**{sname}**\n")
                        st.markdown(all_drafts[sname])
                        st.divider()
        
        st.divider()
        st.subheader("导出")
        from src.utils.exporter import export_to_word
        if st.button("导出为 Word 文档", type="secondary"):
            path = export_to_word(
                st.session_state.graph_state.get("project_type", "基金申请"),
                st.session_state.graph_state.get("research_topic", "Draft"),
                st.session_state.graph_state.get("draft_sections", {})
            )
            st.success(f"文件已保存至: `{path}`")
