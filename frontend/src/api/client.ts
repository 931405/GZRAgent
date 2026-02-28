import axios from 'axios';

const API_BASE = 'http://localhost:8000/api';

export const apiClient = axios.create({
    baseURL: API_BASE,
    headers: {
        'Content-Type': 'application/json',
    },
});

export const api = {
    // --- Workflow ---
    startWorkflow: async (data: any) => {
        const res = await apiClient.post('/workflow/start', data);
        return res.data;
    },
    getWorkflowResult: async (runId: string) => {
        const res = await apiClient.get(`/workflow/result/${runId}`);
        return res.data;
    },

    // --- Knowledge Base ---
    getKbStats: async () => {
        const res = await apiClient.get('/knowledge/stats');
        return res.data;
    },
    scanFolder: async (folderPath: string) => {
        const res = await apiClient.post('/knowledge/scan', { folder_path: folderPath });
        return res.data;
    },

    // --- History ---
    getHistoryList: async () => {
        const res = await apiClient.get('/history/list');
        return res.data.files;
    },
    loadHistory: async (filename: string) => {
        const res = await apiClient.get(`/history/${filename}`);
        return res.data;
    },
    saveHistory: async (graphState: any) => {
        const res = await apiClient.post('/history/save', { graph_state: graphState });
        return res.data;
    },

    // --- Templates ---
    getTemplateList: async () => {
        const res = await apiClient.get('/templates/list');
        return res.data.templates;
    },
    getTemplate: async (name: string) => {
        const res = await apiClient.get(`/templates/${name}`);
        return res.data;
    },
    saveTemplate: async (data: { name: string; description: string; sections: any }) => {
        const res = await apiClient.post('/templates/save', data);
        return res.data;
    },
    uploadTemplateFile: async (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/templates/upload-file`, {
            method: 'POST',
            body: formData,
        });
        const json = await res.json();
        if (!res.ok) throw new Error(json.error || 'Upload failed');
        return json as { name: string; sections_count: number; detected_sections: string[]; templates: string[] };
    },
    getPreferences: async () => {
        const res = await apiClient.get('/preferences/');
        return res.data;
    },
    savePreferences: async (data: any) => {
        const res = await apiClient.post('/preferences/', data);
        return res.data;
    },

    // --- Export ---
    exportWordUrl: `${API_BASE}/export/word`,

    exportWord: async (data: {
        project_type: string;
        research_topic: string;
        draft_sections: Record<string, string>;
        generate_images?: boolean;
        template_name?: string | null;
    }) => {
        // Returns a Blob for file download
        const res = await fetch(`${API_BASE}/export/word`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error(`Export failed: ${res.status}`);
        return res.blob();
    },

    listExportTemplates: async () => {
        const res = await apiClient.get('/export/templates');
        return res.data.templates as Array<{ filename: string; detected_sections: string[]; mtime: number }>;
    },

    uploadExportTemplate: async (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${API_BASE}/export/upload-template`, {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) throw new Error('Upload failed');
        return res.json();
    },

    // --- Workflow Control ---
    stopWorkflow: async (runId: string) => {
        const res = await apiClient.post(`/workflow/stop/${runId}`);
        return res.data;
    },
};
