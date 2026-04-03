// Heartbeat page Alpine component
window.heartbeatPage = function() {
    return {
        tasks: [],
        lastRun: {},
        rawMarkdown: '',
        editMode: false,
        saving: false,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            const data = await this.getApp().api('/api/heartbeat');
            if (data) {
                this.tasks = data.tasks || [];
                this.lastRun = data.last_run || {};
                this.rawMarkdown = data.raw_markdown || '';
            }
        },

        async saveMarkdown() {
            this.saving = true;
            const result = await this.getApp().api('/api/heartbeat', {
                method: 'PUT',
                body: JSON.stringify({ content: this.rawMarkdown }),
            });
            this.saving = false;

            if (result && result.ok) {
                this.getApp().showToast('Heartbeat saved', 'success');
                // Re-parse tasks
                await this.load();
                this.editMode = false;
            }
        },
    };
};
export function init(app) { /* Alpine auto-discovers heartbeatPage() via x-data */ }
