import { useState, useEffect, useCallback, useRef } from 'react';

export interface SSEMessage {
    type:
    | 'log' | 'section_start' | 'section_done'
    | 'draft_update' | 'feedback_update' | 'done'
    | 'error' | 'heartbeat' | 'outline_ready' | 'reviewer_direct' | 'stopped'
    // 新架构事件类型
    | 'task_dispatch' | 'debate_update' | 'debate_verdict'
    | 'innovation' | 'layout_done' | 'decision_log' | 'workflow_mode';
    section?: string;
    node?: string;
    message?: string;
    content?: string;
    feedbacks?: any[];
    draft_sections?: Record<string, string>;
    outline?: string;
    score?: number;
    feedback_count?: number;
    iteration?: number;
    // 新架构字段
    tasks?: any[];           // task_dispatch
    count?: number;
    rounds?: any[];          // debate_update
    conclusion?: string;     // debate_verdict
    revision_required?: boolean;
    targets?: any[];
    notes?: string;          // layout_done
    mode?: string;           // workflow_mode
}

export interface DebateVerdict {
    conclusion: string;
    revision_required: boolean;
    targets: any[];
}

const HEARTBEAT_TIMEOUT_MS = 120000;
const RECONNECT_DELAY_MS = 3000;
const MAX_RECONNECT = 5;

export const AGENT_STEPS = [
    'decision_agent', 'multi_worker', 'review_panel', 'final_decision', 'layout_agent',
    // 兼容旧版
    'searcher', 'outline_planner', 'designer', 'writer', 'reviewer',
];

export function useSSE(runId: string | null) {
    const [messages, setMessages] = useState<string[]>([]);
    const [drafts, setDrafts] = useState<Record<string, string>>({});
    const [feedbacks, setFeedbacks] = useState<any[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [currentNode, setCurrentNode] = useState<string>('');
    const [documentOutline, setDocumentOutline] = useState<string>('');
    const [reviewerScore, setReviewerScore] = useState<{ score: number, feedbackCount: number, iteration: number } | null>(null);
    // 新架构状态
    const [pendingTasks, setPendingTasks] = useState<any[]>([]);
    const [allDispatchedTasks, setAllDispatchedTasks] = useState<any[]>([]);
    const [debateRounds, setDebateRounds] = useState<any[]>([]);
    const [debateVerdict, setDebateVerdict] = useState<DebateVerdict | null>(null);
    const [innovationPoints, setInnovationPoints] = useState<string>('');
    const [layoutNotes, setLayoutNotes] = useState<string>('');

    const eventSourceRef = useRef<EventSource | null>(null);
    const heartbeatTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const reconnectCount = useRef(0);

    const messageQueueRef = useRef<string[]>([]);
    const updateTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const flushMessages = useCallback(() => {
        if (messageQueueRef.current.length > 0) {
            // CRITICAL: snapshot the queue BEFORE clearing it.
            // setMessages queues an updater for deferred execution (React 18 batching).
            // If we clear messageQueueRef.current first, the updater would see an empty array.
            const batch = [...messageQueueRef.current];
            messageQueueRef.current = [];
            setMessages(prev => [...prev, ...batch]);
        }
        updateTimeoutRef.current = null;
    }, []);

    const queueMessage = useCallback((msg: string) => {
        messageQueueRef.current.push(msg);
        if (!updateTimeoutRef.current) {
            updateTimeoutRef.current = setTimeout(flushMessages, 100);
        }
    }, [flushMessages]);

    const cleanup = useCallback(() => {
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
        }
        if (heartbeatTimer.current) {
            clearTimeout(heartbeatTimer.current);
            heartbeatTimer.current = null;
        }
    }, []);

    const startListening = useCallback((rid: string, isReconnect = false) => {
        cleanup();
        if (!isReconnect) {
            setIsRunning(true);
            setMessages([]);
            setFeedbacks([]);
            setCurrentNode('');
            setDocumentOutline('');
            setReviewerScore(null);
            setPendingTasks([]);
            setAllDispatchedTasks([]);
            setDebateRounds([]);
            setDebateVerdict(null);
            setInnovationPoints('');
            setLayoutNotes('');
            reconnectCount.current = 0;
        }

        const es = new EventSource(`http://localhost:8000/api/workflow/stream/${rid}`);
        eventSourceRef.current = es;

        const resetHeartbeat = () => {
            if (heartbeatTimer.current) clearTimeout(heartbeatTimer.current);
            heartbeatTimer.current = setTimeout(() => {
                if (reconnectCount.current < MAX_RECONNECT) {
                    reconnectCount.current++;
                    queueMessage(`[系统] 连接中断，正在第 ${reconnectCount.current} 次重连...`);
                    startListening(rid, true);
                } else {
                    queueMessage(`[系统] 重连失败，请手动刷新页面。`);
                    setIsRunning(false);
                }
            }, HEARTBEAT_TIMEOUT_MS);
        };

        es.onmessage = (event) => {
            try {
                const data: SSEMessage = JSON.parse(event.data);
                resetHeartbeat();
                reconnectCount.current = 0;

                if (data.type === 'heartbeat') return;

                if (data.type === 'log' && data.message) {
                    queueMessage(data.message!);
                    if (data.node) setCurrentNode(data.node);
                }
                else if (data.type === 'decision_log' && data.message) {
                    queueMessage(`🧠 ${data.message}`);
                    setCurrentNode('decision_agent');
                }
                else if (data.type === 'section_start') {
                    setCurrentNode('searcher');
                }
                else if (data.type === 'section_done') {
                    setCurrentNode('');
                }
                else if (data.type === 'workflow_mode') {
                    queueMessage(`[系统] 工作流模式: ${data.mode}`);
                }
                else if (data.type === 'task_dispatch' && data.tasks) {
                    setPendingTasks(data.tasks);
                    setAllDispatchedTasks(prev => [...prev, ...(data.tasks as any[])]);
                    const names = (data.tasks as any[]).map(t => `${t.agent_type}(${t.section || '-'})`).join(', ');
                    queueMessage(`📋 决策Agent派发 ${data.count || data.tasks!.length} 个任务: ${names}`);
                    setCurrentNode('multi_worker');
                }
                else if (data.type === 'debate_update' && data.rounds) {
                    setDebateRounds(data.rounds);
                    const latest = (data.rounds as any[]).at(-1);
                    if (latest) queueMessage(`💬 [${latest.reviewer}] ${latest.stance}: ${latest.argument?.slice(0, 60)}...`);
                }
                else if (data.type === 'debate_verdict') {
                    setDebateVerdict({
                        conclusion: data.conclusion || '',
                        revision_required: data.revision_required || false,
                        targets: data.targets || [],
                    });
                    const verdict = data.revision_required ? '⚠️ 需要修改' : '✅ 审核通过';
                    queueMessage(`⚖️ 辩论裁决: ${verdict} | ${data.conclusion?.slice(0, 80) ?? ''}`);
                    setCurrentNode('final_decision');
                }
                else if (data.type === 'innovation' && data.content) {
                    setInnovationPoints(data.content);
                    queueMessage(`💡 创新点提炼完成（${data.content.length}字）`);
                }
                else if (data.type === 'layout_done' && data.notes) {
                    setLayoutNotes(data.notes);
                    queueMessage(`📐 排版审查完成`);
                    setCurrentNode('layout_agent');
                }
                else if (data.type === 'outline_ready' && data.outline) {
                    setDocumentOutline(data.outline);
                }
                else if (data.type === 'reviewer_direct') {
                    setReviewerScore({
                        score: data.score || 0,
                        feedbackCount: data.feedback_count || 0,
                        iteration: data.iteration || 0
                    });
                }
                else if (data.type === 'draft_update' && data.section && data.content) {
                    setDrafts(prev => ({ ...prev, [data.section!]: data.content! }));
                }
                else if (data.type === 'feedback_update' && data.feedbacks) {
                    setFeedbacks(data.feedbacks!);
                }
                else if (data.type === 'done') {
                    if (data.draft_sections) setDrafts(data.draft_sections);
                    setIsRunning(false);
                    setCurrentNode('done');
                    cleanup();
                }
                else if (data.type === 'error') {
                    queueMessage(`[错误] ${data.message}`);
                    setIsRunning(false);
                    cleanup();
                }
                else if (data.type === 'stopped') {
                    queueMessage(`[系统] ${data.message || '工作流已中止'}`);
                    setIsRunning(false);
                    cleanup();
                }
            } catch (err) {
                console.error("Failed to parse SSE message", err);
            }
        };

        es.onerror = () => {
            if (reconnectCount.current < MAX_RECONNECT) {
                reconnectCount.current++;
                queueMessage(`[系统] SSE 连接异常，${RECONNECT_DELAY_MS / 1000}s 后重连...`);
                cleanup();
                setTimeout(() => startListening(rid, true), RECONNECT_DELAY_MS);
            } else {
                setIsRunning(false);
                cleanup();
            }
        };

        resetHeartbeat();
    }, [cleanup]);

    useEffect(() => {
        if (runId) {
            startListening(runId);
            return () => cleanup();
        }
    }, [runId, startListening, cleanup]);

    return {
        messages, drafts, setDrafts, feedbacks, setFeedbacks,
        isRunning, setMessages, currentNode, documentOutline, reviewerScore,
        // 新架构
        pendingTasks, allDispatchedTasks, debateRounds, debateVerdict, innovationPoints, layoutNotes,
    };
}
