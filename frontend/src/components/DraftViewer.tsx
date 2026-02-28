import { useState, useMemo, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import { ALL_SECTIONS } from './Sidebar';
import { api } from '../api/client';
import { Download, Pencil, Save, X, Clock, RotateCcw, ChevronDown, Image, Upload, FileText, AlertTriangle, Lightbulb, CheckCircle2 } from 'lucide-react';

interface DraftSnapshot {
    timestamp: string;
    drafts: Record<string, string>;
    label: string;
}

interface DraftViewerProps {
    drafts: Record<string, string>;
    feedbacks: any[];
    projectInfo: { type: string; topic: string; } | null;
    onSaveDraft: (section: string, newContent: string) => void;
    draftHistory: DraftSnapshot[];
    onRestoreSnapshot: (snapshot: DraftSnapshot) => void;
    // ---- 新架构数据 ----
    innovationPoints?: string;
    layoutNotes?: string;
    debateRounds?: any[];
    debateVerdict?: any;
}

function ScoreBar({ label, score, color }: { label: string; score: number; color: string }) {
    return (
        <div>
            <div className="flex justify-between text-xs text-slate-500 mb-1">
                <span>{label}</span>
                <span className="font-mono font-semibold">{score}</span>
            </div>
            <div className="w-full bg-slate-200 rounded-full h-2.5">
                <div className={`${color} h-2.5 rounded-full transition-all duration-500`} style={{ width: `${Math.min(score, 100)}%` }}></div>
            </div>
        </div>
    );
}

function OverallBadge({ score }: { score: number }) {
    const cls = score >= 85
        ? 'bg-green-100 text-green-700 border-green-200'
        : score >= 60
            ? 'bg-amber-100 text-amber-700 border-amber-200'
            : 'bg-red-100 text-red-700 border-red-200';
    const label = score >= 85 ? '优秀' : score >= 60 ? '待修正' : '需重构';
    return (
        <span className={`text-xs font-bold px-2.5 py-1 rounded-full border ${cls}`}>
            {label} {score}
        </span>
    );
}

function PersonaBadge({ persona }: { persona?: string }) {
    if (!persona) return null;
    const p = persona.toLowerCase();
    if (p.includes('红') || p.includes('挑战') || p.includes('challenge')) {
        return <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-rose-50 text-rose-700 border border-rose-200">挑战方·挑刺</span>;
    }
    if (p.includes('蓝') || p.includes('建设') || p.includes('support')) {
        return <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-teal-50 text-teal-700 border border-teal-200">建设方·支持</span>;
    }
    if (p.includes('方法') || p.includes('method')) {
        return <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-slate-100 text-slate-700 border border-slate-200">方法论</span>;
    }
    if (p.includes('创新') || p.includes('innov')) {
        return <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-cyan-50 text-cyan-700 border border-cyan-200">创新性</span>;
    }
    return <span className="text-[10px] font-bold px-2 py-0.5 rounded-sm bg-blue-50 text-blue-700 border border-blue-200">{persona}</span>;
}

export function DraftViewer({ drafts, feedbacks, projectInfo, onSaveDraft, draftHistory, onRestoreSnapshot, innovationPoints, layoutNotes, debateRounds, debateVerdict }: DraftViewerProps) {
    const [activeTab, setActiveTab] = useState<'draft' | 'feedback' | 'innovation' | 'debate' | 'preview' | 'history'>('draft');
    const availableSections = Object.keys(drafts).length > 0 ? Object.keys(drafts) : [ALL_SECTIONS[0]];
    const [viewFocus, setViewFocus] = useState(availableSections[availableSections.length - 1]);
    const [isEditing, setIsEditing] = useState(false);
    const [editContent, setEditContent] = useState('');

    const focusFeedbacks = feedbacks.filter(fb => fb.section === viewFocus);
    const feedbackCount = feedbacks.length;

    // ---- 导出选项面板状态 ----
    const [showExportPanel, setShowExportPanel] = useState(false);
    const [generateImages, setGenerateImages] = useState(true);
    const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
    const [availableTemplates, setAvailableTemplates] = useState<Array<{ filename: string; detected_sections: string[] }>>([]);
    const [isExporting, setIsExporting] = useState(false);
    const [isExportingPdf, setIsExportingPdf] = useState(false);
    const [uploadingTemplate, setUploadingTemplate] = useState(false);
    const exportPanelRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);

    // 加载模板列表
    useEffect(() => {
        if (showExportPanel) {
            api.listExportTemplates().then(setAvailableTemplates).catch(() => setAvailableTemplates([]));
        }
    }, [showExportPanel]);

    // 点击面板外关闭
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (exportPanelRef.current && !exportPanelRef.current.contains(e.target as Node)) {
                setShowExportPanel(false);
            }
        };
        if (showExportPanel) document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [showExportPanel]);

    const handleExport = async () => {
        if (!projectInfo) return;
        setIsExporting(true);
        setShowExportPanel(false);
        try {
            const blob = await api.exportWord({
                project_type: projectInfo.type,
                research_topic: projectInfo.topic,
                draft_sections: drafts,
                generate_images: generateImages,
                template_name: selectedTemplate,
            });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${projectInfo.type}_申请书.docx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (e) {
            alert('导出失败，请检查后端日志。');
        } finally {
            setIsExporting(false);
        }
    };

    const handleExportPdf = async () => {
        if (!projectInfo) return;
        setIsExportingPdf(true);
        setShowExportPanel(false);
        try {
            const blob = await api.exportPdf({
                project_type: projectInfo.type,
                research_topic: projectInfo.topic,
                draft_sections: drafts,
                generate_images: generateImages,
            });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${projectInfo.type}_申请书.pdf`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (e) {
            alert('PDF 导出失败，请检查后端日志。您可能需要先撰写完成包含表格或公式的章节。');
        } finally {
            setIsExportingPdf(false);
        }
    };

    const handleTemplateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setUploadingTemplate(true);
        try {
            const result = await api.uploadExportTemplate(file);
            setAvailableTemplates(prev => [...prev, { filename: result.filename, detected_sections: result.detected_sections }]);
            setSelectedTemplate(result.filename);
            alert(`模板上传成功！检测到章节: ${result.detected_sections.join(', ') || '未识别到标准章节'}`);
        } catch {
            alert('模板上传失败');
        } finally {
            setUploadingTemplate(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    // Extract headings from current draft for TOC
    const tocItems = useMemo(() => {
        const allContent = ALL_SECTIONS.map(s => drafts[s] ? { section: s, content: drafts[s] } : null).filter(Boolean) as { section: string; content: string }[];
        const items: { section: string; heading: string; level: number }[] = [];
        for (const { section, content } of allContent) {
            items.push({ section, heading: section, level: 1 });
            const headingMatches = content.match(/^#{1,3}\s+.+$/gm);
            if (headingMatches) {
                for (const h of headingMatches.slice(0, 5)) {
                    const level = (h.match(/^#+/) || [''])[0].length + 1;
                    items.push({ section, heading: h.replace(/^#+\s*/, ''), level: Math.min(level, 3) });
                }
            }
        }
        return items;
    }, [drafts]);

    const tabs = [
        { key: 'feedback' as const, label: '修订建议', badge: feedbackCount > 0 ? feedbackCount : undefined },
        { key: 'innovation' as const, label: '创新点分析', badge: innovationPoints ? undefined : undefined },
        { key: 'debate' as const, label: '辩论报告', badge: debateVerdict ? (debateVerdict.revision_required ? '需改' : undefined) : undefined },
        { key: 'preview' as const, label: '完整预览' },
        { key: 'history' as const, label: '版本历史', badge: draftHistory.length > 0 ? draftHistory.length : undefined },
    ];

    return (
        <div className="flex flex-col h-full bg-white rounded-md border border-blue-100 overflow-hidden" style={{ minHeight: 0 }}>
            {/* Header Tabs */}
            <div className="bg-[#f0f7ff] px-4 pt-3 border-b border-blue-100 flex justify-between items-end shrink-0">
                <div className="flex gap-0.5">
                    {tabs.map(t => (
                        <button
                            key={t.key}
                            className={`pb-2 px-2.5 border-b-2 font-medium text-xs transition-colors relative ${activeTab === t.key ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-500 hover:text-slate-700'}`}
                            onClick={() => setActiveTab(t.key)}
                        >
                            {t.label}
                            {t.badge !== undefined && (
                                <span className={typeof t.badge === 'string' ? "ml-1 inline-flex items-center justify-center px-1 h-4 text-[9px] font-bold rounded-full bg-rose-500 text-white" : "ml-1 inline-flex items-center justify-center w-4 h-4 text-[9px] font-bold rounded-full bg-rose-500 text-white"}>
                                    {typeof t.badge === 'number' && t.badge > 99 ? '99+' : t.badge}
                                </span>
                            )}
                        </button>
                    ))}
                </div>

                {/* 导出按钟 + 选项面板 */}
                <div className="relative mb-2" ref={exportPanelRef}>
                    <div className="flex items-center gap-0">
                        <button
                            onClick={handleExport}
                            disabled={Object.keys(drafts).length === 0 || isExporting}
                            className="text-xs flex gap-1 items-center text-slate-600 hover:text-slate-900 disabled:opacity-40 disabled:cursor-not-allowed border-y border-l px-2 py-1 rounded-l bg-white hover:bg-slate-50 transition-colors"
                            title={isExporting ? '导出中...' : Object.keys(drafts).length === 0 ? '请先生成内容' : '导出为 Word 文档'}
                        >
                            {isExporting ? (
                                <span className="animate-spin inline-block w-3 h-3 border-2 border-slate-400 border-t-transparent rounded-full" />
                            ) : (
                                <Download size={12} />
                            )}
                            {isExporting ? '导出中...' : '导出'}
                        </button>
                        <button
                            onClick={() => setShowExportPanel(v => !v)}
                            disabled={Object.keys(drafts).length === 0 || isExporting || isExportingPdf}
                            className="text-xs flex items-center text-slate-500 hover:text-slate-800 disabled:opacity-40 disabled:cursor-not-allowed border px-1.5 py-1 rounded-r bg-white hover:bg-slate-50 transition-colors"
                            title="导出选项"
                        >
                            <ChevronDown size={11} />
                        </button>
                    </div>

                    {/* 选项面板 */}
                    {showExportPanel && (
                        <div className="absolute right-0 top-full mt-1 w-72 bg-white border border-slate-200 rounded-xl shadow-xl z-50 p-4 text-xs">
                            <div className="font-semibold text-slate-700 mb-3 text-sm">导出选项</div>

                            {/* 配图开关 */}
                            <div className="flex items-start gap-3 mb-4 p-3 rounded-lg bg-slate-50 border border-slate-100">
                                <Image size={14} className="text-slate-500 mt-0.5 shrink-0" />
                                <div className="flex-1">
                                    <div className="font-medium text-slate-700 mb-0.5">自动生成章节配图</div>
                                    <div className="text-slate-500 text-[10px] mb-2">为「研究方案与可行性」等章节自动生成 Mermaid 技术路线图（需要网络，耗时约1-2分钟）</div>
                                    <label className="flex items-center gap-2 cursor-pointer">
                                        <div
                                            onClick={() => setGenerateImages(v => !v)}
                                            className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${generateImages ? 'bg-blue-500' : 'bg-slate-300'}`}
                                        >
                                            <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${generateImages ? 'translate-x-4' : 'translate-x-0.5'}`} />
                                        </div>
                                        <span className={generateImages ? 'text-blue-700 font-medium' : 'text-slate-500'}>{generateImages ? '已开启' : '已关闭'}</span>
                                    </label>
                                </div>
                            </div>

                            {/* 模板选择 */}
                            <div className="mb-3">
                                <div className="flex items-center gap-1.5 font-medium text-slate-700 mb-2">
                                    <FileText size={12} />选择 Word 模板
                                </div>
                                <select
                                    value={selectedTemplate ?? ''}
                                    onChange={e => setSelectedTemplate(e.target.value || null)}
                                    className="w-full p-2 border border-slate-200 rounded-lg text-xs bg-white"
                                >
                                    <option value="">— 不使用模板（标准格式）—</option>
                                    {availableTemplates.map(t => (
                                        <option key={t.filename} value={t.filename}>
                                            {t.filename} {t.detected_sections.length > 0 ? `(识别 ${t.detected_sections.length} 章节)` : ''}
                                        </option>
                                    ))}
                                </select>

                                {/* 上传模板按钟 */}
                                <input ref={fileInputRef} type="file" accept=".docx" className="hidden" onChange={handleTemplateUpload} />
                                <button
                                    onClick={() => fileInputRef.current?.click()}
                                    disabled={uploadingTemplate}
                                    className="mt-2 w-full flex items-center justify-center gap-1.5 px-3 py-1.5 border border-dashed border-slate-300 rounded-lg text-slate-500 hover:text-blue-600 hover:border-blue-300 transition-colors text-[11px]"
                                >
                                    <Upload size={12} /> {uploadingTemplate ? '上传中...' : '上传 Word 模板 (.docx)'}
                                </button>
                                {selectedTemplate && (
                                    <div className="mt-1 text-[10px] text-blue-600">✓ 将使用: {selectedTemplate}</div>
                                )}
                            </div>

                            <div className="flex gap-2">
                                <button
                                    onClick={handleExport}
                                    disabled={isExporting || isExportingPdf}
                                    className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white py-2 rounded-lg font-semibold text-xs transition-colors flex items-center justify-center gap-2"
                                >
                                    {isExporting ? (
                                        <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                                    ) : (
                                        <Download size={13} />
                                    )}
                                    {isExporting ? '导出中...' : '导出 Word'}
                                </button>
                                <button
                                    onClick={handleExportPdf}
                                    disabled={isExporting || isExportingPdf}
                                    className="flex-1 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white py-2 rounded-lg font-semibold text-xs transition-colors flex items-center justify-center gap-2"
                                >
                                    {isExportingPdf ? (
                                        <span className="animate-spin inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                                    ) : (
                                        <Download size={13} />
                                    )}
                                    {isExportingPdf ? '导出中...' : '导出 PDF (原生排版)'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Content Area */}
            <div className="flex-1 overflow-y-auto p-5" style={{ minHeight: 0 }}>

                {/* ========== TAB 1: 章节草稿 ========== */}
                {activeTab === 'draft' && (
                    <div>
                        <div className="mb-4 flex items-center justify-between">
                            <div className="flex items-center gap-3">
                                <label className="text-xs font-semibold text-slate-600">章节:</label>
                                <select value={viewFocus} onChange={e => { setViewFocus(e.target.value); setIsEditing(false); }} className="p-1.5 border rounded text-xs w-44">
                                    {availableSections.map(s => <option key={s} value={s}>{s}</option>)}
                                </select>
                            </div>
                            {drafts[viewFocus] && !isEditing && (
                                <button onClick={() => { setEditContent(drafts[viewFocus]); setIsEditing(true); }} className="flex items-center gap-1 px-2.5 py-1 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs rounded font-medium border border-slate-300">
                                    <Pencil size={12} /> 编辑
                                </button>
                            )}
                            {isEditing && (
                                <div className="flex gap-2">
                                    <button onClick={() => setIsEditing(false)} className="flex items-center gap-1 px-2.5 py-1 text-slate-600 hover:bg-slate-100 text-xs rounded border border-slate-300"><X size={12} /> 取消</button>
                                    <button onClick={() => { onSaveDraft(viewFocus, editContent); setIsEditing(false); }} className="flex items-center gap-1 px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded font-medium shadow-sm"><Save size={12} /> 保存</button>
                                </div>
                            )}
                        </div>

                        {!drafts[viewFocus] ? (
                            <div className="text-slate-400 text-center py-16 text-sm">该章节尚无内容，请先在左侧启动撰写流程。</div>
                        ) : isEditing ? (
                            <textarea value={editContent} onChange={e => setEditContent(e.target.value)} className="w-full h-[450px] p-3 border-2 border-blue-200 focus:border-blue-400 focus:outline-none rounded-lg text-xs font-mono text-slate-800 resize-y" />
                        ) : (
                            <div className="prose prose-slate max-w-none prose-sm"><ReactMarkdown>{drafts[viewFocus]}</ReactMarkdown></div>
                        )}

                        {focusFeedbacks.length > 0 && !isEditing && (
                            <div className="mt-5 p-3 bg-amber-50 border border-amber-200 rounded-lg flex items-center justify-between">
                                <span className="text-xs text-amber-800">本章节有 <strong>{focusFeedbacks.length}</strong> 条评审修改建议</span>
                                <button onClick={() => setActiveTab('feedback')} className="text-xs text-amber-700 font-semibold hover:text-amber-900 underline">查看修订建议 →</button>
                            </div>
                        )}
                    </div>
                )}

                {/* ========== TAB 2: 修订建议 ========== */}
                {activeTab === 'feedback' && (
                    <div>
                        <div className="mb-4 flex items-center gap-3">
                            <label className="text-xs font-semibold text-slate-600">筛选:</label>
                            <select value={viewFocus} onChange={e => setViewFocus(e.target.value)} className="p-1.5 border rounded text-xs w-44">
                                {availableSections.map(s => <option key={s} value={s}>{s}</option>)}
                            </select>
                            <span className="text-[10px] text-slate-400">{focusFeedbacks.length} / {feedbackCount} 条</span>
                        </div>

                        {focusFeedbacks.length === 0 ? (
                            <div className="text-slate-400 text-center py-16 text-sm">
                                {feedbackCount === 0 ? '暂无评审建议。运行工作流后，红脸/蓝脸专家的打分和修改建议将展示在此处。' : `「${viewFocus}」暂无修订建议。`}
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {focusFeedbacks.map((fb, i) => {
                                    const dims = [
                                        { label: '创新性', score: fb.innovation_score ?? fb.overall_score ?? 0, color: 'bg-violet-500' },
                                        { label: '逻辑性', score: fb.logic_score ?? fb.overall_score ?? 0, color: 'bg-sky-500' },
                                        { label: '可行性', score: fb.feasibility_score ?? fb.overall_score ?? 0, color: 'bg-emerald-500' },
                                    ];
                                    const overall = fb.overall_score ?? fb.score ?? 0;
                                    return (
                                        <div key={i} className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
                                            <div className="bg-slate-50 px-4 py-2.5 flex justify-between items-center border-b border-slate-100">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-xs font-bold text-slate-700">#{i + 1}</span>
                                                    <PersonaBadge persona={fb.reviewer_persona} />
                                                    <OverallBadge score={overall} />
                                                </div>
                                            </div>
                                            <div className="px-4 py-2 grid grid-cols-3 gap-3 border-b border-slate-100 bg-slate-50/50">
                                                {dims.map(d => <ScoreBar key={d.label} {...d} />)}
                                            </div>
                                            <div className="px-4 py-3 space-y-2.5 text-xs">
                                                {/* Macro-level problem description */}
                                                {fb.problem_description && (
                                                    <div className="flex gap-2 items-start">
                                                        <span className="shrink-0 w-5 h-5 rounded bg-rose-50 text-rose-600 flex items-center justify-center mt-0.5"><AlertTriangle size={12} /></span>
                                                        <div className="flex-1">
                                                            <div className="text-[10px] font-semibold text-rose-700 mb-0.5">问题描述</div>
                                                            <div className="text-slate-800 bg-rose-50/50 px-2.5 py-1.5 rounded border border-rose-100">{fb.problem_description}</div>
                                                        </div>
                                                    </div>
                                                )}
                                                {/* Macro-level improvement direction */}
                                                {fb.improvement_direction && (
                                                    <div className="flex gap-2 items-start">
                                                        <span className="shrink-0 w-5 h-5 rounded bg-emerald-50 text-emerald-600 flex items-center justify-center mt-0.5"><Lightbulb size={12} /></span>
                                                        <div className="flex-1">
                                                            <div className="text-[10px] font-semibold text-emerald-700 mb-0.5">改进方向</div>
                                                            <div className="text-slate-800 bg-emerald-50/50 px-2.5 py-1.5 rounded border border-emerald-100">{fb.improvement_direction}</div>
                                                        </div>
                                                    </div>
                                                )}
                                                {/* Fallback for old format with original/suggested text */}
                                                {fb.original_text && (
                                                    <div className="flex gap-2 items-start">
                                                        <span className="shrink-0 w-4 h-4 rounded bg-rose-50 text-rose-600 flex items-center justify-center text-[10px] font-bold mt-0.5">-</span>
                                                        <div className="flex-1 text-rose-800 bg-rose-50/50 px-2.5 py-1.5 rounded border border-rose-100 line-through">{fb.original_text}</div>
                                                    </div>
                                                )}
                                                {fb.suggested_text && (
                                                    <div className="flex gap-2 items-start">
                                                        <span className="shrink-0 w-4 h-4 rounded bg-emerald-50 text-emerald-600 flex items-center justify-center text-[10px] font-bold mt-0.5">+</span>
                                                        <div className="flex-1 text-emerald-800 bg-emerald-50/50 px-2.5 py-1.5 rounded border border-emerald-100">{fb.suggested_text}</div>
                                                    </div>
                                                )}
                                                <div className="text-slate-600 pt-1"><strong className="text-slate-700">理由：</strong>{fb.reason}</div>
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                )}

                {/* ========== TAB 3 (新): 创新点 ========== */}
                {activeTab === 'innovation' && (
                    <div>
                        <div className="mb-4 flex items-center gap-2">
                            <span className="text-xs font-semibold text-cyan-800 bg-cyan-50 px-2.5 py-1 rounded-sm border border-cyan-200 flex items-center gap-1.5"><Lightbulb size={12} /> InnovationAgent 生成</span>
                        </div>
                        {!innovationPoints ? (
                            <div className="text-slate-400 text-center py-16 text-sm">
                                暂无创新点分析。启动工作流后，InnovationAgent 将自动提炼本项目的创新点并生成「特色与创新」章节内容。
                            </div>
                        ) : (
                            <div className="prose prose-slate max-w-none prose-sm bg-lime-50 p-5 rounded-xl border border-lime-200">
                                <ReactMarkdown>{innovationPoints}</ReactMarkdown>
                            </div>
                        )}
                    </div>
                )}

                {/* ========== TAB 4 (新): 辩论报告 ========== */}
                {activeTab === 'debate' && (
                    <div className="space-y-5">
                        {/* 最终裁决卡片 */}
                        {debateVerdict ? (
                            <div className={`p-4 rounded-xl border-2 ${debateVerdict.revision_required ? 'bg-rose-50 border-rose-200' : 'bg-emerald-50 border-emerald-200'}`}>
                                <div className="flex items-center gap-2 mb-2">
                                    <span className={`flex items-center justify-center w-6 h-6 rounded-full ${debateVerdict.revision_required ? 'text-rose-600 bg-rose-100' : 'text-emerald-600 bg-emerald-100'}`}>
                                        {debateVerdict.revision_required ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />}
                                    </span>
                                    <span className={`font-bold text-sm ${debateVerdict.revision_required ? 'text-rose-700' : 'text-emerald-700'}`}>
                                        辩论裁决: {debateVerdict.revision_required ? '需要修订' : '质量达标'}
                                    </span>
                                    {typeof debateVerdict.final_score === 'number' && (
                                        <span className={`ml-auto text-xs font-bold px-3 py-1 rounded-full ${debateVerdict.final_score >= 80 ? 'bg-emerald-100 text-emerald-700' : debateVerdict.final_score >= 60 ? 'bg-amber-100 text-amber-700' : 'bg-rose-100 text-rose-700'}`}>
                                            综合得分 {debateVerdict.final_score}
                                        </span>
                                    )}
                                </div>
                                {debateVerdict.conclusion && (
                                    <p className="text-sm text-slate-700 mt-1">{debateVerdict.conclusion}</p>
                                )}
                                {Array.isArray(debateVerdict.revision_targets) && debateVerdict.revision_targets.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-1">
                                        {debateVerdict.revision_targets.map((t: string, i: number) => (
                                            <span key={i} className="text-xs px-2 py-0.5 bg-rose-100 text-rose-700 rounded-full border border-rose-200">{t}</span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="text-slate-400 text-center py-8 text-sm bg-slate-50 rounded-xl border border-slate-200">
                                暂无辩论结果。工作流完成后，专家辩论记录将在此显示。
                            </div>
                        )}

                        {/* 辩论轮次 */}
                        {Array.isArray(debateRounds) && debateRounds.length > 0 && (
                            <div>
                                {[1, 2].map(round => {
                                    const roundEntries = debateRounds.filter((r: any) => r.round === round);
                                    if (roundEntries.length === 0) return null;
                                    return (
                                        <div key={round} className="mb-5">
                                            <div className="flex items-center gap-2 mb-3">
                                                <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">第 {round} 轮</span>
                                                <span className="text-xs text-slate-400">{round === 1 ? '独立评审' : '交叉辩论'}</span>
                                            </div>
                                            <div className="space-y-3">
                                                {roundEntries.map((entry: any, i: number) => {
                                                    const stanceBg = entry.stance === 'challenge' ? 'border-l-red-400' : entry.stance === 'support' ? 'border-l-blue-400' : entry.stance === 'methodology' ? 'border-l-orange-400' : 'border-l-lime-400';
                                                    return (
                                                        <div key={i} className={`bg-white border border-slate-200 rounded-lg p-4 border-l-4 ${stanceBg}`}>
                                                            <div className="flex items-center gap-2 mb-2">
                                                                <PersonaBadge persona={entry.expert_name || entry.stance} />
                                                                {typeof entry.score === 'number' && (
                                                                    <OverallBadge score={entry.score} />
                                                                )}
                                                            </div>
                                                            <p className="text-sm text-slate-700">{entry.argument || entry.comment}</p>
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}

                        {/* 排版注释 */}
                        {layoutNotes && (
                            <div className="p-4 bg-teal-50/50 border border-teal-100 rounded-xl">
                                <div className="text-xs font-bold text-teal-700 mb-2 flex items-center gap-1">排版优化报告</div>
                                <div className="prose prose-sm max-w-none prose-slate text-xs">
                                    <ReactMarkdown>{typeof layoutNotes === 'string' ? layoutNotes : JSON.stringify(layoutNotes, null, 2)}</ReactMarkdown>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* ========== TAB 5 (原 3): 完整预览 + TOC ========== */}
                {activeTab === 'preview' && (
                    <div className="flex gap-5">
                        {/* TOC Sidebar */}
                        {tocItems.length > 0 && (
                            <div className="w-48 shrink-0 sticky top-0 self-start">
                                <div className="text-xs font-bold text-slate-500 mb-2 uppercase tracking-wider">大纲导航</div>
                                <nav className="space-y-0.5 border-l-2 border-slate-200 pl-3">
                                    {tocItems.map((item, i) => (
                                        <a
                                            key={i}
                                            href={`#toc-${item.section}`}
                                            onClick={(e) => {
                                                e.preventDefault();
                                                document.getElementById(`toc-${item.section}`)?.scrollIntoView({ behavior: 'smooth' });
                                            }}
                                            className={`block text-xs truncate hover:text-blue-600 transition-colors ${item.level === 1 ? 'font-semibold text-slate-700 py-1' : 'text-slate-500 pl-3 py-0.5'}`}
                                        >
                                            {item.heading}
                                        </a>
                                    ))}
                                </nav>
                            </div>
                        )}

                        {/* Main content */}
                        <div className="flex-1 min-w-0">
                            {Object.keys(drafts).length === 0 ? (
                                <div className="text-slate-400 text-center py-16 text-sm">尚无任何章节内容被生成。</div>
                            ) : (
                                <>
                                    <div className="mb-5 p-2.5 bg-blue-50 border border-blue-200 rounded-lg flex items-center gap-4 text-xs text-blue-800">
                                        <span>已生成 <strong>{Object.keys(drafts).filter(k => k !== '参考文献').length}</strong> / {ALL_SECTIONS.length} 章节</span>
                                        <span>·</span>
                                        <span>评审 <strong>{feedbackCount}</strong> 条</span>
                                        <span>·</span>
                                        <span>字数 <strong>{Object.values(drafts).join('').length.toLocaleString()}</strong></span>
                                    </div>
                                    <div className="prose prose-slate max-w-none prose-sm">
                                        {ALL_SECTIONS.map(s => {
                                            if (!drafts[s]) return null;
                                            return (
                                                <div key={s} id={`toc-${s}`} className="mb-8 pb-6 border-b border-slate-200 last:border-0">
                                                    <h2 className="text-lg font-bold text-slate-800 border-l-4 border-blue-600 pl-3 mb-3 not-prose">{s}</h2>
                                                    <ReactMarkdown>{drafts[s]}</ReactMarkdown>
                                                </div>
                                            );
                                        })}
                                        {drafts['参考文献'] && (
                                            <div id="toc-参考文献" className="mb-8 pb-6">
                                                <h2 className="text-lg font-bold text-slate-800 border-l-4 border-teal-500 pl-3 mb-3 not-prose">参考文献</h2>
                                                <pre className="text-xs text-slate-700 whitespace-pre-wrap bg-slate-50 p-3 rounded-lg border">{drafts['参考文献']}</pre>
                                            </div>
                                        )}
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                )}

                {/* ========== TAB 6 (原 4): 版本历史 ========== */}
                {activeTab === 'history' && (
                    <div>
                        {draftHistory.length === 0 ? (
                            <div className="text-slate-400 text-center py-16 text-sm">暂无历史版本。每次启动工作流或手动编辑草稿时，系统会自动保存快照。</div>
                        ) : (
                            <div className="space-y-3">
                                {[...draftHistory].reverse().map((snap, i) => (
                                    <div key={i} className="bg-white border border-slate-200 rounded-lg p-4 flex items-center justify-between hover:border-blue-300 transition-colors">
                                        <div className="flex items-center gap-3">
                                            <div className="w-8 h-8 rounded-full bg-slate-100 flex items-center justify-center text-slate-500">
                                                <Clock size={14} />
                                            </div>
                                            <div>
                                                <div className="text-sm font-medium text-slate-700">{snap.label}</div>
                                                <div className="text-xs text-slate-400">{snap.timestamp} · {Object.keys(snap.drafts).length} 个章节 · {Object.values(snap.drafts).join('').length} 字</div>
                                            </div>
                                        </div>
                                        <button
                                            onClick={() => onRestoreSnapshot(snap)}
                                            className="flex items-center gap-1 px-3 py-1.5 bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-semibold rounded-lg border border-blue-200 transition-colors"
                                        >
                                            <RotateCcw size={12} /> 回退到此版本
                                        </button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
