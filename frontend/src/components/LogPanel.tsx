import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

type FilterLevel = 'all' | 'key' | 'score' | 'debate';

interface LogPanelProps {
    messages: string[];
}

// Agent role color mapping
const ROLE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
    // ---- 原有角色 ----
    searcher: { bg: 'bg-amber-100', text: 'text-amber-800', label: '文献专员' },
    designer: { bg: 'bg-violet-100', text: 'text-violet-800', label: '策略师' },
    writer: { bg: 'bg-sky-100', text: 'text-sky-800', label: '首席研究员' },
    reviewer: { bg: 'bg-rose-100', text: 'text-rose-800', label: '评审专家' },
    reviewer_red: { bg: 'bg-red-100', text: 'text-red-800', label: '🔴 红脸·挑刺' },
    reviewer_blue: { bg: 'bg-blue-100', text: 'text-blue-800', label: '🔵 蓝脸·建设' },
    coherence_checker: { bg: 'bg-emerald-100', text: 'text-emerald-800', label: '连贯性审计' },
    reference_compiler: { bg: 'bg-teal-100', text: 'text-teal-800', label: '参考文献' },
    // ---- 新架构角色 ----
    decision_agent: { bg: 'bg-indigo-100', text: 'text-indigo-800', label: '🧠 决策规划' },
    multi_worker: { bg: 'bg-cyan-100', text: 'text-cyan-800', label: '⚡ 并行执行' },
    review_panel: { bg: 'bg-rose-50', text: 'text-rose-700', label: '👥 专家评审' },
    final_decision: { bg: 'bg-purple-100', text: 'text-purple-800', label: '⚖️ 辩论裁决' },
    layout_agent: { bg: 'bg-teal-100', text: 'text-teal-800', label: '📐 排版优化' },
    innovation_agent: { bg: 'bg-lime-100', text: 'text-lime-800', label: '💡 创新专员' },
    // ---- 辩论专家 ----
    expert_red: { bg: 'bg-red-100', text: 'text-red-800', label: '🔴 挑战专家' },
    expert_blue: { bg: 'bg-blue-100', text: 'text-blue-800', label: '🔵 建设专家' },
    expert_method: { bg: 'bg-orange-100', text: 'text-orange-800', label: '🔬 方法论专家' },
    expert_innovation: { bg: 'bg-lime-100', text: 'text-lime-800', label: '✨ 创新性专家' },
};

function parseLogMessage(msg: string): { section: string; role: string; roleKey: string; body: string } | null {
    // ---- 新架构：emoji 前缀格式 ----
    // 🧠 [DecisionAgent] ...  or  🧠 决策Agent: ...
    if (msg.startsWith('🧠')) {
        const m = msg.match(/^🧠\s*(?:\[DecisionAgent\]|决策Agent[:：]?)\s*([\s\S]*)$/i);
        return { section: '', role: 'DecisionAgent', roleKey: 'decision_agent', body: (m?.[1] ?? msg).trim() };
    }
    // ⚡ [MultiWorker] ... or  ⚡ 并行派发...
    if (msg.startsWith('⚡')) {
        const m = msg.match(/^⚡\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'MultiWorker', roleKey: 'multi_worker', body: (m?.[1] ?? msg).trim() };
    }
    // 📋 决策Agent派发 N 个任务...
    if (msg.startsWith('📋')) {
        return { section: '', role: 'DecisionAgent', roleKey: 'decision_agent', body: msg.replace(/^📋\s*/, '').trim() };
    }
    // 💡 [InnovationAgent] ...
    if (msg.startsWith('💡')) {
        const m = msg.match(/^💡\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'InnovationAgent', roleKey: 'innovation_agent', body: (m?.[1] ?? msg).trim() };
    }
    // 📐 [LayoutAgent] ...
    if (msg.startsWith('📐')) {
        const m = msg.match(/^📐\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'LayoutAgent', roleKey: 'layout_agent', body: (m?.[1] ?? msg).trim() };
    }
    // 👥 [ReviewPanel] ...
    if (msg.startsWith('👥')) {
        const m = msg.match(/^👥\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'ReviewPanel', roleKey: 'review_panel', body: (m?.[1] ?? msg).trim() };
    }
    // ⚖️ 辩论裁决...
    if (msg.startsWith('⚖️')) {
        return { section: '', role: 'FinalDecision', roleKey: 'final_decision', body: msg.replace(/^⚖️\s*/, '').trim() };
    }
    // 💬 [专家名][stance]: ...  辩论专家发言
    const debateMatch = msg.match(/^💬\s*\[([^\]]+)\](?:\[([^\]]*)\])?\s*[:：]\s*([\s\S]*)$/);
    if (debateMatch) {
        const expertName = debateMatch[1];
        const stance = debateMatch[2] || '';
        const body = debateMatch[3].trim();
        let roleKey = 'review_panel';
        if (expertName.includes('红') || stance.toLowerCase().includes('challenge')) roleKey = 'expert_red';
        else if (expertName.includes('蓝') || stance.toLowerCase().includes('support')) roleKey = 'expert_blue';
        else if (expertName.includes('方法') || expertName.toLowerCase().includes('method')) roleKey = 'expert_method';
        else if (expertName.includes('创新') || expertName.toLowerCase().includes('innov')) roleKey = 'expert_innovation';
        return { section: '', role: expertName, roleKey, body };
    }

    // ---- 原有格式：[章节 / agent_name] 内容... ----
    const match = msg.match(/^\[([^\]]+)\s*\/\s*([^\]]+)\]\s*([\s\S]*)$/);
    if (match) {
        const section = match[1].trim();
        const roleRaw = match[2].trim();
        let body = match[3].trim();
        let roleKey = Object.keys(ROLE_STYLES).find(k => roleRaw.toLowerCase().includes(k.replace('_', ''))) ||
            Object.keys(ROLE_STYLES).find(k => roleRaw.toLowerCase().includes(k)) || '';

        // Try parsing structured JSON inside the body
        try {
            const jsonObj = JSON.parse(body);
            if (jsonObj && jsonObj.agent && jsonObj.content) {
                const agent = jsonObj.agent.toLowerCase();
                roleKey = agent.includes('reviewer-红') || agent.includes('reviewer_red') ? 'reviewer_red'
                    : agent.includes('reviewer-蓝') || agent.includes('reviewer_blue') ? 'reviewer_blue'
                        : Object.keys(ROLE_STYLES).find(k => agent.includes(k)) || roleKey;
                body = jsonObj.content;
                return { section: jsonObj.section || section, role: jsonObj.agent, roleKey, body };
            }
        } catch { /* not JSON, continue with text parsing */ }

        // Detect Red/Blue sub-persona inside body text
        if (body.startsWith('Reviewer-红:') || body.startsWith('Reviewer-红：')) {
            roleKey = 'reviewer_red';
            body = body.replace(/^Reviewer-红[:：]\s*/, '');
        } else if (body.startsWith('Reviewer-蓝:') || body.startsWith('Reviewer-蓝：')) {
            roleKey = 'reviewer_blue';
            body = body.replace(/^Reviewer-蓝[:：]\s*/, '');
        } else if (body.startsWith('Reviewer:') || body.startsWith('Reviewer：')) {
            roleKey = 'reviewer';
            body = body.replace(/^Reviewer[:：]\s*/, '');
        }

        return { section, role: roleRaw, roleKey, body };
    }

    // Try parsing standalone JSON entry (no [section/node] wrapper)
    try {
        const jsonObj = JSON.parse(msg);
        if (jsonObj && jsonObj.agent && jsonObj.content) {
            const agent = jsonObj.agent.toLowerCase();
            const roleKey = agent.includes('reviewer-红') ? 'reviewer_red'
                : agent.includes('reviewer-蓝') ? 'reviewer_blue'
                    : Object.keys(ROLE_STYLES).find(k => agent.includes(k)) || '';
            return { section: jsonObj.section || '', role: jsonObj.agent, roleKey, body: jsonObj.content };
        }
    } catch { /* not JSON */ }

    // Pattern: AgentName: 内容...
    const match2 = msg.match(/^(Searcher|Designer|Writer|Reviewer|Coherence):\s*([\s\S]*)$/i);
    if (match2) {
        const roleKey = match2[1].toLowerCase().includes('coherence') ? 'coherence_checker' : match2[1].toLowerCase();
        return { section: '', role: match2[1], roleKey, body: match2[2].trim() };
    }

    return null;
}

export function LogPanel({ messages }: LogPanelProps) {
    const containerRef = useRef<HTMLDivElement>(null);
    const [filter, setFilter] = useState<FilterLevel>('all');

    useEffect(() => {
        if (containerRef.current) {
            containerRef.current.scrollTop = containerRef.current.scrollHeight;
        }
    }, [messages]);

    const KEY_NODES = ['designer', 'reviewer', 'outline_planner', 'coherence_checker', 'reference_compiler',
        'decision_agent', 'multi_worker', 'review_panel', 'final_decision', 'layout_agent', 'innovation_agent'];
    const isKeyMessage = (msg: string) => KEY_NODES.some(n => msg.toLowerCase().includes(n)) ||
        /^[🧠⚡📋💡📐👥⚖️]/.test(msg);
    const isScoreMessage = (msg: string) => msg.includes('评分') || msg.includes('分数') || msg.includes('score') || /\d+分/.test(msg);
    const isDebateMessage = (msg: string) => msg.startsWith('💬') || msg.startsWith('⚖️') || msg.includes('辩论') || msg.includes('stance') || msg.includes('debate');

    const filteredMessages = messages.filter(msg => {
        if (filter === 'all') return true;
        if (filter === 'key') return isKeyMessage(msg);
        if (filter === 'score') return isScoreMessage(msg);
        if (filter === 'debate') return isDebateMessage(msg);
        return true;
    });

    const filterBtns: { level: FilterLevel; label: string }[] = [
        { level: 'all', label: '全部' },
        { level: 'key', label: '关键信息' },
        { level: 'score', label: '仅评分' },
        { level: 'debate', label: '辩论过程' },
    ];

    return (
        <div className="flex flex-col h-full bg-white rounded-lg border border-slate-200 shadow-sm overflow-hidden">
            <div className="bg-slate-50 px-4 py-3 border-b border-slate-200 shrink-0 flex items-center justify-between">
                <h2 className="font-semibold text-slate-700">工作流监控 (Agent 会议记录)</h2>
                <div className="flex gap-1">
                    {filterBtns.map(({ level, label }) => (
                        <button
                            key={level}
                            onClick={() => setFilter(level)}
                            className={`px-2 py-0.5 text-xs rounded font-medium transition-colors ${filter === level
                                ? 'bg-blue-600 text-white'
                                : 'bg-slate-200 text-slate-600 hover:bg-slate-300'
                                }`}
                        >
                            {label}
                        </button>
                    ))}
                    <span className="ml-2 text-xs text-slate-400 self-center">{filteredMessages.length}/{messages.length}</span>
                </div>
            </div>
            <div
                ref={containerRef}
                className="flex-1 overflow-y-auto p-4 space-y-2"
                style={{ minHeight: 0 }}
            >
                {messages.length === 0 ? (
                    <div className="text-slate-400 text-center mt-10">等待任务启动...</div>
                ) : filteredMessages.length === 0 ? (
                    <div className="text-slate-400 text-center mt-10">当前过滤器无匹配消息</div>
                ) : (
                    filteredMessages.map((msg, i) => {
                        const parsed = parseLogMessage(msg);

                        if (parsed) {
                            const style = ROLE_STYLES[parsed.roleKey] || { bg: 'bg-slate-100', text: 'text-slate-700', label: parsed.role };
                            return (
                                <div key={i} className="flex items-start gap-2 py-2 border-b border-slate-100 last:border-0">
                                    <span className={`shrink-0 inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${style.bg} ${style.text}`}>
                                        {style.label}
                                    </span>
                                    {parsed.section && (
                                        <span className="shrink-0 text-xs text-slate-400 py-0.5">[{parsed.section}]</span>
                                    )}
                                    <div className="text-sm text-slate-700 prose prose-sm max-w-none prose-slate flex-1 min-w-0">
                                        <ReactMarkdown>{parsed.body}</ReactMarkdown>
                                    </div>
                                </div>
                            );
                        }

                        return (
                            <div key={i} className="py-2 border-b border-slate-100 last:border-0 text-sm text-slate-700 prose prose-sm max-w-none prose-slate">
                                <ReactMarkdown>{msg}</ReactMarkdown>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

