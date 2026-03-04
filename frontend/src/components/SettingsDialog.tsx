"use client"

import { useState, useEffect } from "react"
import { Settings2 } from "lucide-react"
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
import { useTranslation } from "@/store/i18nStore"

export function SettingsDialog() {
    const t = useTranslation()
    const { apiBaseUrl, wsBaseUrl, getApiBase, getWsBase, setApiBaseUrl, setWsBaseUrl } = useSettingsStore()
    const [open, setOpen] = useState(false)
    const [localApiUrl, setLocalApiUrl] = useState('')
    const [localWsUrl, setLocalWsUrl] = useState('')

    useEffect(() => {
        if (open) {
            setLocalApiUrl(apiBaseUrl || getApiBase())
            setLocalWsUrl(wsBaseUrl || getWsBase())
        }
    }, [open, apiBaseUrl, wsBaseUrl, getApiBase, getWsBase])

    const handleSave = () => {
        setApiBaseUrl(localApiUrl)
        setWsBaseUrl(localWsUrl)
        setOpen(false)
    }

    const handleReset = () => {
        setApiBaseUrl('')
        setWsBaseUrl('')
        if (typeof window !== 'undefined') {
            setLocalApiUrl(`http://${window.location.hostname}:8000`)
            setLocalWsUrl(`ws://${window.location.hostname}:8000`)
        }
    }

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="ghost" size="sm" className="h-8 w-8 p-0" title="API 设置">
                    <Settings2 size={14} />
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[480px]">
                <DialogHeader>
                    <DialogTitle>⚙️ 连接设置</DialogTitle>
                    <DialogDescription>
                        配置后端 API 地址。留空则自动使用当前域名。
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                        <label htmlFor="api-url" className="text-sm font-medium">
                            后端 API 地址
                        </label>
                        <Input
                            id="api-url"
                            value={localApiUrl}
                            onChange={(e) => setLocalApiUrl(e.target.value)}
                            placeholder="http://pydys.art:8000"
                        />
                        <p className="text-xs text-muted-foreground">
                            FastAPI 后端的 HTTP 地址（含端口）
                        </p>
                    </div>
                    <div className="grid gap-2">
                        <label htmlFor="ws-url" className="text-sm font-medium">
                            WebSocket 地址
                        </label>
                        <Input
                            id="ws-url"
                            value={localWsUrl}
                            onChange={(e) => setLocalWsUrl(e.target.value)}
                            placeholder="ws://pydys.art:8000"
                        />
                        <p className="text-xs text-muted-foreground">
                            实时消息推送的 WebSocket 地址
                        </p>
                    </div>
                </div>
                <DialogFooter className="gap-2 sm:gap-0">
                    <Button variant="outline" onClick={handleReset} className="mr-auto">
                        重置为默认
                    </Button>
                    <Button variant="outline" onClick={() => setOpen(false)}>
                        取消
                    </Button>
                    <Button onClick={handleSave}>
                        保存
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
