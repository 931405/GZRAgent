"use client"

import { useEffect, useRef, useState } from 'react'
import { useAppStore, StreamEvent } from '@/store/appStore'
import { format } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/store/i18nStore'
import { ChevronDown, ChevronRight, Clock, Cpu, Zap } from 'lucide-react'

export function AgentStream() {
    const t = useTranslation()
    const logs = useAppStore(state => state.logs)
    const endRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: 'smooth' })
    }, [logs])

    if (logs.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-xs text-muted-foreground p-4 text-center">
                {t('stream.waiting')}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-3 pb-4">
            {logs.map((log) => (
                <LogItem key={log.id} log={log} />
            ))}
            <div ref={endRef} />
        </div>
    )
}

function LogItem({ log }: { log: StreamEvent }) {
    const [expanded, setExpanded] = useState(false)
    const isError = log.intent === 'ERROR' || log.intent === 'NACK_FATAL'
    const hasDetails = log.details && (log.details.prompt || log.details.result || log.details.tokens || log.details.duration_ms)

    return (
        <div
            className={`rounded-lg border text-sm flex flex-col transition-all 
            ${isError ? 'bg-destructive/10 border-destructive/20' : 'bg-background border-border/60 hover:border-border'}
            ${hasDetails ? 'cursor-pointer' : ''}`}
            onClick={() => hasDetails && setExpanded(!expanded)}
        >
            {/* Header */}
            <div className="p-3 flex flex-col gap-2">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 flex-wrap">
                        {hasDetails && (
                            <span className="text-muted-foreground shrink-0">
                                {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                            </span>
                        )}
                        <Badge variant={isError ? "destructive" : "secondary"} className="text-[10px] h-5 px-1.5 rounded-sm">
                            {log.intent}
                        </Badge>
                        <span className="font-semibold text-xs text-foreground/80">{log.source}</span>
                        {log.target && (
                            <>
                                <span className="text-muted-foreground/50 text-[10px]">→</span>
                                <span className="font-medium text-xs text-muted-foreground">{log.target}</span>
                            </>
                        )}
                    </div>
                    <span className="text-[10px] text-muted-foreground shrink-0 font-mono">
                        {format(log.timestamp, 'HH:mm:ss.SSS')}
                    </span>
                </div>

                <div className={`prose prose-sm dark:prose-invert prose-p:leading-snug prose-p:my-0 prose-pre:bg-muted prose-pre:p-2 text-muted-foreground ${isError ? 'text-destructive-foreground' : ''}`}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {log.message}
                    </ReactMarkdown>
                </div>

                {/* Meta chips (always shown if available) */}
                {log.details && (log.details.model || log.details.tokens || log.details.duration_ms) && (
                    <div className="flex items-center gap-2 flex-wrap">
                        {log.details.model && (
                            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground bg-muted/60 px-1.5 py-0.5 rounded">
                                <Cpu size={10} /> {log.details.model}
                            </span>
                        )}
                        {log.details.tokens !== undefined && log.details.tokens > 0 && (
                            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground bg-muted/60 px-1.5 py-0.5 rounded">
                                <Zap size={10} /> {log.details.tokens} tokens
                            </span>
                        )}
                        {log.details.duration_ms !== undefined && log.details.duration_ms > 0 && (
                            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground bg-muted/60 px-1.5 py-0.5 rounded">
                                <Clock size={10} /> {(log.details.duration_ms / 1000).toFixed(1)}s
                            </span>
                        )}
                    </div>
                )}
            </div>

            {/* Expandable details */}
            {expanded && log.details && (
                <div className="border-t border-border/50 p-3 bg-muted/20 space-y-3 text-xs" onClick={e => e.stopPropagation()}>
                    {log.details.prompt && (
                        <div>
                            <div className="font-semibold text-muted-foreground mb-1 uppercase tracking-wider text-[10px]">
                                📝 Prompt / 输入
                            </div>
                            <div className="bg-background border border-border/50 rounded-md p-2 max-h-48 overflow-y-auto custom-scrollbar">
                                <pre className="whitespace-pre-wrap text-[11px] text-foreground/70 font-mono leading-relaxed">
                                    {log.details.prompt}
                                </pre>
                            </div>
                        </div>
                    )}
                    {log.details.result && (
                        <div>
                            <div className="font-semibold text-muted-foreground mb-1 uppercase tracking-wider text-[10px]">
                                ✅ Result / 输出
                            </div>
                            <div className="bg-background border border-border/50 rounded-md p-2 max-h-64 overflow-y-auto custom-scrollbar prose prose-sm dark:prose-invert">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {log.details.result}
                                </ReactMarkdown>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
