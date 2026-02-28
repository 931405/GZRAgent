interface WorkflowTimelineProps {
    currentNode: string;
    isRunning: boolean;
}

const STEPS: { key: string; label: string; icon: string }[] = [
    { key: 'decision_agent', label: '决策规划', icon: '🧠' },
    { key: 'multi_worker',   label: '并行写作', icon: '⚡' },
    { key: 'review_panel',   label: '专家评审', icon: '👥' },
    { key: 'final_decision', label: '辩论裁决', icon: '⚖️' },
    { key: 'layout_agent',   label: '排版定稿', icon: '📐' },
    // 兼容旧版节点
    { key: 'searcher',        label: '文献检索', icon: '🔍' },
    { key: 'writer',          label: '起草撰写', icon: '✍️' },
    { key: 'reviewer',        label: '评审打分', icon: '📋' },
];

export function WorkflowTimeline({ currentNode, isRunning }: WorkflowTimelineProps) {
    const activeIdx = STEPS.findIndex(s => currentNode.includes(s.key));
    const isDone = currentNode === 'done';

    if (!isRunning && !isDone) return null;

    return (
        <div className="flex items-center gap-0 bg-white border border-slate-200 rounded-lg px-4 py-2 overflow-x-auto shrink-0">
            {STEPS.map((step, idx) => {
                const isActive = activeIdx === idx;
                const isCompleted = isDone || (activeIdx > idx);
                return (
                    <div key={step.key} className="flex items-center">
                        <div className={`flex flex-col items-center gap-0.5 px-2 transition-all duration-300 ${isActive ? 'opacity-100 scale-110' : isCompleted ? 'opacity-60' : 'opacity-30'
                            }`}>
                            <span className={`text-lg ${isActive ? 'animate-pulse' : ''}`}>{step.icon}</span>
                            <span className={`text-[10px] whitespace-nowrap font-medium ${isActive ? 'text-blue-600' : isCompleted ? 'text-slate-500' : 'text-slate-400'
                                }`}>{step.label}</span>
                            {isActive && (
                                <div className="h-0.5 w-full bg-blue-500 rounded animate-pulse" />
                            )}
                            {isCompleted && !isActive && (
                                <div className="h-0.5 w-full bg-emerald-400 rounded" />
                            )}
                        </div>
                        {idx < STEPS.length - 1 && (
                            <div className={`h-px w-3 mx-0.5 transition-colors duration-300 ${isCompleted && activeIdx > idx ? 'bg-emerald-400' : 'bg-slate-200'
                                }`} />
                        )}
                    </div>
                );
            })}
            {isDone && (
                <div className="ml-3 text-emerald-600 text-xs font-semibold">✅ 完成</div>
            )}
        </div>
    );
}
