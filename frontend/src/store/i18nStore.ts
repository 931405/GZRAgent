import { create } from 'zustand';

export type Language = 'en' | 'zh';

interface Translations {
    [key: string]: {
        en: string;
        zh: string;
    };
}

export const t: Translations = {
    // Common
    'app.title': { en: 'PD-MAWS Studio', zh: 'PD-MAWS 协作工作台' },
    'app.session': { en: 'Session:', zh: '会话状态:' },
    'app.config': { en: 'Config', zh: '配置' },
    'app.mock': { en: 'Mock Workflow', zh: '模拟运行' },
    'app.simulating': { en: 'Simulating...', zh: '模拟中...' },
    'app.state': { en: 'STATE:', zh: '状态:' },
    'app.turn': { en: 'TURN:', zh: '轮次:' },

    // Connection status
    'connection.connected': { en: 'Connected', zh: '已连接' },
    'connection.disconnected': { en: 'Disconnected', zh: '未连接' },

    // Left Sidebar
    'sidebar.fleet': { en: 'Agent Fleet', zh: '智能体舰队' },
    'agent.status': { en: 'STATUS:', zh: '状态:' },

    // Agent names
    'agent.name.pi': { en: 'PI Agent', zh: 'PI 协调者' },
    'agent.name.writer': { en: 'Writer 01', zh: '学术写手' },
    'agent.name.researcher': { en: 'Researcher', zh: '文献研究员' },
    'agent.name.reviewer': { en: 'Red Team', zh: '红队审稿人' },

    // Agent status values
    'status.IDLE': { en: 'IDLE', zh: '空闲' },
    'status.PLAN': { en: 'PLAN', zh: '规划中' },
    'status.EXECUTE': { en: 'EXECUTE', zh: '执行中' },
    'status.VERIFY': { en: 'VERIFY', zh: '校验中' },
    'status.EMIT': { en: 'EMIT', zh: '输出中' },
    'status.WAIT': { en: 'WAIT', zh: '等待中' },
    'status.DONE': { en: 'DONE', zh: '已完成' },
    'status.ERROR': { en: 'ERROR', zh: '错误' },
    'status.INTERRUPTED': { en: 'INTERRUPTED', zh: '已中断' },

    // Roles
    'role.orchestrator': { en: 'Orchestrator', zh: '编排与规划' },
    'role.academicwriter': { en: 'Academic Writer', zh: '学术主笔' },
    'role.writer': { en: 'Academic Writer', zh: '学术主笔' },
    'role.literature': { en: 'Literature', zh: '文献检索' },
    'role.reviewer': { en: 'Reviewer', zh: '红蓝对抗评审' },

    // Center Pane Tabs
    'tab.blackboard': { en: 'Blackboard', zh: '黑板区 (文档)' },
    'tab.topology': { en: 'Topology', zh: '拓扑图 (L4)' },
    'plane.data': { en: 'L4 Data Plane', zh: 'L4 数据面' },

    // Topology View
    'topology.badge': { en: 'Static L4 Topography', zh: 'L4 静态拓扑图' },

    // Right Pane
    'pane.telemetry': { en: 'A2A Telemetry Stream', zh: 'A2A 遥测事件流' },
    'plane.control': { en: 'L3 Control Plane', zh: 'L3 控制面' },
    'stream.waiting': { en: 'Waiting for A2A telemetry events...', zh: '等待 A2A 遥测事件到达...' },

    // Editor
    'editor.placeholder': { en: 'Drafting will appear here once agents begin...', zh: '等待智能体开始撰写草稿...' },

    // Empty state
    'empty.title': { en: 'Ready to Start', zh: '准备就绪' },
    'empty.desc': { en: 'Click the Config button above to create a writing session and start the multi-agent collaborative workflow.', zh: '点击上方「配置」按钮，创建写作会话并启动多智能体协作流程。' },

    // Tooltips
    'tooltip.theme': { en: 'Toggle Light/Dark', zh: '切换明暗模式' },
    'tooltip.llm': { en: 'LLM Settings', zh: '大模型设置' },
    'tooltip.settings': { en: 'Connection Settings', zh: '连接设置' },
    'tooltip.lang': { en: 'Switch Language', zh: '切换语言' },

    // Config Dialog
    'dialog.title': { en: 'Configure Writing Session', zh: '初始化写作会话' },
    'dialog.desc': { en: 'Provide the topic and initial outline to kick off the multi-agent workflow.', zh: '提供研究主题和初步大纲以启动多智能体协作流。' },
    'dialog.topic': { en: 'Research Topic', zh: '研究主题' },
    'dialog.topic.placeholder': { en: 'e.g. Optimization of LLM inference latency', zh: '例如：大模型推理延迟优化研究' },
    'dialog.outline': { en: 'Draft Outline', zh: '基础大纲' },
    'dialog.cancel': { en: 'Cancel', zh: '取消' },
    'dialog.start': { en: 'Initialize Session', zh: '启动会话' },
};

interface I18nState {
    lang: Language;
    toggleLang: () => void;
    setLang: (lang: Language) => void;
}

export const useI18nStore = create<I18nState>((set) => ({
    lang: 'zh', // Default to Chinese as requested
    toggleLang: () => set((state) => ({ lang: state.lang === 'en' ? 'zh' : 'en' })),
    setLang: (lang) => set({ lang }),
}));

export function useTranslation() {
    const lang = useI18nStore((state) => state.lang);

    return (key: keyof typeof t) => {
        return t[key]?.[lang] || key;
    };
}
