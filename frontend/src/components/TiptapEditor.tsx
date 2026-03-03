"use client"

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { useEffect } from 'react'
import { useAppStore } from '@/store/appStore'
import { useTranslation } from '@/store/i18nStore'

export function TiptapEditor() {
    const t = useTranslation()
    const content = useAppStore(state => state.documentContent)
    const updateDocument = useAppStore(state => state.updateDocument)

    const editor = useEditor({
        extensions: [
            StarterKit,
            Placeholder.configure({
                placeholder: t('editor.placeholder') as string,
            }),
        ],
        immediatelyRender: false,
        content: content,
        onUpdate: ({ editor }) => {
            // For local manual edits (Human-in-the-loop)
            updateDocument(editor.getHTML())
        },
        editorProps: {
            attributes: {
                class: 'prose prose-sm dark:prose-invert sm:prose-base focus:outline-none max-w-none h-full min-h-[500px] p-6',
            },
        },
    })

    // Sync external state changes (Agent Patches) into editor
    useEffect(() => {
        if (editor && content !== editor.getHTML()) {
            editor.commands.setContent(content)
        }
    }, [content, editor])

    return (
        <div className="w-full h-full bg-background rounded-b-md">
            <EditorContent editor={editor} className="h-full overflow-y-auto" />
        </div>
    )
}
