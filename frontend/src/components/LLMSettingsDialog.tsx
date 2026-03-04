"use client"

import { useState, useEffect } from "react"
import { Bot, Key, Save, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { useSettingsStore } from "@/store/settingsStore"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface ProviderConfig {
    api_key: string
    base_url: string
    default_model: string
}

interface AgentAssignment {
    provider: string
    model: string
}

interface LLMSettings {
    providers: Record<string, ProviderConfig>
    agents: Record<string, AgentAssignment>
}

const PROVIDER_INFO: Record<string, { label: string; hasKey: boolean; hasUrl: boolean; placeholder: string }> = {
    openai: { label: "OpenAI", hasKey: true, hasUrl: true, placeholder: "sk-..." },
    deepseek: { label: "DeepSeek", hasKey: true, hasUrl: true, placeholder: "sk-..." },
    gemini: { label: "Google Gemini", hasKey: true, hasUrl: false, placeholder: "AIza..." },
    ollama: { label: "Ollama (本地)", hasKey: false, hasUrl: true, placeholder: "" },
    custom: { label: "自定义", hasKey: true, hasUrl: true, placeholder: "your-api-key" },
}

const AGENT_LABELS: Record<string, string> = {
    pi: "🧠 PI 协调者",
    writer: "✍️ 学术写手",
    researcher: "🔍 文献研究员",
    red_team: "🛡️ 红队审稿人",
    diagram: "📊 图表引擎",
    format: "📄 格式化引擎",
    data_analyst: "📈 数据分析师",
}

export function LLMSettingsDialog() {
    const [open, setOpen] = useState(false)
    const [loading, setLoading] = useState(false)
    const [saving, setSaving] = useState(false)
    const [settings, setSettings] = useState<LLMSettings | null>(null)
    const getApiBase = useSettingsStore(state => state.getApiBase)

    const fetchSettings = async () => {
        setLoading(true)
        try {
            const res = await fetch(`${getApiBase()}/api/settings/llm`)
            if (res.ok) {
                const data = await res.json()
                setSettings(data)
            }
        } catch (e) {
            console.error("Failed to fetch LLM settings", e)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        if (open) fetchSettings()
    }, [open])

    const updateProvider = (name: string, field: keyof ProviderConfig, value: string) => {
        if (!settings) return
        setSettings({
            ...settings,
            providers: {
                ...settings.providers,
                [name]: { ...settings.providers[name], [field]: value }
            }
        })
    }

    const updateAgent = (name: string, field: keyof AgentAssignment, value: string) => {
        if (!settings) return
        setSettings({
            ...settings,
            agents: {
                ...settings.agents,
                [name]: { ...settings.agents[name], [field]: value }
            }
        })
    }

    const handleSave = async () => {
        if (!settings) return
        setSaving(true)
        try {
            const res = await fetch(`${getApiBase()}/api/settings/llm`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            })
            if (res.ok) {
                const data = await res.json()
                toast.success(`保存成功！更新了 ${data.updated_fields?.length || 0} 个字段`)
                setOpen(false)
            } else {
                toast.error("保存失败")
            }
        } catch (e) {
            console.error("Failed to save LLM settings", e)
            toast.error("保存失败，无法连接后端")
        } finally {
            setSaving(false)
        }
    }

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="大模型设置">
                    <Bot size={14} />
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[600px] max-h-[80vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>🤖 大模型配置</DialogTitle>
                    <DialogDescription>
                        配置 LLM API 密钥、模型，以及每个 Agent 使用的供应商
                    </DialogDescription>
                </DialogHeader>

                {loading ? (
                    <div className="flex items-center justify-center py-8 text-muted-foreground">
                        <RefreshCw size={16} className="animate-spin mr-2" />
                        加载中...
                    </div>
                ) : settings ? (
                    <Tabs defaultValue="providers" className="w-full">
                        <TabsList className="grid w-full grid-cols-2">
                            <TabsTrigger value="providers">
                                <Key size={14} className="mr-1" /> 供应商配置
                            </TabsTrigger>
                            <TabsTrigger value="agents">
                                <Bot size={14} className="mr-1" /> Agent 分配
                            </TabsTrigger>
                        </TabsList>

                        <TabsContent value="providers" className="space-y-4 mt-4">
                            {Object.entries(PROVIDER_INFO).map(([name, info]) => {
                                const provider = settings.providers[name]
                                if (!provider) return null
                                return (
                                    <div key={name} className="rounded-lg border p-3 space-y-2">
                                        <h4 className="text-sm font-semibold">{info.label}</h4>
                                        {info.hasKey && (
                                            <div className="grid gap-1">
                                                <label className="text-xs text-muted-foreground">API Key</label>
                                                <Input
                                                    type="password"
                                                    value={provider.api_key}
                                                    onChange={(e) => updateProvider(name, "api_key", e.target.value)}
                                                    placeholder={info.placeholder}
                                                    className="h-8 text-sm font-mono"
                                                />
                                            </div>
                                        )}
                                        {info.hasUrl && (
                                            <div className="grid gap-1">
                                                <label className="text-xs text-muted-foreground">Base URL</label>
                                                <Input
                                                    value={provider.base_url}
                                                    onChange={(e) => updateProvider(name, "base_url", e.target.value)}
                                                    placeholder="https://api.example.com/v1"
                                                    className="h-8 text-sm font-mono"
                                                />
                                            </div>
                                        )}
                                        <div className="grid gap-1">
                                            <label className="text-xs text-muted-foreground">默认模型</label>
                                            <Input
                                                value={provider.default_model}
                                                onChange={(e) => updateProvider(name, "default_model", e.target.value)}
                                                placeholder="model-name"
                                                className="h-8 text-sm font-mono"
                                            />
                                        </div>
                                    </div>
                                )
                            })}
                        </TabsContent>

                        <TabsContent value="agents" className="space-y-3 mt-4">
                            <p className="text-xs text-muted-foreground">
                                为每个 Agent 指定使用的 LLM 供应商和模型（留空则使用供应商的默认模型）
                            </p>
                            {Object.entries(settings.agents).map(([name, assignment]) => (
                                <div key={name} className="rounded-lg border p-3 flex items-center gap-3">
                                    <span className="text-sm font-medium min-w-[120px]">
                                        {AGENT_LABELS[name] || name}
                                    </span>
                                    <select
                                        value={assignment.provider}
                                        onChange={(e) => updateAgent(name, "provider", e.target.value)}
                                        className="flex h-8 rounded-md border border-input bg-background px-2 py-1 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                    >
                                        {Object.entries(PROVIDER_INFO).map(([pName, pInfo]) => (
                                            <option key={pName} value={pName}>{pInfo.label}</option>
                                        ))}
                                    </select>
                                    <Input
                                        value={assignment.model}
                                        onChange={(e) => updateAgent(name, "model", e.target.value)}
                                        placeholder="使用默认模型"
                                        className="h-8 text-sm font-mono flex-1"
                                    />
                                </div>
                            ))}
                        </TabsContent>
                    </Tabs>
                ) : (
                    <div className="text-center py-8 text-muted-foreground">
                        无法加载设置，请检查后端连接
                    </div>
                )}

                <DialogFooter>
                    <Button variant="outline" onClick={() => setOpen(false)}>
                        取消
                    </Button>
                    <Button onClick={handleSave} disabled={saving || !settings} className="gap-2">
                        <Save size={14} />
                        {saving ? "保存中..." : "保存配置"}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
