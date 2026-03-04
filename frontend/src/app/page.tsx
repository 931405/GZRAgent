"use client"

import React, { useEffect, useState } from "react";
import {
  FileText,
  Settings,
  MessageSquare,
  Play,
  Activity,
  BrainCircuit,
  Bot,
  SquareTerminal,
  ShieldAlert,
  Edit2
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useAppStore, AgentStatus, AgentInfo } from "@/store/appStore";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TiptapEditor } from "@/components/TiptapEditor";
import { AgentStream } from "@/components/AgentStream";
import { ConfigDialog } from "@/components/ConfigDialog";
import { SettingsDialog } from "@/components/SettingsDialog";
import { LLMSettingsDialog } from "@/components/LLMSettingsDialog";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useTranslation, useI18nStore } from "@/store/i18nStore";
import { generateId } from "@/lib/uuid";
import dynamic from "next/dynamic";

const AgentTopology = dynamic(() => import("@/components/AgentTopology").then(mod => mod.AgentTopology), {
  ssr: false,
  loading: () => <div className="h-full w-full flex items-center justify-center text-muted-foreground p-8">Loading Agent Map...</div>
});

// Helper map for converting agent roles to Lucide icons
const AgentRoleIcons: Record<string, React.ReactNode> = {
  "Orchestrator": <BrainCircuit size={16} />,
  "Academic Writer": <Edit2 size={16} />,
  "Literature": <SquareTerminal size={16} />,
  "Reviewer": <ShieldAlert size={16} />,
};

export default function StudioPage() {
  const t = useTranslation();
  const { lang, toggleLang } = useI18nStore();
  const { sessionState, agents, addLog, updateAgentStatus, setSession, globalTurn, updateDocument } = useAppStore();
  const [isSimulating, setIsSimulating] = useState(false);

  useWebSocket();

  // A tiny simulation function to test the UI without backend attached yet
  const runSimulationStep = () => {
    setIsSimulating(true);
    setSession("sess_mock_001", "RUNNING");

    // Simulate PI Agent Planning
    setTimeout(() => {
      updateAgentStatus("pi", "PLAN");
      addLog({
        id: generateId(), timestamp: Date.now(), source: "PI_Agent", target: "System",
        intent: "DECOMPOSE_TASK", message: "**Goal**: Draft 'Introduction' section.\n1. Literature search\n2. Compose draft\n3. Red Team Review"
      });
    }, 1000);

    // Simulate Writer & Researcher Interaction
    setTimeout(() => {
      updateAgentStatus("pi", "WAIT");
      updateAgentStatus("researcher", "EXECUTE");
      addLog({
        id: generateId(), timestamp: Date.now(), source: "PI_Agent", target: "Researcher",
        intent: "REQUEST_EVIDENCE", message: "Find papers on 'Transformer self-attention efficiency' from 2021-2023."
      });
    }, 3000);

    setTimeout(() => {
      updateAgentStatus("researcher", "IDLE");
      updateAgentStatus("writer", "EXECUTE");
      addLog({
        id: generateId(), timestamp: Date.now(), source: "Researcher", target: "Writer_01",
        intent: "PROVIDE_EVIDENCE", message: "Found 3 papers. Core claim: Sparse attention reduces bottleneck [doi:10.xxx/abc]."
      });
      updateDocument("<h2>1. Introduction</h2><p>Transformers have revolutionized sequential modeling, but self-attention efficiency remains a bottleneck.</p>");
    }, 6000);

    setTimeout(() => {
      updateAgentStatus("writer", "VERIFY");
      addLog({ id: generateId(), timestamp: Date.now(), source: "Writer_01", target: "Blackboard", intent: "PATCH_DRAFT", message: "Appended section 1 content." });
    }, 8000);

    setTimeout(() => {
      updateAgentStatus("writer", "IDLE");
      setIsSimulating(false);
    }, 9000);
  };

  return (
    <div className="flex h-screen w-full flex-col bg-background text-foreground overflow-hidden">
      {/* Top Header */}
      <header className="flex h-14 items-center justify-between border-b px-4 shrink-0 bg-card z-10">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground shadow-sm">
            <BrainCircuit size={18} />
          </div>
          <h1 className="text-lg font-semibold tracking-tight">{t('app.title')}</h1>
          <Separator orientation="vertical" className="h-6 mx-2 hidden sm:block" />
          <div className="hidden sm:flex items-center gap-2 text-xs font-mono text-muted-foreground bg-muted/50 px-2 py-1.5 rounded-md border border-border/50">
            <Activity size={14} className={sessionState === 'RUNNING' ? "text-emerald-500 animate-pulse" : "text-muted-foreground"} />
            <span>{t('app.state')} {sessionState}</span>
            <span className="opacity-50">|</span>
            <span>{t('app.turn')} {globalTurn}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LLMSettingsDialog />
          <SettingsDialog />
          <Button variant="ghost" size="sm" onClick={toggleLang} className="h-8 px-2 text-xs font-medium">
            {lang === 'en' ? '中' : 'En'}
          </Button>
          <ConfigDialog />
          <Button
            size="sm"
            className="gap-2 h-8"
            onClick={runSimulationStep}
            disabled={isSimulating}
          >
            <Play size={14} className={isSimulating ? "opacity-50" : ""} />
            {isSimulating ? t('app.simulating') : t('app.mock')}
          </Button>
        </div>
      </header>

      {/* Main Workspace */}
      <main className="flex flex-1 overflow-hidden relative">
        {/* Left Sidebar - Navigation / Agents Status */}
        <aside className="w-64 border-r bg-card/30 flex flex-col hidden lg:flex shrink-0">
          <div className="p-4 font-semibold text-xs text-muted-foreground uppercase tracking-wider flex items-center justify-between">
            <span>{t('sidebar.fleet')}</span>
            <span className="bg-primary/10 text-primary px-1.5 py-0.5 rounded text-[10px]">L2 ACP</span>
          </div>
          <div className="flex-1 overflow-y-auto px-3 space-y-2 pb-4">
            {Object.values(agents).map(agent => (
              <AgentItem key={agent.id} agent={agent} />
            ))}
          </div>
        </aside>

        {/* Center - Document Blackboard & Topology */}
        <section className="flex-1 flex flex-col border-r bg-background min-w-0">
          <Tabs defaultValue="blackboard" className="flex flex-col h-full w-full">
            <div className="h-10 border-b flex items-center justify-between px-4 font-medium text-sm bg-muted/10 shrink-0">
              <TabsList className="h-8 bg-transparent p-0 gap-4">
                <TabsTrigger value="blackboard" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 border-primary rounded-none px-2 h-full gap-2">
                  <FileText size={14} className="text-muted-foreground" />
                  {t('tab.blackboard')}
                </TabsTrigger>
                <TabsTrigger value="topology" className="data-[state=active]:bg-transparent data-[state=active]:shadow-none data-[state=active]:border-b-2 border-primary rounded-none px-2 h-full gap-2">
                  <BrainCircuit size={14} className="text-muted-foreground" />
                  {t('tab.topology')}
                </TabsTrigger>
              </TabsList>
              <div className="text-[10px] uppercase font-semibold tracking-wide bg-blue-500/10 text-blue-500 px-2 rounded-sm border border-blue-500/20">
                {t('plane.data')}
              </div>
            </div>

            <TabsContent value="blackboard" className="flex-1 overflow-hidden m-0 border-none outline-none">
              <TiptapEditor />
            </TabsContent>

            <TabsContent value="topology" className="flex-1 overflow-hidden m-0 p-4 border-none outline-none">
              <AgentTopology />
            </TabsContent>
          </Tabs>
        </section>

        {/* Right - Control Plane / Logs */}
        <section className="w-80 md:w-96 flex flex-col bg-card/20 shrink-0">
          <div className="h-10 border-b flex items-center justify-between px-4 font-medium text-sm bg-muted/10 shrink-0">
            <div className="flex items-center text-muted-foreground">
              <MessageSquare size={14} className="mr-2" />
              {t('pane.telemetry')}
            </div>
            <div className="text-[10px] uppercase font-semibold tracking-wide bg-amber-500/10 text-amber-500 px-2 rounded-sm border border-amber-500/20">
              {t('plane.control')}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
            {/* Real-time Status and Messages */}
            <AgentStream />
          </div>
        </section>
      </main>
    </div>
  );
}

function AgentItem({ agent }: { agent: AgentInfo }) {
  const t = useTranslation();
  const isActive = agent.status !== 'IDLE' && agent.status !== 'DONE';
  const icon = AgentRoleIcons[agent.role] || <Bot size={16} />;

  // Dynamic mapping since Zustand has static english defaults
  const nameKey = `agent.name.${agent.id}` as keyof typeof import('@/store/i18nStore').t;
  const roleKey = `role.${agent.role.toLowerCase().replace(' ', '')}` as keyof typeof import('@/store/i18nStore').t;

  return (
    <div className={`p-3 rounded-xl border flex flex-col gap-2.5 transition-all shadow-sm
      \${isActive ? 'bg-card border-primary/30 ring-1 ring-primary/10 shadow-primary/5' : 'bg-transparent border-border/60 hover:bg-card/50'}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`p-1.5 rounded-md \${isActive ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'}`}>
            {icon}
          </div>
          <div className="flex flex-col">
            <span className={`font-semibold text-sm \${isActive ? 'text-foreground' : 'text-foreground/80'}`}>
              {t(nameKey as any) || agent.name}
            </span>
            <span className="text-[10px] text-muted-foreground">{t(roleKey as any) || agent.role}</span>
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between bg-background/50 rounded p-1.5 border border-border/50">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-medium text-muted-foreground">{t('agent.status')}</span>
          <span className={`text-[10px] font-mono font-bold tracking-tight uppercase \${isActive ? 'text-primary' : 'text-muted-foreground'}`}>
            {agent.status}
          </span>
        </div>
        {isActive && (
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
        )}
      </div>
    </div>
  )
}
