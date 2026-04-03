function app() {
    return {
        page: 'status',
        pageContent: '<p>Loading...</p>',
        theme: localStorage.getItem('rac-theme') || 'light',
        toast: { show: false, msg: '', type: 'info' },
        menuOpen: false,

        async init() {
            document.documentElement.setAttribute('data-theme', this.theme);
            window.addEventListener('hashchange', () => this.route());
            this.route();
        },

        go(page) {
            window.location.hash = '#/' + page;
        },

        async route() {
            const hash = window.location.hash || '#/status';
            this.page = hash.replace('#/', '');

            // Clean up page-level intervals (e.g. status auto-refresh)
            if (window._statusInterval) {
                clearInterval(window._statusInterval);
                window._statusInterval = null;
            }

            const el = document.getElementById('page-content');
            if (el) el.classList.add('fading');
            await new Promise(r => setTimeout(r, 150)); // wait for fade-out

            try {
                const resp = await fetch(`/admin/pages/${this.page}.html`);
                if (!resp.ok) throw new Error('Page not found');
                let html = await resp.text();
                html = html.replace(/<script[\s\S]*?<\/script>/gi, '');

                try {
                    const mod = await import(`/admin/pages/${this.page}.js`);
                    if (mod.init) mod.init(this);
                } catch (e) {}

                this.pageContent = html;
            } catch (e) {
                const safe = this.page.replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
                this.pageContent = '<h2>Page not found</h2><p>' + safe + '</p>';
            }

            this.$nextTick(() => { if (el) el.classList.remove('fading'); });
        },

        toggleTheme() {
            this.theme = this.theme === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', this.theme);
            localStorage.setItem('rac-theme', this.theme);
        },

        showToast(msg, type = 'info') {
            this.toast = { show: true, msg, type };
        },

        async api(path, opts = {}) {
            try {
                const resp = await fetch(`/admin${path}`, {
                    headers: { 'Content-Type': 'application/json', ...opts.headers },
                    ...opts,
                });
                if (resp.status === 401) {
                    window.location.hash = '#/login';
                    return null;
                }
                const data = await resp.json();
                if (data.error) {
                    this.showToast(data.error, 'error');
                    return null;
                }
                return data;
            } catch (e) {
                this.showToast('Connection error', 'error');
                return null;
            }
        },
    };
}
