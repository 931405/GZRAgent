import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import { FolderSearch, Play, BookOpen, Upload, ChevronLeft, ChevronRight, Settings } from 'lucide-react';

export const ALL_SECTIONS = ["立项依据", "研究目标与内容", "研究方案与可行性", "特色与创新", "研究基础"];
const PROVIDERS = ["deepseek", "moonshot", "doubao", "custom"];
const MODEL_LABELS: Record<string, string> = {
    decision: '决策规划',
    searcher: '文献检索',
    innovation: '创新点',
    writer: '撰写',
    reviewer: '评审',
    layout: '排版',
};
const PROJECT_TYPES = ["面上项目", "青年科学基金", "重点项目", "杰青/优青"];

const PRESET_TOPICS: Record<string, { topic: string; hint: string }> = {
    "自定义": { topic: "", hint: "" },
    "生命科学·分子机制": { topic: "基于AI的蛋白质互作网络动态调控机制研究", hint: "侧重分子机制探索与实验验证设计" },
    "信息科学·算法创新": { topic: "大语言模型多智能体协作机制研究", hint: "侧重算法设计与性能对比验证" },
    "化学·药物合成": { topic: "核苷类抗病毒药物的绿色合成新策略研究", hint: "侧重合成路线与选择性优化" },
    "工程·智能制造": { topic: "数字孪生驱动的智能车间自适应调度优化", hint: "侧重系统建模与工程验证" },
};

interface SidebarProps {
    onStartWorkflow: (req: any) => void;
    isRunning: boolean;
    onLoadHistory: (data: any) => void;
    isCollapsed: boolean;
    setIsCollapsed: (collapsed: boolean) => void;
}


export function Sidebar({ onStartWorkflow, isRunning, onLoadHistory, isCollapsed, setIsCollapsed }: SidebarProps) {
    const [projectType, setProjectType] = useState("面上项目");
    const [researchTopic, setResearchTopic] = useState("大语言模型多智能体协作机制研究");
    const [currentFocus, setCurrentFocus] = useState("立项依据");
    const [maxIterations, setMaxIterations] = useState(2);
    const [models, setModels] = useState({
        decision: "deepseek", searcher: "deepseek", innovation: "deepseek",
        writer: "deepseek", reviewer: "deepseek", layout: "deepseek",
    });

    const [templates, setTemplates] = useState<string[]>([]);
    const [selectedTemplate, setSelectedTemplate] = useState("不使用模板");
    const [templateContent, setTemplateContent] = useState<any>(null);

    const [kbStats, setKbStats] = useState({ total_files: 0, file_names: [] });
    const [folderPath, setFolderPath] = useState("");
    const [historyFiles, setHistoryFiles] = useState<string[]>([]);
    const [selectedHistory, setSelectedHistory] = useState("");

    const [scanProgress, setScanProgress] = useState<{ current: number; total: number; filename: string } | null>(null);
    const [isScanning, setIsScanning] = useState(false);
    const [isUploadingTemplate, setIsUploadingTemplate] = useState(false);
    const templateFileRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        api.getTemplateList().then(setTemplates);
        api.getKbStats().then(setKbStats);
        api.getHistoryList().then(list => {
            setHistoryFiles(list);
            if (list.length > 0) setSelectedHistory(list[0]);
        });
    }, []);

    useEffect(() => {
        if (selectedTemplate !== "不使用模板") {
            api.getTemplate(selectedTemplate).then(setTemplateContent);
        } else {
            setTemplateContent(null);
        }
    }, [selectedTemplate]);

    const handleStart = (mode: "single" | "all") => {
        let hint = "";
        if (templateContent && templateContent.sections) {
            hint = templateContent.sections[currentFocus] || "";
        }
        onStartWorkflow({
            project_type: projectType,
            research_topic: researchTopic,
            current_focus: currentFocus,
            max_iterations: maxIterations,
            model_config: models,
            template_hint: hint,
            mode
        });
    };

    const scanFolder = async () => {
        if (!folderPath || isScanning) return;
        setIsScanning(true);
        setScanProgress(null);

        try {
            const response = await fetch('http://localhost:8000/api/knowledge/scan_stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_path: folderPath }),
            });

            const reader = response.body?.getReader();
            const decoder = new TextDecoder();

            if (!reader) {
                // fallback to old sync API
                await api.scanFolder(folderPath);
                const stats = await api.getKbStats();
                setKbStats(stats);
                setIsScanning(false);
                return;
            }

            let buffer = '';
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });

                const lines = buffer.split('\n\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue;
                    try {
                        const data = JSON.parse(line.slice(6));
                        if (data.type === 'progress') {
                            setScanProgress({ current: data.current, total: data.total, filename: data.filename });
                        } else if (data.type === 'done') {
                            setScanProgress(null);
                            const stats = await api.getKbStats();
                            setKbStats(stats);
                        } else if (data.type === 'error') {
                            alert(data.message);
                        }
                    } catch { }
                }
            }
        } catch {
            alert("扫描失败");
        }
        setIsScanning(false);
    };

    const loadHistory = async () => {
        if (!selectedHistory) return;
        try {
            const data = await api.loadHistory(selectedHistory);
            onLoadHistory(data);
        } catch (e) {
            alert("加载历史记录失败");
        }
    };

    const handleTemplateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        setIsUploadingTemplate(true);
        try {
            const result = await api.uploadTemplateFile(file);
            setTemplates(result.templates);
            setSelectedTemplate(result.name);
            const hint = result.detected_sections.length > 0
                ? `检测到章节: ${result.detected_sections.join('、')}`
                : '未检测到标准章节，模板内容已保存';
            alert(`模板「${result.name}」上传成功！${hint}`);
        } catch (err: any) {
            alert(`上传失败: ${err.message}`);
        } finally {
            setIsUploadingTemplate(false);
            if (templateFileRef.current) templateFileRef.current.value = '';
        }
    };

    const canStart = researchTopic.trim().length > 0 && !isRunning;

    if (isCollapsed) {
        return (
            <div className="w-12 bg-white border-r border-blue-100 h-screen flex flex-col items-center py-4 transition-all duration-300">
                <button
                    onClick={() => setIsCollapsed(false)}
                    className="p-1.5 text-blue-500 hover:bg-blue-50 hover:text-blue-700 rounded-md transition-colors"
                    title="展开配置"
                >
                    <Settings size={20} />
                </button>
            </div>
        );
    }

    return (
        <div className="w-80 bg-white border-r border-blue-100 h-screen flex flex-col text-sm transition-all duration-300 relative">
            <button
                onClick={() => setIsCollapsed(true)}
                className="absolute -right-3 top-6 bg-white border border-blue-200 text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded-md p-0.5 z-10 shadow-sm"
            >
                <ChevronLeft size={16} />
            </button>

            <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6 scrollbar-thin scrollbar-thumb-blue-100 scrollbar-track-transparent">
                {/* Project Settings */}
                <section className="flex flex-col gap-3">
                    <h3 className="font-semibold text-blue-900 tracking-wide text-[13px] uppercase">项目设置</h3>
                    <select value={projectType} onChange={e => setProjectType(e.target.value)} className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md focus:border-blue-400 focus:outline-none transition-colors">
                        {PROJECT_TYPES.map(p => <option key={p} value={p}>{p}</option>)}
                    </select>

                    {/* Preset quick-fill */}
                    <div>
                        <label className="text-xs text-slate-500 mb-1 block">快速预设 (选择学部模板)</label>
                        <select
                            onChange={e => {
                                const preset = PRESET_TOPICS[e.target.value];
                                if (preset && preset.topic) {
                                    setResearchTopic(preset.topic);
                                }
                            }}
                            className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md w-full text-xs focus:border-blue-400 focus:outline-none transition-colors"
                            defaultValue="自定义"
                        >
                            {Object.keys(PRESET_TOPICS).map(k => <option key={k} value={k}>{k}</option>)}
                        </select>
                    </div>

                    <textarea
                        value={researchTopic} onChange={e => setResearchTopic(e.target.value)}
                        className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md h-20 placeholder:text-blue-300 focus:border-blue-400 focus:outline-none transition-colors"
                        placeholder="研究主题"
                    />
                    <select value={currentFocus} onChange={e => setCurrentFocus(e.target.value)} className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md focus:border-blue-400 focus:outline-none transition-colors">
                        {ALL_SECTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                    </select>
                    <div className="flex justify-between items-center bg-[#f8fbff] p-2 border border-blue-100 rounded-md">
                        <div className="flex items-center gap-1">
                            <span className="text-slate-600 text-xs font-medium">迭代轮次</span>
                        </div>
                        <input type="number" min={1} max={5} value={maxIterations} onChange={e => setMaxIterations(Number(e.target.value))} className="w-12 p-1 border border-blue-200 rounded-md text-center bg-white focus:border-blue-400 focus:outline-none" />
                    </div>
                </section>

                <hr className="border-blue-100" />

                {/* Templates */}
                <section className="flex flex-col gap-3">
                    <h3 className="font-semibold text-blue-900 tracking-wide text-[13px] uppercase">写作模板</h3>
                    <select value={selectedTemplate} onChange={e => setSelectedTemplate(e.target.value)} className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md focus:border-blue-400 focus:outline-none transition-colors">
                        <option value="不使用模板">不使用模板</option>
                        {templates.map(t => <option key={t} value={t}>{t}</option>)}
                    </select>
                    {templateContent && (
                        <p className="text-xs text-blue-600 italic bg-blue-50 p-2 rounded-md border border-blue-100">{templateContent.description}</p>
                    )}
                    {/* 上传自定义模板 */}
                    <input
                        ref={templateFileRef}
                        type="file"
                        accept=".json,.docx,.doc,.txt,.md"
                        className="hidden"
                        onChange={handleTemplateUpload}
                    />
                    <button
                        onClick={() => templateFileRef.current?.click()}
                        disabled={isUploadingTemplate}
                        className="flex items-center justify-center gap-1.5 w-full py-2 border border-dashed border-blue-300 bg-[#f8fbff] rounded-md text-xs text-blue-600 hover:text-blue-800 hover:border-blue-400 hover:bg-blue-50 transition-colors disabled:opacity-50"
                        title="支持 .json / .docx / .txt 格式"
                    >
                        <Upload size={14} />
                        {isUploadingTemplate ? '解析中...' : '上传新模板'}
                    </button>
                </section>

                <hr className="border-blue-100" />

                {/* Models */}
                <section className="flex flex-col gap-3">
                    <h3 className="font-semibold text-blue-900 tracking-wide text-[13px] uppercase">模型分配</h3>
                    {Object.values(models).includes("custom") && (
                        <div className="text-[10px] text-amber-700 bg-amber-50 p-2 rounded border border-amber-200">
                            <strong>⚠️ 提示：</strong> 选择了 custom 提供商，请确保后端 .env 已配置 CUSTOM_API_KEY。
                        </div>
                    )}
                    <div className="grid grid-cols-2 gap-2">
                        {Object.keys(models).map((key) => (
                            <div key={key}>
                                <div className="text-[10px] text-slate-500 mb-1">{MODEL_LABELS[key] || key}</div>
                                <select value={(models as any)[key]} onChange={e => setModels({ ...models, [key]: e.target.value })} className="w-full p-1.5 border border-blue-200 bg-[#f8fbff] rounded-md text-xs focus:border-blue-400 focus:outline-none transition-colors">
                                    {PROVIDERS.map(p => <option key={p} value={p}>{p}</option>)}
                                </select>
                            </div>
                        ))}
                    </div>
                </section>

                <hr className="border-blue-100" />

                {/* Knowledge Base */}
                <section className="flex flex-col gap-3">
                    <h3 className="font-semibold text-blue-900 tracking-wide text-[13px] uppercase">本地知识库</h3>
                    <div className="text-xs text-blue-700 bg-[#eef6ff] p-2 rounded-md border border-blue-200 font-medium text-center">
                        已收录 {kbStats.total_files} 份文档
                    </div>
                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="D:\论文目录"
                            value={folderPath}
                            onChange={e => setFolderPath(e.target.value)}
                            className="flex-1 p-2 border border-blue-200 bg-white rounded-md text-xs focus:border-blue-400 focus:outline-none transition-colors"
                            disabled={isScanning}
                        />
                        <button onClick={scanFolder} disabled={isScanning} className="p-2 bg-blue-100 hover:bg-blue-200 border border-blue-200 disabled:opacity-50 rounded-md text-blue-800 transition-colors" title="扫描文件夹"><FolderSearch size={16} /></button>
                    </div>
                    {scanProgress && (
                        <div className="flex flex-col gap-1">
                            <div className="flex justify-between text-[10px] text-slate-500">
                                <span>{scanProgress.current}/{scanProgress.total} 文件</span>
                                <span>{Math.round((scanProgress.current / scanProgress.total) * 100)}%</span>
                            </div>
                            <div className="w-full bg-slate-100 rounded-sm h-1">
                                <div
                                    className="bg-blue-500 h-1 rounded-sm transition-all duration-300"
                                    style={{ width: `${(scanProgress.current / scanProgress.total) * 100}%` }}
                                />
                            </div>
                            <div className="text-[10px] text-slate-400 truncate">{scanProgress.filename}</div>
                        </div>
                    )}
                    {isScanning && !scanProgress && (
                        <div className="text-xs text-blue-600 animate-pulse text-center">正在读取目录结构...</div>
                    )}
                </section>

                <hr className="border-blue-100" />

                {/* History */}
                <section className="flex flex-col gap-3 pb-4">
                    <h3 className="font-semibold text-blue-900 tracking-wide text-[13px] uppercase">历史记录</h3>
                    <select value={selectedHistory} onChange={e => setSelectedHistory(e.target.value)} className="p-2 border border-blue-200 bg-[#f8fbff] rounded-md text-xs focus:border-blue-400 focus:outline-none transition-colors">
                        <option value="" disabled>选择快照...</option>
                        {historyFiles.map(h => <option key={h} value={h}>{h}</option>)}
                    </select>
                    <button onClick={loadHistory} disabled={!selectedHistory || isRunning} className="w-full p-2 border border-blue-200 hover:bg-blue-50 text-blue-700 rounded-md text-xs font-medium transition-colors disabled:opacity-50">
                        还原记录
                    </button>
                </section>
            </div>
            {/* Action Buttons */}
            <div className="shrink-0 border-t border-blue-100 bg-white p-4 flex flex-col gap-2 relative z-10">
                {!researchTopic.trim() && (
                    <div className="text-xs text-amber-600 font-medium text-center pb-1">要求填写研究主题</div>
                )}
                <button
                    onClick={() => handleStart("single")}
                    disabled={!canStart}
                    className="flex items-center justify-center gap-2 w-full p-2.5 bg-[#f0f7ff] border border-blue-300 hover:bg-blue-100 disabled:opacity-50 disabled:cursor-not-allowed text-blue-700 rounded-md font-medium transition-colors"
                >
                    <Play size={14} /> 局部: 「{currentFocus}」
                </button>
                <button
                    onClick={() => {
                        handleStart("all");
                        setIsCollapsed(true);
                    }}
                    disabled={!canStart}
                    className="flex items-center justify-center gap-2 w-full p-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-md font-medium transition-colors shadow-sm"
                >
                    <BookOpen size={16} /> 从头推演全文
                </button>
            </div>
        </div>
    );
}
