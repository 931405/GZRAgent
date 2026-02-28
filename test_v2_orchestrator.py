import json
from src.state import GraphState
from src.orchestrator import _run_task, _merge_results

def test_v2_pipeline():
    state = GraphState(
        project_type="面上项目",
        research_topic="复杂多 Agent 系统中的动态内存与调度算法",
        current_focus="立项依据",
        draft_sections={
            "立项依据": "当前调度系统存在瓶颈。[PLACEHOLDER: TABLE: 系统瓶颈对比表]\n根据以下推导得到结论。[PLACEHOLDER: FORMULA: 动态调度内存释放方程]"
        },
        document_dom={},
        innovation_points="",
        layout_notes="",
        reference_documents=[],
        reference_dict={},
        review_feedbacks=[],
        discussion_history=[],
        iteration_count=0,
        max_iterations=3,
        status="EXECUTING",
        reviewer_score=0.0,
        prev_review_feedbacks=[],
        pending_tasks=[],
        completed_tasks=[],
        decision_log=[],
        current_phase="executing",
        debate_rounds=[],
        debate_conclusion="",
        revision_required=False,
        revision_targets=[],
        completed_section_summaries={},
        document_outline="",
        final_document_path=None,
        model_config={},
        generated_images={}
    )

    # 1. 验证 Decision Agent 是否能正确提取占位符
    from src.agents.decision_agent import run_decision_agent
    res1 = run_decision_agent(state)
    print("=== Decision Agent 生成的任务 ===")
    print(json.dumps(res1["pending_tasks"], indent=2, ensure_ascii=False))

    # 更新 state
    state["pending_tasks"] = res1["pending_tasks"]
    
    # 2. 模拟 Multi-Worker 提取数据和公式
    from src.orchestrator import run_multi_worker
    res2 = run_multi_worker(state)
    print("\n=== Multi-Worker 执行结果 DOM 树 ===")
    # Note: run_multi_worker merges properties, let's extract document_dom
    dom_result = res2.get("document_dom", {})
    for sec, dom in dom_result.items():
        print(f"Section: {sec}")
        for el in dom.elements:
            print(f"  - Element [{el.id}] Type: {el.type}\n    Content: {el.content[:50]}...\n")
            
    print("\n=== Exporter 兼容性测试 ===")
    from src.utils.exporter import _export_standard
    # Make a dummy call to export standard with dom injection directly via drafts (to simulate API compat layer)
    try:
        drafts_with_dom = dict(state["draft_sections"])
        drafts_with_dom["_dom_cache"] = dom_result
        output = _export_standard("面上项目", "测试主题", drafts_with_dom, "data", {})
        print(f"Export successful: {output}")
    except Exception as e:
        print(f"Export failed: {e}")

if __name__ == "__main__":
    test_v2_pipeline()
