// Status page Alpine component
// Interval tracked on window so route() can clear it on page switch
window.statusPage = function() {
    return {
        data: {},
        async load() {
            const appEl = document.querySelector('[x-data]');
            const appData = Alpine.evaluate(appEl, '$data');
            this.data = await appData.api('/api/bootstrap') || {};
            this.data._lastUpdated = new Date().toLocaleTimeString();

            // Auto-refresh every 30s (only one interval at a time)
            if (!window._statusInterval) {
                window._statusInterval = setInterval(() => this.load(), 30000);
            }
        },
    };
};
export function init(app) { /* Alpine auto-discovers statusPage() via x-data */ }
