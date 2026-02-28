import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestrator import build_orchestrator

def main():
    app = build_orchestrator()
    print("Graph compiled successfully.")
    
    initial_state = {
        "project_type": "面上项目",
        "research_topic": "多智能体协作框架的理论探索",
        "current_focus": "立项依据",
        "draft_sections": {},
        "reference_documents": [],
        "review_feedbacks": [],
        "discussion_history": [],
        "iteration_count": 0,
        "max_iterations": 2, # Run for 2 iterations
        "status": "INITIALIZED",
        "final_document_path": None
    }
    
    print("--- BEGIN WORKFLOW ---")
    for output in app.stream(initial_state):
        for key, value in output.items():
            print(f"\n[Node Execution]: {key}")
            print(f"Status: {value.get('status')}")
            if "discussion_history" in value:
                print(f"Messages: {value['discussion_history']}")
            if "review_feedbacks" in value:
                print(f"Feedbacks: {len(value['review_feedbacks'])}")
            print("-" * 20)

if __name__ == "__main__":
    main()
