"use client"

import React, { useCallback } from 'react';
import ReactFlow, {
    Node,
    Edge,
    Background,
    Controls,
    MiniMap,
    useNodesState,
    useEdgesState
} from 'reactflow';
import { useAppStore } from '@/store/appStore';
import { useTranslation } from '@/store/i18nStore';

// Initial agent topology for PD-MAWS L4 ANP
const initialNodes: Node[] = [
    { id: 'pi', position: { x: 400, y: 50 }, data: { label: 'PI Agent (Orchestrator)' }, type: 'input' },
    { id: 'writer', position: { x: 200, y: 150 }, data: { label: 'Writer 01' } },
    { id: 'researcher', position: { x: 600, y: 150 }, data: { label: 'Researcher' } },
    { id: 'diagram', position: { x: 200, y: 250 }, data: { label: 'Diagram Agent' } },
    { id: 'reviewer', position: { x: 400, y: 350 }, data: { label: 'Red Team Reviewer' }, type: 'output' },
];

const initialEdges: Edge[] = [
    { id: 'e-pi-writer', source: 'pi', target: 'writer', animated: true, label: 'Task' },
    { id: 'e-pi-research', source: 'pi', target: 'researcher', animated: true, label: 'Task' },
    { id: 'e-writer-diagram', source: 'writer', target: 'diagram', animated: true, label: 'Request' },
    { id: 'e-writer-reviewer', source: 'writer', target: 'reviewer', animated: true, label: 'Draft' },
    { id: 'e-research-reviewer', source: 'researcher', target: 'reviewer', animated: true, label: 'Evidence' },
];

export function AgentTopology() {
    const t = useTranslation();
    const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
    const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

    // Syncing Zustand state colors to ReactFlow nodes
    const agents = useAppStore(state => state.agents);

    // Update node styles based on agent activity
    const activeNodes = nodes.map((node) => {
        const status = agents[node.id]?.status || 'IDLE';
        const isActive = status !== 'IDLE' && status !== 'DONE';
        const isError = status === 'ERROR' || status === 'INTERRUPTED';

        return {
            ...node,
            style: {
                background: isError ? '#fee2e2' : isActive ? '#dcfce7' : '#f8fafc',
                border: `2px solid \${isError ? '#ef4444' : isActive ? '#22c55e' : '#cbd5e1'}`,
                color: isError ? '#991b1b' : isActive ? '#166534' : '#334155',
                fontWeight: isActive ? 'bold' : 'normal',
                borderRadius: '8px',
                padding: '10px',
                width: 150,
            }
        };
    });

    return (
        <div className="w-full h-full min-h-[400px] border rounded-lg bg-card/30 overflow-hidden relative">
            <div className="absolute top-3 left-3 z-10 text-xs font-semibold text-muted-foreground uppercase tracking-widest bg-background/80 px-2 rounded-sm border">
                {t('topology.badge')}
            </div>
            <ReactFlow
                nodes={activeNodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                fitView
                attributionPosition="bottom-right"
            >
                <Background gap={12} size={1} color="#cbd5e1" />
                <Controls showInteractive={false} />
            </ReactFlow>
        </div>
    );
}
