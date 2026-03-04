"use client"

import { useState } from "react"
import { Play, Settings2, Activity } from "lucide-react"
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
import { Textarea } from "@/components/ui/textarea"
import { useAppStore } from "@/store/appStore"
import { useSettingsStore } from "@/store/settingsStore"
import { useTranslation } from "@/store/i18nStore"

export function ConfigDialog() {
    const t = useTranslation()
    const [open, setOpen] = useState(false)
    const [topic, setTopic] = useState("Transformer attention mechanisms")
    const [outline, setOutline] = useState("1. Introduction\n2. Methodology\n3. Results")
    const setSession = useAppStore(state => state.setSession)

    const [isLoading, setIsLoading] = useState(false)

    const handleStart = async () => {
        if (!topic.trim() || !outline.trim()) return;
        setIsLoading(true);
        try {
            // 1. Create the session
            const outlineSection = outline.split('\n').filter(s => s.trim()).map(s => ({ title: s.trim() }));

            const API_BASE = useSettingsStore.getState().getApiBase();

            const sessionRes = await fetch(`${API_BASE}/api/sessions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    topic,
                    outline: outlineSection,
                    max_turns: 6,
                    budget_limit: 200000
                })
            });

            if (!sessionRes.ok) throw new Error('Failed to create session');
            const sessionData = await sessionRes.json();

            // Set session in Zustand to trigger WebSocket connection
            setSession(sessionData.session_id, sessionData.state);

            // 2. Start the workflow graph
            const workflowRes = await fetch(`${API_BASE}/api/workflow/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionData.session_id,
                    paper_topic: topic,
                    outline: outlineSection
                })
            });

            if (!workflowRes.ok) throw new Error('Failed to start workflow');

            setOpen(false);
        } catch (error) {
            console.error("Error starting session:", error);
            alert("Error starting session. Is the backend running?");
        } finally {
            setIsLoading(false);
        }
    }

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="outline" size="sm" className="gap-2 h-8 hidden sm:flex">
                    <Settings2 size={14} />
                    {t('app.config')}
                </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-[500px]">
                <DialogHeader>
                    <DialogTitle>{t('dialog.title')}</DialogTitle>
                    <DialogDescription>
                        {t('dialog.desc')}
                    </DialogDescription>
                </DialogHeader>
                <div className="grid gap-4 py-4">
                    <div className="grid gap-2">
                        <label htmlFor="topic" className="text-sm font-medium">{t('dialog.topic')}</label>
                        <Input
                            id="topic"
                            value={topic}
                            onChange={(e) => setTopic(e.target.value)}
                            placeholder={t('dialog.topic.placeholder') as string}
                        />
                    </div>
                    <div className="grid gap-2">
                        <label htmlFor="outline" className="text-sm font-medium">{t('dialog.outline')}</label>
                        <Textarea
                            id="outline"
                            value={outline}
                            onChange={(e) => setOutline(e.target.value)}
                            placeholder="1. Introduction..."
                            className="h-32"
                        />
                    </div>
                </div>
                <DialogFooter>
                    <Button variant="outline" onClick={() => setOpen(false)} disabled={isLoading}>
                        {t('dialog.cancel')}
                    </Button>
                    <Button onClick={handleStart} className="gap-2" disabled={isLoading}>
                        {isLoading ? <Activity size={14} className="animate-spin" /> : <Play size={14} />}
                        {isLoading ? t('app.simulating') : t('dialog.start')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
