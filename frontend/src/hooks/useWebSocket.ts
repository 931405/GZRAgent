"use client"

import { useEffect, useRef } from "react"
import { useAppStore, StreamEvent } from "@/store/appStore"
import { useSettingsStore } from "@/store/settingsStore"
import { generateId } from "@/lib/uuid"

export function useWebSocket() {
    const sessionId = useAppStore(state => state.sessionId)
    const addLog = useAppStore(state => state.addLog)
    const updateAgentStatus = useAppStore(state => state.updateAgentStatus)
    const wsRef = useRef<WebSocket | null>(null)

    useEffect(() => {
        if (!sessionId) return

        let reconnectCount = 0;
        let pinger: NodeJS.Timeout;
        const maxRetries = 5;

        const connect = () => {
            const WS_BASE = useSettingsStore.getState().getWsBase();
            const wsUrl = `${WS_BASE}/api/ws/${sessionId}`;
            const ws = new WebSocket(wsUrl)
            wsRef.current = ws

            ws.onopen = () => {
                reconnectCount = 0; // reset
                addLog({
                    id: generateId(),
                    timestamp: Date.now(),
                    source: 'System',
                    intent: 'SYSTEM_INFO',
                    message: `Connected to Session: \${sessionId}`
                })

                // Setup ping heartbeat
                pinger = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'ping' }))
                    }
                }, 15000)
            }

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data)

                    if (data.type === 'connected') {
                        // Handled in onopen mostly
                    }
                    else if (data.type === 'agent_state_change') {
                        updateAgentStatus(data.agent_id, data.status)
                    }
                    else if (data.type === 'telemetry') {
                        addLog(data.data as StreamEvent)
                    }
                    else if (data.type === 'session_status') {
                        // Update global turn or other session fields if needed
                    }
                } catch (err) {
                    console.error("Failed to parse WS message", err)
                }
            }

            ws.onclose = () => {
                clearInterval(pinger)
                if (reconnectCount < maxRetries) {
                    const timeoutMs = Math.min(1000 * Math.pow(2, reconnectCount), 10000);
                    reconnectCount++;
                    addLog({
                        id: generateId(),
                        timestamp: Date.now(),
                        source: 'System',
                        intent: 'WARNING',
                        message: `WebSocket disconnected. Reconnecting in \${timeoutMs/1000}s... (\${reconnectCount}/\${maxRetries})`
                    })
                    setTimeout(connect, timeoutMs)
                } else {
                    addLog({
                        id: generateId(),
                        timestamp: Date.now(),
                        source: 'System',
                        intent: 'ERROR',
                        message: 'WebSocket connection closed definitively. Please refresh the page.'
                    })
                }
            }
        }

        connect()

        return () => {
            clearInterval(pinger)
            if (wsRef.current) {
                // Prevent infinite reconnect loop on unmount
                wsRef.current.onclose = null
                wsRef.current.close()
            }
        }
    }, [sessionId, addLog, updateAgentStatus])

    return wsRef.current
}
