import os
from src.state import GraphState, SectionDOM, TextElement, TableElement, FormulaElement
from src.utils.typst_exporter import export_to_typst

def test_export():
    dom = {
        "立项依据": SectionDOM(
            title="立项依据",
            elements=[
                TextElement(id="t1", content="动态内存与调度算法在多智能体系统（MAS）中起着至关重要的作用。以下是不同架构对比："),
                TableElement(id="tbl1", content="| 架构 | 延迟 (ms) | 吞吐量 |\n|---|---|---|\n| 传统轮询 | 120 | 500 |\n| 事件驱动 | 45 | 1200 |\n| 混合调度 | 20 | 2500 |"),
            ]
        ),
        "研究目标与内容": SectionDOM(
            title="研究目标与内容",
            elements=[
                TextElement(id="t2", content="本项目拟解决资源受限下的内存回收问题，核心动态调度方程如下："),
                FormulaElement(id="eq1", content="E = integral_0^T (P(t) - L(t)) dif t + sum_(i=1)^N alpha_i"),
                TextElement(id="t3", content="其中 $P(t)$ 为处理能力，$L(t)$ 为负载，$alpha_i$ 为动态惩罚项。")
            ]
        )
    }
    
    drafts = {"document_dom": dom}
    
    print("开始导出 Typst PDF...")
    pdf_path = export_to_typst(
        project_type="面上项目",
        topic="复杂多 Agent 系统中的动态内存与调度算法",
        drafts=drafts,
        output_dir="data"
    )
    
    if os.path.exists(pdf_path):
        print(f"测试成功！PDF 文件位于: {pdf_path}")
    else:
        print("测试失败：未找到输出的 PDF 文件。")

if __name__ == "__main__":
    test_export()
