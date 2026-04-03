// Credentials page Alpine component
window.credentialsPage = function() {
    return {
        credentials: [],
        showAdd: false,
        form: { key_name: '', key_value: '', service: '' },
        testing: false,
        testResult: null,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            this.credentials = await this.getApp().api('/api/credentials') || [];
        },

        async create() {
            const svcMap = { MINIMAX_API_KEY: 'llm', SERPER_API_KEY: 'mcp', JINA_API_KEY: 'mcp', TAVILY_API_KEY: 'mcp', AGENTS_INFRA_API_KEY: 'infra' };
            this.form.service = svcMap[this.form.key_name] || '';
            await this.getApp().api('/api/credentials', { method: 'POST', body: JSON.stringify(this.form) });
            this.showAdd = false;
            this.form = { key_name: '', key_value: '', service: '' };
            this.testResult = null;
            await this.load();
            this.getApp().showToast('Credential saved', 'success');
        },

        async reveal(cred) {
            if (cred._revealed) { cred._revealed = null; return; }
            const data = await this.getApp().api('/api/credentials/' + cred.id + '/reveal');
            if (data) cred._revealed = data.key_value;
        },

        async remove(id) {
            await this.getApp().api('/api/credentials/' + id, { method: 'DELETE' });
            await this.load();
            this.getApp().showToast('Credential deleted', 'success');
        },

        async test() {
            this.testing = true;
            this.testResult = null;
            this.testResult = await this.getApp().api('/api/credentials/test', {
                method: 'POST',
                body: JSON.stringify({ key_name: this.form.key_name, key_value: this.form.key_value })
            });
            this.testing = false;
        },
    };
};
export function init(app) { /* Alpine auto-discovers credentialsPage() via x-data */ }
