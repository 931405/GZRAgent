import { useState, useCallback, useEffect } from 'react';
import { Sidebar } from '../components/Sidebar';
import { LogPanel } from '../components/LogPanel';
import { DraftViewer } from '../components/DraftViewer';
import { WorkflowProgress } from '../components/WorkflowProgress';
import { useSSE } from '../hooks/useSSE';
import { api } from '../api/client';

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

    // Version history
    const [draftHistory, setDraftHistory] = useState<DraftSnapshot[]>([]);

    // Toast notification
    const [toast, setToast] = useState<string | null>(null);
    const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 2000); };

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
        } catch (e) {
            alert("启动工作流失败，请检查后端服务是否运行。");
            setBackendOk(false);
        }
    };

    const handleStopWorkflow = async () => {
        if (!runId) return;
        try {
            await api.stopWorkflow(runId);
            showToast('⏹ 工作流已中止');
        } catch {
            alert("中止失败");
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
        <div className="flex h-screen bg-slate-100 font-sans text-slate-800">
            <Sidebar
                onStartWorkflow={handleStartWorkflow}
                isRunning={isRunning}
                onLoadHistory={handleLoadHistory}
            />

            <main className="flex-1 flex flex-col p-4 gap-3 min-w-0 overflow-hidden" style={{ height: '100vh' }}>
                {/* ── 顶部工具栏 ── */}
                <div className="flex items-center gap-2 shrink-0 flex-wrap">
                    <div className="text-xs font-semibold text-slate-500 mr-1">
                        {isRunning ? '🟢 运行中' : (Object.keys(drafts).length > 0 ? '⏹ 已完成' : '⚪ 待启动')}
                    </div>

                    {/* Pending tasks badge */}
                    {pendingTasks.length > 0 && isRunning && (
                        <div className="px-2 py-0.5 rounded text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                            ⚡ 并行 {pendingTasks.length} 任务
                        </div>
                    )}

                    {/* Debate verdict badge */}
                    {debateVerdict && (
                        <div className={`px-2 py-0.5 rounded text-xs font-semibold border ${
                            debateVerdict.revision_required
                                ? 'bg-amber-50 text-amber-700 border-amber-200'
                                : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        }`} title={debateVerdict.conclusion}>
                            {debateVerdict.revision_required ? '⚠️ 需修改' : '✅ 已通过'}
                        </div>
                    )}

                    {/* Reviewer score badge */}
                    {reviewerScore && (
                        <div className={`px-2 py-0.5 rounded text-xs font-bold border ${
                            reviewerScore.score >= 85 ? 'bg-green-50 text-green-700 border-green-200'
                                : reviewerScore.score >= 60 ? 'bg-amber-50 text-amber-700 border-amber-200'
                                    : 'bg-red-50 text-red-700 border-red-200'
                        }`}>
                            评分 {reviewerScore.score.toFixed(0)} · 轮次 {reviewerScore.iteration}
                        </div>
                    )}

                    <div className="flex-1" />

                    {/* Stop button */}
                    {isRunning && (
                        <button
                            onClick={handleStopWorkflow}
                            className="px-3 py-1 bg-red-500 hover:bg-red-600 text-white text-xs font-semibold rounded transition-colors"
                        >
                            ⏹ 停止
                        </button>
                    )}
                    {/* Connection indicator */}
                    <div title={backendOk === true ? '后端已连接' : backendOk === false ? '后端未连接' : '检测中...'}>
                        <div className={`w-2 h-2 rounded-full ${
                            backendOk === true ? 'bg-green-500' : backendOk === false ? 'bg-red-500 animate-pulse' : 'bg-slate-300'
                        }`} />
                    </div>
                </div>

                {/* ── 主内容区：三列布局 ── */}
                <div className="flex-1 grid gap-4 min-h-0" style={{ gridTemplateColumns: '220px 1fr 1.4fr' }}>

                    {/* 左列：流程进度面板 */}
                    <div className="min-h-0 overflow-hidden">
                        <WorkflowProgress
                            currentNode={currentNode}
                            isRunning={isRunning}
                            allDispatchedTasks={allDispatchedTasks}
                            debateRounds={debateRounds}
                            debateVerdict={debateVerdict}
                            reviewerScore={reviewerScore}
                            drafts={drafts}
                            layoutNotes={layoutNotes}
                            innovationPoints={innovationPoints}
                        />
                    </div>

                    {/* 中列：日志 */}
                    <div className="min-h-0 overflow-hidden">
                        <LogPanel messages={messages} />
                    </div>

                    {/* 右列：草稿查看器 */}
                    <div className="min-h-0 overflow-hidden">
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
            </main>

            {/* Toast */}
            {toast && (
                <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-slate-800 text-white px-4 py-2 rounded-lg shadow-lg text-sm font-medium animate-bounce z-50">
                    {toast}
                </div>
            )}
        </div>
    );
}
