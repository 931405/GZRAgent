/**
 * WorkflowProgress — 全流程进度面板
 *
 * 展示：
 *  1. 5个阶段进度条（决策 → 并行执行 → 专家辩论 → 裁决 → 排版）
 *  2. 任务执行看板（所有历史任务 + 完成状态）
 *  3. 专家辩论评分（第1轮 + 第2轮）
 *  4. 辩论裁决卡片
 *  5. 统计数据（章节数、字数）
 */

import { useMemo } from 'react';

interface Task {
    task_id?: string;
    agent_type: string;
    section?: string;
    priority?: number;
}

interface DebateRoundEntry {
    round: number;
    reviewer?: string;
    expert_name?: string;
    stance?: string;
    score?: number;
    argument?: string;
    comment?: string;
}

interface WorkflowProgressProps {
    currentNode: string;
    isRunning: boolean;
    allDispatchedTasks: Task[];
    debateRounds: DebateRoundEntry[];
    debateVerdict: { conclusion: string; revision_required: boolean; targets: any[]; final_score?: number } | null;
    reviewerScore: { score: number; feedbackCount: number; iteration: number } | null;
    drafts: Record<string, string>;
    layoutNotes: string;
    innovationPoints: string;
    iterationCount?: number;
    maxIterations?: number;
}

// ─────────────── Phase 定义 ───────────────
const PHASES = [
    { key: 'decision_agent', label: '决策规划', icon: '🧠' },
    { key: 'multi_worker',   label: '并行执行', icon: '⚡' },
    { key: 'review_panel',   label: '专家辩论', icon: '👥' },
    { key: 'final_decision', label: '辩论裁决', icon: '⚖️' },
    { key: 'layout_agent',   label: '排版定稿', icon: '📐' },
];

// ─────────────── Agent 类型样式 ───────────────
const AGENT_STYLES: Record<string, { color: string; label: string; icon: string }> = {
    searcher:   { color: 'bg-amber-100 text-amber-800 border-amber-200',  label: '文献检索', icon: '🔍' },
    innovation: { color: 'bg-lime-100 text-lime-800 border-lime-200',     label: '创新提炼', icon: '💡' },
    writer:     { color: 'bg-sky-100 text-sky-800 border-sky-200',        label: '章节写作', icon: '✍️' },
    diagram:    { color: 'bg-violet-100 text-violet-800 border-violet-200', label: '绘图', icon: '🖼' },
    layout:     { color: 'bg-teal-100 text-teal-800 border-teal-200',     label: '排版', icon: '📐' },
};

// ─────────────── 专家样式 ───────────────
function expertStyle(name: string) {
    const n = (name || '').toLowerCase();
    if (n.includes('红') || n.includes('challenge')) return { bg: 'bg-red-50 border-red-200', badge: 'bg-red-100 text-red-700', icon: '🔴' };
    if (n.includes('蓝') || n.includes('support')) return { bg: 'bg-blue-50 border-blue-200', badge: 'bg-blue-100 text-blue-700', icon: '🔵' };
    if (n.includes('方法') || n.includes('method')) return { bg: 'bg-orange-50 border-orange-200', badge: 'bg-orange-100 text-orange-700', icon: '🔬' };
    return { bg: 'bg-lime-50 border-lime-200', badge: 'bg-lime-100 text-lime-700', icon: '✨' };
}

export function WorkflowProgress({
    currentNode, isRunning,
    allDispatchedTasks, debateRounds, debateVerdict, reviewerScore,
    drafts, layoutNotes, innovationPoints,
    iterationCount = 0, maxIterations = 3,
}: WorkflowProgressProps) {

    // ─── 阶段完成状态 ───
    const phaseStatus = useMemo(() => {
        const hasDrafts = Object.keys(drafts).length > 0;
        const hasDebate = debateRounds.length > 0;
        const hasVerdict = debateVerdict !== null;
        const hasLayout = !!layoutNotes;
        const hasTasks = allDispatchedTasks.length > 0;

        return {
            decision_agent: hasTasks ? 'done' : (currentNode === 'decision_agent' ? 'active' : 'pending'),
            multi_worker: hasDrafts ? 'done' : (currentNode === 'multi_worker' ? 'active' : (hasTasks ? 'active' : 'pending')),
            review_panel: hasDebate ? 'done' : (currentNode === 'review_panel' ? 'active' : 'pending'),
            final_decision: hasVerdict ? 'done' : (currentNode === 'final_decision' ? 'active' : 'pending'),
            layout_agent: hasLayout ? 'done' : (currentNode === 'layout_agent' ? 'active' : 'pending'),
        } as Record<string, 'done' | 'active' | 'pending'>;
    }, [currentNode, allDispatchedTasks, drafts, debateRounds, debateVerdict, layoutNotes]);

    // ─── 任务是否已完成 ───
    const isTaskDone = (task: Task) => {
        if (task.agent_type === 'writer' && task.section) return !!(drafts[task.section] && drafts[task.section].length > 100);
        if (task.agent_type === 'innovation') return !!innovationPoints;
        if (task.agent_type === 'searcher') return Object.keys(drafts).length > 0; // searcher 完成后 writer 才有内容
        return false;
    };

    // ─── 任务按类型分组 ───
    const taskGroups = useMemo(() => {
        const map: Record<string, Task[]> = {};
        for (const t of allDispatchedTasks) {
            const key = t.agent_type;
            if (!map[key]) map[key] = [];
            // 去重：同 agent_type+section 只保留一条
            if (!map[key].find(x => x.section === t.section)) {
                map[key].push(t);
            }
        }
        return map;
    }, [allDispatchedTasks]);

    // ─── 辩论第1轮和第2轮 ───
    const round1 = debateRounds.filter(r => r.round === 1);
    const round2 = debateRounds.filter(r => r.round === 2);

    // ─── 无任何进度时不渲染 ───
    const hasAnyProgress = isRunning || allDispatchedTasks.length > 0 || Object.keys(drafts).length > 0;
    if (!hasAnyProgress) return null;

    const phaseIconClass = (status: 'done' | 'active' | 'pending') =>
        status === 'done' ? 'opacity-100' : status === 'active' ? 'opacity-100 animate-pulse' : 'opacity-25';

    return (
        <div className="flex flex-col gap-3 bg-white rounded-lg border border-slate-200 shadow-sm p-4 overflow-y-auto" style={{ minHeight: 0 }}>

            {/* ══════ 1. 阶段进度带 ══════ */}
            <div>
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">工作流阶段</div>
                <div className="flex items-center gap-0">
                    {PHASES.map((phase, idx) => {
                        const status = phaseStatus[phase.key];
                        return (
                            <div key={phase.key} className="flex items-center">
                                <div className={`flex flex-col items-center gap-0.5 px-1.5 transition-all ${phaseIconClass(status)}`}>
                                    <span className="text-base leading-tight">{phase.icon}</span>
                                    <span className={`text-[9px] font-semibold whitespace-nowrap leading-tight ${
                                        status === 'active' ? 'text-blue-600' : status === 'done' ? 'text-emerald-600' : 'text-slate-400'
                                    }`}>{phase.label}</span>
                                    <div className={`h-0.5 w-full rounded ${
                                        status === 'done' ? 'bg-emerald-400' : status === 'active' ? 'bg-blue-400' : 'bg-transparent'
                                    }`} />
                                </div>
                                {idx < PHASES.length - 1 && (
                                    <div className={`h-px w-2 mx-0.5 ${
                                        phaseStatus[PHASES[idx+1].key] !== 'pending' || status === 'done' ? 'bg-emerald-300' : 'bg-slate-200'
                                    }`} />
                                )}
                            </div>
                        );
                    })}
                    {/* 迭代标记 */}
                    {iterationCount > 0 && (
                        <div className="ml-auto shrink-0 text-[9px] text-slate-400 font-mono">
                            第{iterationCount}轮/{maxIterations}
                        </div>
                    )}
                </div>
            </div>

            {/* ══════ 2. 任务执行看板 ══════ */}
            {Object.keys(taskGroups).length > 0 && (
                <div>
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">任务执行</div>
                    <div className="flex flex-col gap-1.5">
                        {Object.entries(taskGroups).map(([agentType, tasks]) => {
                            const style = AGENT_STYLES[agentType] || { color: 'bg-slate-100 text-slate-700 border-slate-200', label: agentType, icon: '🔧' };
                            const doneCount = tasks.filter(isTaskDone).length;
                            return (
                                <div key={agentType}>
                                    <div className="flex items-center gap-1 mb-1">
                                        <span className="text-sm">{style.icon}</span>
                                        <span className="text-xs font-semibold text-slate-600">{style.label}</span>
                                        <span className="text-[10px] text-slate-400 ml-auto">{doneCount}/{tasks.length}</span>
                                    </div>
                                    <div className="flex flex-wrap gap-1">
                                        {tasks.map((task, i) => {
                                            const done = isTaskDone(task);
                                            const isActive = !done && (currentNode === 'multi_worker') && isRunning;
                                            return (
                                                <div
                                                    key={i}
                                                    className={`flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-medium transition-all ${
                                                        done
                                                            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                                            : isActive
                                                                ? 'bg-blue-50 border-blue-300 text-blue-700 animate-pulse'
                                                                : 'bg-slate-50 border-slate-200 text-slate-500'
                                                    }`}
                                                >
                                                    <span>{done ? '✓' : isActive ? '⟳' : '○'}</span>
                                                    <span>{task.section || '全文'}</span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* ══════ 3. 专家辩论评分 ══════ */}
            {round1.length > 0 && (
                <div>
                    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">专家评分</div>
                    {/* 第1轮 */}
                    <div className="mb-1.5">
                        <div className="text-[9px] text-slate-400 mb-1">第1轮 · 独立评审</div>
                        <div className="flex flex-col gap-1">
                            {round1.map((entry, i) => {
                                const name = entry.reviewer || entry.expert_name || `专家${i + 1}`;
                                const score = entry.score ?? 0;
                                const st = expertStyle(name);
                                const pct = Math.min(score, 100);
                                return (
                                    <div key={i} className="flex items-center gap-2">
                                        <span className="text-[10px] shrink-0 w-3">{st.icon}</span>
                                        <span className="text-[10px] text-slate-600 truncate w-20 shrink-0">{name.replace(/专家|（.*?）/g, '').trim().slice(0, 6)}</span>
                                        <div className="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                                            <div
                                                className={`h-full rounded-full transition-all duration-700 ${score >= 80 ? 'bg-emerald-400' : score >= 65 ? 'bg-amber-400' : 'bg-red-400'}`}
                                                style={{ width: `${pct}%` }}
                                            />
                                        </div>
                                        <span className="text-[10px] font-mono font-bold w-6 text-right text-slate-700">{score}</span>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                    {/* 第2轮 */}
                    {round2.length > 0 && (
                        <div>
                            <div className="text-[9px] text-slate-400 mb-1">第2轮 · 交叉辩论</div>
                            <div className="flex flex-col gap-1">
                                {round2.map((entry, i) => {
                                    const name = entry.reviewer || entry.expert_name || `专家${i + 1}`;
                                    const score = entry.score ?? 0;
                                    const st = expertStyle(name);
                                    const pct = Math.min(score, 100);
                                    return (
                                        <div key={i} className="flex items-center gap-2">
                                            <span className="text-[10px] shrink-0 w-3">{st.icon}</span>
                                            <span className="text-[10px] text-slate-600 truncate w-20 shrink-0">{name.replace(/专家|（.*?）/g, '').trim().slice(0, 6)}</span>
                                            <div className="flex-1 bg-slate-100 rounded-full h-1.5 overflow-hidden">
                                                <div
                                                    className={`h-full rounded-full transition-all duration-700 ${score >= 80 ? 'bg-emerald-400' : score >= 65 ? 'bg-amber-400' : 'bg-red-400'}`}
                                                    style={{ width: `${pct}%` }}
                                                />
                                            </div>
                                            <span className="text-[10px] font-mono font-bold w-6 text-right text-slate-700">{score}</span>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* ══════ 4. 辩论裁决 ══════ */}
            {debateVerdict && (
                <div className={`rounded-lg border p-2.5 ${debateVerdict.revision_required ? 'bg-rose-50 border-rose-200' : 'bg-emerald-50 border-emerald-200'}`}>
                    <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1.5">
                            <span className="text-sm">{debateVerdict.revision_required ? '⚠️' : '✅'}</span>
                            <span className={`text-xs font-bold ${debateVerdict.revision_required ? 'text-rose-700' : 'text-emerald-700'}`}>
                                {debateVerdict.revision_required ? '需要修订' : '质量达标'}
                            </span>
                        </div>
                        {debateVerdict.final_score !== undefined && (
                            <span className={`text-xs font-mono font-bold px-1.5 py-0.5 rounded ${
                                debateVerdict.final_score >= 80 ? 'bg-emerald-100 text-emerald-700' :
                                debateVerdict.final_score >= 65 ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700'
                            }`}>{debateVerdict.final_score}</span>
                        )}
                    </div>
                    {debateVerdict.conclusion && (
                        <p className="text-[10px] text-slate-600 leading-relaxed line-clamp-3">{debateVerdict.conclusion}</p>
                    )}
                    {Array.isArray(debateVerdict.targets) && debateVerdict.targets.length > 0 && (
                        <div className="mt-1.5 flex flex-wrap gap-1">
                            {debateVerdict.targets.map((t: any, i: number) => (
                                <span key={i} className="text-[9px] px-1.5 py-0.5 bg-rose-100 text-rose-700 rounded-full border border-rose-200">
                                    {t.section || (typeof t === 'string' ? t : '?')}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* ══════ 5. 统计数据 ══════ */}
            {Object.keys(drafts).length > 0 && (
                <div className="flex items-center gap-3 pt-1 border-t border-slate-100">
                    <div className="flex items-center gap-1 text-[10px] text-slate-500">
                        <span>📄</span>
                        <span><strong className="text-slate-700">{Object.keys(drafts).length}</strong> 章节</span>
                    </div>
                    <div className="flex items-center gap-1 text-[10px] text-slate-500">
                        <span>📝</span>
                        <span><strong className="text-slate-700">{Object.values(drafts).join('').length.toLocaleString()}</strong> 字</span>
                    </div>
                    {reviewerScore && (
                        <div className={`flex items-center gap-1 text-[10px] font-bold ${
                            reviewerScore.score >= 85 ? 'text-emerald-600' : reviewerScore.score >= 60 ? 'text-amber-600' : 'text-red-600'
                        }`}>
                            <span>📊</span>
                            <span>{reviewerScore.score.toFixed(0)}分</span>
                        </div>
                    )}
                    {innovationPoints && (
                        <div className="flex items-center gap-1 text-[10px] text-lime-600">
                            <span>💡</span>
                            <span>创新点已提炼</span>
                        </div>
                    )}
                    {layoutNotes && (
                        <div className="flex items-center gap-1 text-[10px] text-teal-600">
                            <span>📐</span>
                            <span>已排版优化</span>
                        </div>
                    )}
                </div>
            )}

            {/* 运行中的心跳 */}
            {isRunning && (
                <div className="flex items-center gap-1.5 text-[10px] text-blue-500">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                    <span>正在运行中...</span>
                </div>
            )}
        </div>
    );
}
