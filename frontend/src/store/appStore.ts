import { create } from 'zustand';

export type AgentStatus = 'IDLE' | 'PLAN' | 'EXECUTE' | 'VERIFY' | 'EMIT' | 'WAIT' | 'DONE' | 'ERROR' | 'INTERRUPTED';
export type SessionState = 'INIT' | 'RUNNING' | 'PAUSED' | 'ARBITRATION' | 'COMPLETED' | 'HALTED' | 'FAILED';

export interface AgentInfo {
    id: string;
    name: string;
    role: string;
    status: AgentStatus;
}

export interface StreamEvent {
    id: string;
    timestamp: number;
    source: string;
    target?: string;
    intent: string;
    message: string;
}

interface AppState {
    sessionId: string | null;
    sessionState: SessionState;
    globalTurn: number;
    agents: Record<string, AgentInfo>;
    logs: StreamEvent[];
    documentContent: string;
    wsConnected: boolean;

    // Actions
    setSession: (id: string, state: SessionState) => void;
    updateAgentStatus: (id: string, status: AgentStatus) => void;
    addLog: (event: StreamEvent) => void;
    updateDocument: (content: string) => void;
    setWsConnected: (connected: boolean) => void;
    clearSession: () => void;
}

export const useAppStore = create<AppState>((set) => ({
    sessionId: null,
    sessionState: 'INIT',
    globalTurn: 0,
    agents: {
        pi: { id: 'pi', name: 'PI Agent', role: 'Orchestrator', status: 'IDLE' },
        writer: { id: 'writer', name: 'Writer 01', role: 'Academic Writer', status: 'IDLE' },
        researcher: { id: 'researcher', name: 'Researcher', role: 'Literature', status: 'IDLE' },
        reviewer: { id: 'reviewer', name: 'Red Team', role: 'Reviewer', status: 'IDLE' },
    },
    logs: [],
    documentContent: '',
    wsConnected: false,

    setSession: (id, state) => set({ sessionId: id, sessionState: state }),
    updateAgentStatus: (id, status) => set((state) => ({
        agents: {
            ...state.agents,
            [id]: { ...state.agents[id], status }
        }
    })),
    addLog: (event) => set((state) => ({ logs: [...state.logs, event] })),
    updateDocument: (content) => set({ documentContent: content }),
    setWsConnected: (connected) => set({ wsConnected: connected }),
    clearSession: () => set({ sessionId: null, sessionState: 'INIT', globalTurn: 0, logs: [], documentContent: '' }),
}));
