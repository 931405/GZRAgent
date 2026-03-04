"use client"

import { useState, useEffect } from "react"
import { History, Clock, ChevronRight, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import { useSettingsStore } from "@/store/settingsStore"
import { useAppStore } from "@/store/appStore"
import { toast } from "sonner"

interface SessionSummary {
    session_id: string
    state: string
    turn_counter: number
}

export function SessionHistory() {
    const [sessions, setSessions] = useState<SessionSummary[]>([])
    const [loading, setLoading] = useState(false)
    const getApiBase = useSettingsStore(state => state.getApiBase)
    const currentSessionId = useAppStore(state => state.sessionId)
    const setSession = useAppStore(state => state.setSession)

    const fetchSessions = async () => {
        setLoading(true)
        try {
            const res = await fetch(`${getApiBase()}/api/sessions`)
            if (res.ok) {
                const ids: string[] = await res.json()
                // Fetch details for each (up to 10 most recent)
                const details: SessionSummary[] = []
                for (const id of ids.slice(-10).reverse()) {
                    try {
                        const r = await fetch(`${getApiBase()}/api/sessions/${id}`)
                        if (r.ok) {
                            const d = await r.json()
                            details.push({
                                session_id: d.session_id,
                                state: d.state,
                                turn_counter: d.turn_counter,
                            })
                        }
                    } catch { /* skip */ }
                }
                setSessions(details)
            }
        } catch (e) {
            console.error("Failed to fetch sessions", e)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchSessions()
    }, [])

    const stateColors: Record<string, string> = {
        INIT: 'text-blue-400',
        RUNNING: 'text-emerald-500',
        COMPLETED: 'text-green-500',
        FAILED: 'text-red-500',
        PAUSED: 'text-yellow-500',
        HALTED: 'text-orange-500',
    }

    return (
        <div className="flex flex-col">
            <div className="px-4 py-2 flex items-center justify-between">
                <span className="text-xs text-muted-foreground uppercase tracking-wider font-semibold flex items-center gap-1.5">
                    <History size={12} />
                    历史会话
                </span>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={fetchSessions} title="刷新">
                    <Clock size={12} />
                </Button>
            </div>
            <div className="px-3 space-y-1 max-h-[200px] overflow-y-auto">
                {loading ? (
                    <div className="text-xs text-muted-foreground text-center py-2">加载中...</div>
                ) : sessions.length === 0 ? (
                    <div className="text-xs text-muted-foreground text-center py-2">暂无历史会话</div>
                ) : (
                    sessions.map(s => (
                        <button
                            key={s.session_id}
                            onClick={() => {
                                setSession(s.session_id, s.state as any)
                                toast.info(`已切换到会话 ${s.session_id.slice(0, 12)}...`)
                            }}
                            className={`w-full text-left px-2.5 py-2 rounded-md text-xs flex items-center justify-between gap-2 transition-colors
                                ${currentSessionId === s.session_id
                                    ? 'bg-primary/10 border border-primary/20 text-foreground'
                                    : 'hover:bg-muted/50 text-muted-foreground border border-transparent'
                                }`}
                        >
                            <div className="flex flex-col min-w-0">
                                <span className="font-mono truncate">{s.session_id.slice(0, 16)}...</span>
                                <span className={`text-[10px] ${stateColors[s.state] || 'text-muted-foreground'}`}>
                                    {s.state} · Turn {s.turn_counter}
                                </span>
                            </div>
                            <ChevronRight size={12} className="shrink-0 text-muted-foreground" />
                        </button>
                    ))
                )}
            </div>
        </div>
    )
}
