import { BrainCircuit, Zap, Users, Scale, LayoutTemplate, Search, PenTool, ClipboardCheck, CheckCircle2 } from 'lucide-react';

interface WorkflowTimelineProps {
    currentNode: string;
    isRunning: boolean;
}

const STEPS: { key: string; label: string; icon: React.ReactNode }[] = [
    { key: 'decision_agent', label: '决策规划', icon: <BrainCircuit size={18} /> },
    { key: 'multi_worker', label: '并行写作', icon: <Zap size={18} /> },
    { key: 'review_panel', label: '专家评审', icon: <Users size={18} /> },
    { key: 'final_decision', label: '辩论裁决', icon: <Scale size={18} /> },
    { key: 'layout_agent', label: '排版定稿', icon: <LayoutTemplate size={18} /> },
    // 兼容旧版节点
    { key: 'searcher', label: '文献检索', icon: <Search size={18} /> },
    { key: 'writer', label: '起草撰写', icon: <PenTool size={18} /> },
    { key: 'reviewer', label: '评审打分', icon: <ClipboardCheck size={18} /> },
];

export function WorkflowTimeline({ currentNode, isRunning }: WorkflowTimelineProps) {
    const activeIdx = STEPS.findIndex(s => currentNode.includes(s.key));
    const isDone = currentNode === 'done';

    if (!isRunning && !isDone) return null;

    return (
        <div className="flex items-center gap-0 bg-white border border-blue-100 rounded-md px-5 py-3 overflow-x-auto shrink-0 shadow-sm">
            {STEPS.map((step, idx) => {
                const isActive = activeIdx === idx;
                const isCompleted = isDone || (activeIdx > idx);
                return (
                    <div key={step.key} className="flex items-center">
                        <div className={`flex flex-col items-center gap-1.5 px-3 transition-all duration-300 ${isActive ? 'opacity-100 scale-105' : isCompleted ? 'opacity-70' : 'opacity-40'}`}>
                            <div className={`${isActive ? 'text-blue-600 animate-pulse' : isCompleted ? 'text-blue-500' : 'text-slate-400'}`}>
                                {step.icon}
                            </div>
                            <span className={`text-[11px] whitespace-nowrap font-medium ${isActive ? 'text-blue-700' : isCompleted ? 'text-blue-600' : 'text-slate-500'}`}>
                                {step.label}
                            </span>
                        </div>
                        {idx < STEPS.length - 1 && (
                            <div className="flex flex-col justify-center px-1">
                                <div className={`h-0.5 w-6 transition-colors duration-300 ${isCompleted && activeIdx > idx ? 'bg-blue-400' : 'bg-blue-100'}`} />
                            </div>
                        )}
                    </div>
                );
            })}
            {isDone && (
                <div className="ml-4 flex items-center gap-1.5 text-emerald-600 text-[11px] font-semibold bg-emerald-50 px-2.5 py-1 rounded-md border border-emerald-200">
                    <CheckCircle2 size={14} /> 完成
                </div>
            )}
        </div>
    );
}
