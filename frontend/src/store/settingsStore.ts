"use client"

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface SettingsState {
    /** Backend API base URL, e.g. http://pydys.art:8000 */
    apiBaseUrl: string
    /** WebSocket base URL, e.g. ws://pydys.art:8000 */
    wsBaseUrl: string

    // Actions
    setApiBaseUrl: (url: string) => void
    setWsBaseUrl: (url: string) => void

    /** Derive API base from current browser location */
    getApiBase: () => string
    getWsBase: () => string
}

export const useSettingsStore = create<SettingsState>()(
    persist(
        (set, get) => ({
            apiBaseUrl: '',
            wsBaseUrl: '',

            setApiBaseUrl: (url: string) => set({ apiBaseUrl: url.replace(/\/+$/, '') }),
            setWsBaseUrl: (url: string) => set({ wsBaseUrl: url.replace(/\/+$/, '') }),

            getApiBase: () => {
                const stored = get().apiBaseUrl
                if (stored) return stored
                if (typeof window !== 'undefined') {
                    const { protocol, hostname, port } = window.location
                    // If on port 80/443 or no port, we're behind Nginx — use same origin
                    if (!port || port === '80' || port === '443') {
                        return `${protocol}//${hostname}`
                    }
                    // Local dev: assume backend is on 8000
                    return `http://${hostname}:8000`
                }
                return 'http://localhost:8000'
            },

            getWsBase: () => {
                const stored = get().wsBaseUrl
                if (stored) return stored
                if (typeof window !== 'undefined') {
                    const { protocol, hostname, port } = window.location
                    const wsProtocol = protocol === 'https:' ? 'wss:' : 'ws:'
                    if (!port || port === '80' || port === '443') {
                        return `${wsProtocol}//${hostname}`
                    }
                    return `ws://${hostname}:8000`
                }
                return 'ws://localhost:8000'
            },
        }),
        {
            name: 'pdmaws-settings',
        }
    )
)
