"use client"

import { useEffect, useRef } from 'react'
import { useAppStore, StreamEvent } from '@/store/appStore'
import { format } from 'date-fns'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge } from '@/components/ui/badge'
import { useTranslation } from '@/store/i18nStore'

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
    const isError = log.intent === 'ERROR' || log.intent === 'NACK_FATAL'
    const isTask = log.intent === 'REQUEST_TASK' || log.intent === 'TASK_ASSIGNED'

    return (
        <div className={`p-3 rounded-md border text-sm flex flex-col gap-2 
      \${isError ? 'bg-destructive/10 border-destructive/20' : 'bg-background hover:bg-muted/50 transition-colors'}`}>

            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5 flex-wrap">
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

            <div className={`prose prose-sm dark:prose-invert prose-p:leading-snug prose-p:my-0 prose-pre:bg-muted prose-pre:p-2 text-muted-foreground \${isError ? 'text-destructive-foreground' : ''}`}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {log.message}
                </ReactMarkdown>
            </div>
        </div>
    )
}
