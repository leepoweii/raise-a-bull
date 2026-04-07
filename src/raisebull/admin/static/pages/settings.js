// Settings page Alpine component
window.settingsPage = function() {
    return {
        settings: {
            agent_name: '',
            model: '',
            max_steps: '',
            auto_reply_timeout: '',
            session_idle_timeout: '',
            heartbeat_interval: '',
            buffer_time: '',
            nightly_compact_hour: '',
            nightly_compact_threshold: '',
            line_trigger_prefix: '',
        },
        models: [],
        saving: false,
        saved: false,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            const data = await this.getApp().api('/api/settings');
            if (data) {
                this.settings = { ...this.settings, ...data };
            }
            // Fetch available models
            const models = await this.getApp().api('/api/models');
            if (models) {
                this.models = models;
            }
        },

        async save() {
            this.saving = true;
            this.saved = false;

            const result = await this.getApp().api('/api/settings', {
                method: 'PUT',
                body: JSON.stringify(this.settings),
            });
            this.saving = false;

            if (result && result.ok) {
                this.saved = true;
                this.getApp().showToast('Settings saved', 'success');
            }
        },
    };
};
export function init(app) { /* Alpine auto-discovers settingsPage() via x-data */ }
