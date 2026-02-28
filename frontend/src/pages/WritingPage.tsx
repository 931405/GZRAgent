import { useState, useCallback, useEffect, useRef } from 'react';
import { Sidebar } from '../components/Sidebar';
import { LogPanel } from '../components/LogPanel';
import { DraftViewer } from '../components/DraftViewer';
import { WorkflowTimeline } from '../components/WorkflowTimeline';
import { useSSE } from '../hooks/useSSE';
import { api } from '../api/client';
import { Activity, CheckCircle2, CircleDashed, PanelRightClose, PanelRightOpen, XCircle, Loader2 } from 'lucide-react';

interface DraftSnapshot {
    timestamp: string;
    drafts: Record<string, string>;
    label: string;
}

export function WritingPage() {
    const [runId, setRunId] = useState<string | null>(null);
    const [projectInfo, setProjectInfo] = useState<{ type: string, topic: string } | null>(null);

    const { messages, drafts, setDrafts, feedbacks, isRunning, setMessages, currentNode, reviewerScore,
        pendingTasks, allDispatchedTasks, debateRounds, debateVerdict, innovationPoints, layoutNotes } = useSSE(runId);

    // UI Layout state
    const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
    const [isRightPaneCollapsed, setIsRightPaneCollapsed] = useState(false);

    // Auto-collapse sidebar when workflow starts; reset isStopping when workflow ends
    useEffect(() => {
        if (isRunning) {
            setIsSidebarCollapsed(true);
        } else {
            setIsStopping(false);
        }
    }, [isRunning]);

    // Version history
    const [draftHistory, setDraftHistory] = useState<DraftSnapshot[]>([]);

    // Toast notification queue
    const [toasts, setToasts] = useState<{ id: number; msg: string; type?: 'error' | 'success' }[]>([]);
    const toastIdCounter = useRef(0);

    const showToast = useCallback((msg: string, type: 'error' | 'success' = 'success') => {
        const id = ++toastIdCounter.current;
        setToasts(prev => [...prev, { id, msg, type }]);
        setTimeout(() => {
            setToasts(prev => prev.filter(t => t.id !== id));
        }, 3500);
    }, []);

    // Connection status
    const [backendOk, setBackendOk] = useState<boolean | null>(null);
    useEffect(() => {
        fetch('http://localhost:8000/api/')
            .then(r => r.ok ? setBackendOk(true) : setBackendOk(false))
            .catch(() => setBackendOk(false));
    }, []);

    const saveDraftSnapshot = useCallback((label: string, currentDrafts: Record<string, string>) => {
        if (Object.keys(currentDrafts).length === 0) return;
        setDraftHistory(prev => [
            ...prev,
            {
                timestamp: new Date().toLocaleTimeString('zh-CN'),
                drafts: { ...currentDrafts },
                label,
            }
        ]);
    }, []);

    const handleStartWorkflow = async (req: any) => {
        try {
            if (Object.keys(drafts).length > 0) {
                saveDraftSnapshot('启动前快照', drafts);
            }
            setProjectInfo({ type: req.project_type, topic: req.research_topic });
            const payload = { ...req, draft_sections: drafts };
            const res = await api.startWorkflow(payload);
            setRunId(res.run_id);
            setBackendOk(true);
        } catch (e: any) {
            showToast(`✖ 启动失败: ${e.customMessage || e.message || "请求异常"}`, 'error');
            setBackendOk(false);
        }
    };

    const [isStopping, setIsStopping] = useState(false);

    const handleStopWorkflow = async () => {
        if (!runId || isStopping) return;
        setIsStopping(true);
        try {
            await api.stopWorkflow(runId);
            showToast('⏹ 工作流已中止');
            // Fallback: force isRunning off after 5s if SSE 'stopped' event doesn't arrive
            setTimeout(() => {
                setIsStopping(false);
            }, 5000);
        } catch (e: any) {
            showToast(`✖ 中止失败: ${e.customMessage || e.message}`, 'error');
            setIsStopping(false);
        }
    };

    const handleLoadHistory = (data: any) => {
        setRunId(null);
        setProjectInfo({ type: data.project_type || "未知", topic: data.research_topic || "未知" });
        setDrafts(data.draft_sections || {});
        setMessages(data.discussion_history || []);
    };

    const handleSaveDraft = (section: string, newContent: string) => {
        saveDraftSnapshot(`手动编辑 [${section}]`, drafts);
        setDrafts(prev => ({ ...prev, [section]: newContent }));
        showToast('✅ 已保存');
    };

    const handleRestoreSnapshot = (snapshot: DraftSnapshot) => {
        saveDraftSnapshot('回退前快照', drafts);
        setDrafts(snapshot.drafts);
        showToast('↩ 已回退');
    };

    return (
        <div className="flex h-screen bg-[#eef6ff] font-sans text-blue-900">
            <Sidebar
                onStartWorkflow={handleStartWorkflow}
                isRunning={isRunning}
                onLoadHistory={handleLoadHistory}
                isCollapsed={isSidebarCollapsed}
                setIsCollapsed={setIsSidebarCollapsed}
            />

            <main className="flex-1 flex flex-col p-4 gap-4 min-w-0 overflow-hidden relative" style={{ height: '100vh' }}>
                {/* ── 顶部工具栏 ── */}
                <div className="flex items-center gap-3 shrink-0 flex-wrap bg-white px-4 py-2.5 rounded-md border border-blue-100">
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-blue-800 border-r border-blue-100 pr-3">
                        {isRunning ? (
                            <><Activity size={16} className="text-blue-500 animate-pulse" /> 运行中</>
                        ) : (Object.keys(drafts).length > 0 ? (
                            <><CheckCircle2 size={16} className="text-emerald-500" /> 已完成</>
                        ) : (
                            <><CircleDashed size={16} className="text-slate-400" /> 待启动</>
                        ))}
                    </div>

                    {/* Pending tasks badge */}
                    {pendingTasks.length > 0 && isRunning && (
                        <div className="px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200 flex items-center gap-1">
                            <Activity size={12} className="animate-spin" /> 并行 {pendingTasks.length} 任务
                        </div>
                    )}

                    {/* Debate verdict badge */}
                    {debateVerdict && (
                        <div className={`px-2.5 py-1 rounded-md text-xs font-semibold border flex items-center gap-1 ${debateVerdict.revision_required
                            ? 'bg-amber-50 text-amber-700 border-amber-200'
                            : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            }`} title={debateVerdict.conclusion}>
                            {debateVerdict.revision_required ? <><Activity size={12} /> 需修改</> : <><CheckCircle2 size={12} /> 已通过</>}
                        </div>
                    )}

                    {/* Reviewer score badge */}
                    {reviewerScore && (
                        <div className={`px-2.5 py-1 rounded-md text-xs font-bold border ${reviewerScore.score >= 85 ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                            : reviewerScore.score >= 60 ? 'bg-amber-50 text-amber-700 border-amber-200'
                                : 'bg-rose-50 text-rose-700 border-rose-200'
                            }`}>
                            评分 {reviewerScore.score.toFixed(0)} · 轮次 {reviewerScore.iteration}
                        </div>
                    )}

                    <div className="flex-1" />

                    {/* Stop button */}
                    {isRunning && (
                        <button
                            onClick={handleStopWorkflow}
                            disabled={isStopping}
                            className={`px-4 py-1.5 text-xs font-semibold rounded-md transition-colors flex items-center gap-1.5 ${isStopping
                                ? 'bg-slate-100 text-slate-400 border border-slate-200 cursor-not-allowed'
                                : 'bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200'
                                }`}
                        >
                            {isStopping ? (
                                <><Loader2 size={14} className="animate-spin" /> 正在停止...</>
                            ) : (
                                <><XCircle size={14} /> 停止工作流</>
                            )}
                        </button>
                    )}
                    {/* Connection indicator */}
                    <div className="flex items-center gap-1 ml-2" title={backendOk === true ? '后端已连接' : backendOk === false ? '后端未连接' : '检测中...'}>
                        <div className={`w-2 h-2 rounded-full ${backendOk === true ? 'bg-emerald-500' : backendOk === false ? 'bg-rose-500 animate-pulse' : 'bg-slate-300'
                            }`} />
                        <span className="text-xs text-slate-400 font-mono">APP API</span>
                    </div>
                </div>

                {/* ── 主内容区：可折叠双列布局 ── */}
                <div className="flex-1 flex gap-4 min-h-0 relative">

                    {/* 左侧工作流监控区 */}
                    <div className={`flex flex-col gap-4 min-w-0 transition-all duration-300 ease-in-out ${isRightPaneCollapsed ? 'w-full' : 'w-[40%]'}`}>
                        <WorkflowTimeline currentNode={currentNode} isRunning={isRunning} />

                        <div className="flex-1 min-h-0">
                            <LogPanel messages={messages} />
                        </div>
                    </div>

                    {/* 右侧边栏展开/折叠按钮 */}
                    <button
                        onClick={() => setIsRightPaneCollapsed(!isRightPaneCollapsed)}
                        className={`absolute top-1/2 -mt-4 bg-white border border-blue-200 text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded-md p-1 z-10 shadow-sm transition-all duration-300 ${isRightPaneCollapsed ? 'right-0' : 'right-[60%] mr-2'}`}
                        title={isRightPaneCollapsed ? "展开文档预览" : "折叠文档预览"}
                    >
                        {isRightPaneCollapsed ? <PanelRightOpen size={18} /> : <PanelRightClose size={18} />}
                    </button>

                    {/* 右侧文档预览区 */}
                    <div className={`min-h-0 overflow-hidden transition-all duration-300 ease-in-out ${isRightPaneCollapsed ? 'w-0 opacity-0' : 'w-[60%] opacity-100'}`}>
                        <div className="h-full w-full">
                            <DraftViewer
                                drafts={drafts}
                                feedbacks={feedbacks}
                                projectInfo={projectInfo}
                                onSaveDraft={handleSaveDraft}
                                draftHistory={draftHistory}
                                onRestoreSnapshot={handleRestoreSnapshot}
                                innovationPoints={innovationPoints}
                                layoutNotes={layoutNotes}
                                debateRounds={debateRounds}
                                debateVerdict={debateVerdict}
                            />
                        </div>
                    </div>
                </div>
            </main>

            {/* Toast Queue */}
            <div className="fixed bottom-6 left-1/2 -translate-x-1/2 flex flex-col items-center gap-2 z-[9999] pointer-events-none">
                {toasts.map(t => (
                    <div key={t.id} className={`px-5 py-2.5 rounded-md shadow-lg text-sm font-medium animate-in fade-in slide-in-from-bottom-2 ${t.type === 'error' ? 'bg-rose-600 text-white' : 'bg-blue-800 text-white'}`}>
                        {t.msg}
                    </div>
                ))}
            </div>
        </div>
    );
}
