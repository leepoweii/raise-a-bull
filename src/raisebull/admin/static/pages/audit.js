// Audit Log page Alpine component
window.auditPage = function() {
    return {
        fromDate: new Date(Date.now() - 7 * 86400e3).toISOString().slice(0, 10),
        toDate: new Date().toISOString().slice(0, 10),
        fetchedRows: [],
        truncated: false,
        loading: false,
        error: null,

        categories: [
            { name: 'Auth',      actions: ['login.success', 'login.fail'] },
            { name: 'Dashboard', actions: ['settings.put', 'session.delete', 'credentials.create', 'credentials.put', 'credentials.delete'] },
            { name: 'Internal',  actions: ['internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push'] },
            { name: 'Scheduler', actions: ['scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push'] },
            { name: 'LINE',      actions: ['line.signature_fail'] },
        ],

        selectedActions: new Set([
            'login.success', 'login.fail',
            'settings.put', 'session.delete', 'credentials.create', 'credentials.put', 'credentials.delete',
            'internal.heartbeat', 'internal.nightly_compact', 'internal.discord_push',
            'scheduler.heartbeat', 'scheduler.nightly_compact', 'scheduler.discord_push',
            'line.signature_fail',
        ]),

        get filteredRows() {
            return this.fetchedRows.filter(r => this.selectedActions.has(r.action));
        },

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            this.loading = true;
            this.error = null;
            try {
                const from = `${this.fromDate}T00:00:00Z`;
                const to = `${this.toDate}T23:59:59Z`;
                const data = await this.getApp().api(
                    `/api/audit?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=500`
                );
                if (data === null) {
                    // app.api() returns null on error or 401 (which redirects to login)
                    return;
                }
                this.fetchedRows = data.rows || [];
                this.truncated = !!data.truncated;
            } catch (e) {
                this.error = String(e);
            } finally {
                this.loading = false;
            }
        },

        toggleAction(action) {
            if (this.selectedActions.has(action)) {
                this.selectedActions.delete(action);
            } else {
                this.selectedActions.add(action);
            }
            // Force Alpine reactivity on Set mutation
            this.selectedActions = new Set(this.selectedActions);
        },

        selectAll() {
            this.selectedActions = new Set(
                this.categories.flatMap(c => c.actions)
            );
        },

        selectNone() {
            this.selectedActions = new Set();
        },

        formatTs(ts) {
            if (!ts) return '';
            // "2026-04-08T03:42:11.123456+00:00" → "04-08 03:42 UTC"
            return ts.slice(5, 10) + ' ' + ts.slice(11, 16) + ' UTC';
        },

        init() {
            this.load();
        },
    };
};
export function init(app) { /* Alpine auto-discovers auditPage() via x-data */ }
