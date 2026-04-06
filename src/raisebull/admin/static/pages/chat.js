// Web Chat page Alpine component
window.chatPage = function() {
    return {
        sessions: [],
        currentSession: null,
        currentSessionType: null,
        currentSessionName: null,
        messages: [],
        input: '',
        sending: false,
        pendingFiles: [],
        dragActive: false,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            await this.loadSessions();
        },

        async loadSessions() {
            this.sessions = await this.getApp().api('/api/chat/sessions') || [];
        },

        async newSession() {
            const result = await this.getApp().api('/api/chat/sessions', {
                method: 'POST',
            });
            if (result && result.id) {
                await this.loadSessions();
                await this.selectSession(result.id);
            }
        },

        async selectSession(sid) {
            this.currentSession = sid;
            const session = this.sessions.find(s => s.id === sid);
            this.currentSessionType = session?.type || 'web';
            this.currentSessionName = session?.name || null;
            this.messages = [];
            this.input = '';
            this.pendingFiles = [];

            // Load conversation history from Claude Code .jsonl
            try {
                const history = await this.getApp().api(
                    '/api/chat/' + encodeURIComponent(sid) + '/history'
                );
                if (Array.isArray(history)) {
                    for (const msg of history) {
                        this.messages.push(msg);
                    }
                }
            } catch (e) {
                // History unavailable — empty chat is fine
            }
            this.$nextTick(() => this.scrollToBottom());
        },

        addFiles(event) {
            const newFiles = Array.from(event.target.files || []);
            this._validateAndAddFiles(newFiles);
            event.target.value = '';
        },

        handleDrop(event) {
            this.dragActive = false;
            const newFiles = Array.from(event.dataTransfer.files || []);
            this._validateAndAddFiles(newFiles);
        },

        _validateAndAddFiles(newFiles) {
            const app = this.getApp();
            for (const f of newFiles) {
                if (f.size > 10 * 1024 * 1024) {
                    app.showToast('檔案過大：' + f.name + '（上限 10MB）', 'error');
                    continue;
                }
                if (this.pendingFiles.length >= 5) {
                    app.showToast('最多 5 個檔案', 'error');
                    break;
                }
                this.pendingFiles.push(f);
            }
        },

        removePendingFile(idx) {
            this.pendingFiles.splice(idx, 1);
        },

        formatFileSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
        },

        async send() {
            if (!this.currentSession || this.sending) return;
            const msg = this.input.trim();
            const files = [...this.pendingFiles];
            if (!msg && files.length === 0) return;

            this.input = '';
            this.pendingFiles = [];
            this.sending = true;

            const userContent = files.length > 0
                ? (files.map(f => '📎 ' + f.name).join(', ') + (msg ? '\n' + msg : ''))
                : msg;
            this.messages.push({ role: 'user', content: userContent });
            this.$nextTick(() => this.scrollToBottom());

            try {
                let fetchOpts;
                const url = '/admin/api/chat/' + encodeURIComponent(this.currentSession) + '/messages';

                if (files.length > 0) {
                    const form = new FormData();
                    form.append('content', msg);
                    for (const f of files) form.append('files', f);
                    fetchOpts = {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: { 'Accept': 'text/event-stream' },
                        body: form,
                    };
                } else {
                    fetchOpts = {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'Accept': 'text/event-stream',
                        },
                        body: JSON.stringify({ content: msg }),
                    };
                }

                const resp = await fetch(url, fetchOpts);

                if (resp.status === 401) {
                    window.location.hash = '#/login';
                    return;
                }
                if (resp.status === 413) {
                    this.getApp().showToast('檔案過大（上限 10MB）', 'error');
                    throw new Error('File too large');
                }
                if (!resp.ok) throw new Error('Request failed');

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();

                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        try {
                            const event = JSON.parse(line.slice(6));
                            this.handleStreamEvent(event);
                        } catch (e) { /* skip malformed */ }
                    }
                }

                await this.loadSessions();
            } catch (e) {
                this.input = msg;
                this.pendingFiles = files;
                this.messages.pop();
                this.getApp().showToast('Connection error', 'error');
            }

            this.sending = false;
            this.$nextTick(() => this.scrollToBottom());
        },

        handleStreamEvent(event) {
            if (event.type === 'thinking') {
                this.messages.push({ role: 'assistant', thinking: event.content });
            } else if (event.type === 'tool_call') {
                const c = event.content || {};
                this.messages.push({
                    role: 'assistant',
                    tool_calls: [{ name: c.name, arguments: JSON.stringify(c.input || {}) }],
                });
            } else if (event.type === 'tool_result') {
                this.messages.push({ role: 'tool', content: event.content });
            } else if (event.type === 'text') {
                this.messages.push({ role: 'assistant', content: event.content });
            } else if (event.type === 'error') {
                this.messages.push({ role: 'assistant', content: '⚠️ ' + (event.content || 'Unknown error') });
            } else if (event.type === 'done') {
                // Done
            }
            this.$nextTick(() => this.scrollToBottom());
        },

        async deleteSession() {
            if (!this.currentSession) return;
            if (!confirm('Delete this session?')) return;

            const result = await this.getApp().api('/api/chat/' + encodeURIComponent(this.currentSession), {
                method: 'DELETE',
            });

            if (result && result.ok) {
                this.currentSession = null;
                this.currentSessionType = null;
                this.currentSessionName = null;
                this.messages = [];
                this.input = '';
                this.pendingFiles = [];
                await this.loadSessions();
                this.getApp().showToast('Session deleted', 'success');
            }
        },

        scrollToBottom() {
            const el = this.$refs.messageContainer;
            if (el) el.scrollTop = el.scrollHeight;
        },

        sessionIcon(type) {
            return { web: '💬', discord: '🎮', line: '📱', heartbeat: '💓' }[type] || '📋';
        },

        formatTokens(count) {
            if (!count) return '0 tokens';
            if (count >= 1000000) return (count / 1000000).toFixed(1) + 'M tokens';
            if (count >= 1000) return (count / 1000).toFixed(1) + 'K tokens';
            return count + ' tokens';
        },

        shortId(sid) {
            if (!sid) return '';
            const parts = sid.split(':');
            return parts[parts.length - 1] || sid;
        },

        renderMarkdown(text) {
            if (!text) return '';
            let s = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            s = s.replace(/```([\s\S]*?)```/g, '<pre class="chat-code-block">$1</pre>');
            s = s.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            s = s.replace(/\n/g, '<br>');
            return s;
        },
    };
};
export function init(app) { /* Alpine auto-discovers chatPage() via x-data */ }
