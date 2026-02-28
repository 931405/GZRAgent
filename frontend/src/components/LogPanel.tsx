import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';

type FilterLevel = 'all' | 'key' | 'score' | 'debate';

interface LogPanelProps {
    messages: string[];
}

// Agent role color mapping - Blue/Teal/Cyan spectrum
const ROLE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
    searcher: { bg: 'bg-sky-100', text: 'text-sky-800', label: '文献专员' },
    designer: { bg: 'bg-blue-100', text: 'text-blue-800', label: '策略师' },
    writer: { bg: 'bg-indigo-100', text: 'text-indigo-800', label: '首席研究员' },
    reviewer: { bg: 'bg-cyan-100', text: 'text-cyan-800', label: '评审专家' },
    reviewer_red: { bg: 'bg-rose-50', text: 'text-rose-700', label: '挑战方·挑刺' },
    reviewer_blue: { bg: 'bg-teal-50', text: 'text-teal-700', label: '建设方·支持' },
    coherence_checker: { bg: 'bg-emerald-50', text: 'text-emerald-700', label: '连贯性审计' },
    reference_compiler: { bg: 'bg-slate-100', text: 'text-slate-700', label: '参考文献' },
    decision_agent: { bg: 'bg-blue-600', text: 'text-white', label: '决策规划' },
    multi_worker: { bg: 'bg-sky-500', text: 'text-white', label: '并行执行' },
    review_panel: { bg: 'bg-indigo-500', text: 'text-white', label: '专家评审' },
    final_decision: { bg: 'bg-slate-700', text: 'text-white', label: '辩论裁决' },
    layout_agent: { bg: 'bg-teal-600', text: 'text-white', label: '排版优化' },
    innovation_agent: { bg: 'bg-cyan-600', text: 'text-white', label: '创新专员' },
    expert_red: { bg: 'bg-rose-100', text: 'text-rose-800', label: '挑战专家' },
    expert_blue: { bg: 'bg-blue-100', text: 'text-blue-800', label: '建设专家' },
    expert_method: { bg: 'bg-slate-200', text: 'text-slate-800', label: '方法论专家' },
    expert_innovation: { bg: 'bg-cyan-100', text: 'text-cyan-800', label: '创新性专家' },
};

function stripEmojis(text: string): string {
    return text.replace(/[\u{1F300}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F900}-\u{1F9FF}\u{1FA70}-\u{1FAFF}\u{1F1E6}-\u{1F1FF}⭐🔴🔵🔬✨⚠️✅📄📝📊🧠⚡📋💡📐👥⚖️💬]/gu, '').trim();
}

function parseLogMessage(msg: string): { section: string; role: string; roleKey: string; body: string } | null {
    // ---- 新架构：emoji 前缀格式 ----
    // 🧠 [DecisionAgent] ...  or  🧠 决策Agent: ...
    if (msg.startsWith('🧠')) {
        const m = msg.match(/^🧠\s*(?:\[DecisionAgent\]|决策Agent[:：]?)\s*([\s\S]*)$/i);
        return { section: '', role: 'DecisionAgent', roleKey: 'decision_agent', body: stripEmojis(m?.[1] ?? msg) };
    }
    // ⚡ [MultiWorker] ... or  ⚡ 并行派发...
    if (msg.startsWith('⚡')) {
        const m = msg.match(/^⚡\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'MultiWorker', roleKey: 'multi_worker', body: stripEmojis(m?.[1] ?? msg) };
    }
    // 📋 决策Agent派发 N 个任务...
    if (msg.startsWith('📋')) {
        return { section: '', role: 'DecisionAgent', roleKey: 'decision_agent', body: stripEmojis(msg.replace(/^📋\s*/, '')) };
    }
    // 💡 [InnovationAgent] ...
    if (msg.startsWith('💡')) {
        const m = msg.match(/^💡\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'InnovationAgent', roleKey: 'innovation_agent', body: stripEmojis(m?.[1] ?? msg) };
    }
    // 📐 [LayoutAgent] ...
    if (msg.startsWith('📐')) {
        const m = msg.match(/^📐\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'LayoutAgent', roleKey: 'layout_agent', body: stripEmojis(m?.[1] ?? msg) };
    }
    // 👥 [ReviewPanel] ...
    if (msg.startsWith('👥')) {
        const m = msg.match(/^👥\s*(?:\[[^\]]+\])?\s*([\s\S]*)$/);
        return { section: '', role: 'ReviewPanel', roleKey: 'review_panel', body: stripEmojis(m?.[1] ?? msg) };
    }
    // ⚖️ 辩论裁决...
    if (msg.startsWith('⚖️')) {
        return { section: '', role: 'FinalDecision', roleKey: 'final_decision', body: stripEmojis(msg.replace(/^⚖️\s*/, '')) };
    }
    // 💬 [专家名][stance]: ...  辩论专家发言
    const debateMatch = msg.match(/^💬\s*\[([^\]]+)\](?:\[([^\]]*)\])?\s*[:：]\s*([\s\S]*)$/);
    if (debateMatch) {
        const expertName = debateMatch[1];
        const stance = debateMatch[2] || '';
        const body = stripEmojis(debateMatch[3]);
        let roleKey = 'review_panel';
        if (expertName.includes('红') || stance.toLowerCase().includes('challenge')) roleKey = 'expert_red';
        else if (expertName.includes('蓝') || stance.toLowerCase().includes('support')) roleKey = 'expert_blue';
        else if (expertName.includes('方法') || expertName.toLowerCase().includes('method')) roleKey = 'expert_method';
        else if (expertName.includes('创新') || expertName.toLowerCase().includes('innov')) roleKey = 'expert_innovation';
        return { section: '', role: stripEmojis(expertName), roleKey, body };
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

        return { section, role: stripEmojis(roleRaw), roleKey, body: stripEmojis(body) };
    }

    // Try parsing standalone JSON entry (no [section/node] wrapper)
    try {
        const jsonObj = JSON.parse(msg);
        if (jsonObj && jsonObj.agent && jsonObj.content) {
            const agent = jsonObj.agent.toLowerCase();
            const roleKey = agent.includes('reviewer-红') ? 'reviewer_red'
                : agent.includes('reviewer-蓝') ? 'reviewer_blue'
                    : Object.keys(ROLE_STYLES).find(k => agent.includes(k)) || '';
            return { section: jsonObj.section || '', role: stripEmojis(jsonObj.agent), roleKey, body: stripEmojis(jsonObj.content) };
        }
    } catch { /* not JSON */ }

    // Pattern: AgentName: 内容...
    const match2 = msg.match(/^(Searcher|Designer|Writer|Reviewer|Coherence):\s*([\s\S]*)$/i);
    if (match2) {
        const roleKey = match2[1].toLowerCase().includes('coherence') ? 'coherence_checker' : match2[1].toLowerCase();
        return { section: '', role: match2[1], roleKey, body: stripEmojis(match2[2]) };
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
        <div className="flex flex-col h-full bg-white rounded-md border border-blue-100 overflow-hidden">
            <div className="bg-[#f0f7ff] px-4 py-2.5 border-b border-blue-100 shrink-0 flex items-center justify-between">
                <h2 className="text-xs font-semibold text-blue-900 tracking-wide uppercase">工作流监控 (会议日志)</h2>
                <div className="flex gap-1.5 items-center">
                    {filterBtns.map(({ level, label }) => (
                        <button
                            key={level}
                            onClick={() => setFilter(level)}
                            className={`px-2 py-0.5 text-[10px] rounded-md font-medium transition-colors border ${filter === level
                                ? 'bg-blue-600 border-blue-600 text-white'
                                : 'bg-white border-blue-200 text-blue-600 hover:bg-blue-50'
                                }`}
                        >
                            {label}
                        </button>
                    ))}
                    <span className="ml-2 text-[10px] text-blue-400 font-mono">{filteredMessages.length}/{messages.length}</span>
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
                                <div key={i} className="flex items-start gap-2 py-2.5 border-b border-blue-50/50 last:border-0">
                                    <span className={`shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold tracking-wide uppercase ${style.bg} ${style.text}`}>
                                        {style.label}
                                    </span>
                                    {parsed.section && (
                                        <span className="shrink-0 text-[10px] font-mono text-blue-400 py-0.5 mt-px border border-blue-100 bg-blue-50/50 rounded px-1">[{parsed.section}]</span>
                                    )}
                                    <div className="text-xs text-blue-900/80 prose prose-sm prose-p:my-0.5 max-w-none prose-blue flex-1 min-w-0">
                                        <ReactMarkdown>{parsed.body}</ReactMarkdown>
                                    </div>
                                </div>
                            );
                        }

                        return (
                            <div key={i} className="py-2.5 border-b border-blue-50/50 last:border-0 text-xs text-blue-900/80 prose prose-sm max-w-none prose-blue">
                                <ReactMarkdown>{stripEmojis(msg)}</ReactMarkdown>
                            </div>
                        );
                    })
                )}
            </div>
        </div>
    );
}

