"use client"

import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Placeholder from '@tiptap/extension-placeholder'
import { useEffect } from 'react'
import { useAppStore } from '@/store/appStore'
import { useTranslation } from '@/store/i18nStore'
import { Bold, Italic, Heading1, Heading2, Heading3, List, ListOrdered, Quote, Code, Undo, Redo, Minus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipTrigger, TooltipContent } from '@/components/ui/tooltip'
import { marked } from 'marked'

function ToolbarButton({ onClick, isActive, icon: Icon, label }: { onClick: () => void; isActive?: boolean; icon: React.ComponentType<{ size?: number }>; label: string }) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <Button
                    variant="ghost"
                    size="sm"
                    className={`h-7 w-7 p-0 ${isActive ? 'bg-accent text-accent-foreground' : ''}`}
                    onClick={onClick}
                >
                    <Icon size={14} />
                </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">{label}</TooltipContent>
        </Tooltip>
    )
}

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
        content: '', // Start empty, useEffect will populate it
        onUpdate: ({ editor }) => {
            // We want to save the state, but we also want to avoid triggering endless formatting loops.
            // When user types, we save HTML back to the store so next render keeps it formatted.
            updateDocument(editor.getHTML())
        },
        editorProps: {
            attributes: {
                class: 'prose prose-sm dark:prose-invert sm:prose-base focus:outline-none max-w-none h-full min-h-[500px] p-6',
            },
        },
    })

    useEffect(() => {
        if (!editor || !content) return;

        // Define an async helper to parse markdown
        const loadContent = async () => {
            // Check if it's already HTML (e.g. user typed something and we saved it)
            // or if it's raw markdown from the backend. 
            // Simple heuristic: if it contains typical markdown headers or lists but no <p> tags.
            const isHtml = content.includes('<p>') || content.includes('<h1>') || content.includes('<h2>') || content.includes('<ul>');

            let htmlToSet = content;
            if (!isHtml) {
                // If it looks like raw markdown, parse it to HTML
                try {
                    // marked.parse can be synchronous or asynchronous depending on configuration
                    const parsed = await marked.parse(content);
                    htmlToSet = parsed;
                } catch (e) {
                    console.error("Markdown parsing failed:", e);
                }
            }

            // Only update if the parsed content is actually different from current editor content
            // to avoid resetting selection cursor
            if (editor.getHTML() !== htmlToSet) {
                editor.commands.setContent(htmlToSet, { emitUpdate: false }) // preserves history/cursor better contextually
            }
        };

        loadContent();
    }, [content, editor])

    return (
        <div className="w-full h-full bg-background rounded-b-md flex flex-col">
            {/* Toolbar */}
            {editor && (
                <div className="flex items-center gap-0.5 px-3 py-1.5 border-b bg-muted/30 flex-wrap shrink-0">
                    <ToolbarButton onClick={() => editor.chain().focus().toggleBold().run()} isActive={editor.isActive('bold')} icon={Bold} label="加粗" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleItalic().run()} isActive={editor.isActive('italic')} icon={Italic} label="斜体" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleCode().run()} isActive={editor.isActive('code')} icon={Code} label="行内代码" />
                    <Separator orientation="vertical" className="h-5 mx-1" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()} isActive={editor.isActive('heading', { level: 1 })} icon={Heading1} label="一级标题" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()} isActive={editor.isActive('heading', { level: 2 })} icon={Heading2} label="二级标题" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()} isActive={editor.isActive('heading', { level: 3 })} icon={Heading3} label="三级标题" />
                    <Separator orientation="vertical" className="h-5 mx-1" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleBulletList().run()} isActive={editor.isActive('bulletList')} icon={List} label="无序列表" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleOrderedList().run()} isActive={editor.isActive('orderedList')} icon={ListOrdered} label="有序列表" />
                    <ToolbarButton onClick={() => editor.chain().focus().toggleBlockquote().run()} isActive={editor.isActive('blockquote')} icon={Quote} label="引用" />
                    <ToolbarButton onClick={() => editor.chain().focus().setHorizontalRule().run()} icon={Minus} label="分隔线" />
                    <Separator orientation="vertical" className="h-5 mx-1" />
                    <ToolbarButton onClick={() => editor.chain().focus().undo().run()} icon={Undo} label="撤销" />
                    <ToolbarButton onClick={() => editor.chain().focus().redo().run()} icon={Redo} label="重做" />
                </div>
            )}
            <EditorContent editor={editor} className="flex-1 overflow-y-auto" />
        </div>
    )
}
