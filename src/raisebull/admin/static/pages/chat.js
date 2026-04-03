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

            const data = await this.getApp().api('/api/chat/' + encodeURIComponent(sid));
            if (Array.isArray(data)) {
                this.messages = data;
                this.$nextTick(() => this.scrollToBottom());
            }
        },

        async send() {
            if (!this.currentSession || !this.input.trim() || this.sending) return;

            const msg = this.input.trim();
            this.input = '';
            this.sending = true;

            // Optimistic: add user message immediately
            this.messages.push({ role: 'user', content: msg });
            this.$nextTick(() => this.scrollToBottom());

            try {
                const resp = await fetch('/admin/api/chat/' + encodeURIComponent(this.currentSession), {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'text/event-stream',
                    },
                    credentials: 'same-origin',
                    body: JSON.stringify({ message: msg }),
                });

                if (resp.status === 401) {
                    window.location.hash = '#/login';
                    return;
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

                // Reload full history for clean state
                await this.selectSession(this.currentSession);
                await this.loadSessions();
            } catch (e) {
                // Restore input on failure so user can retry
                this.input = msg;
                this.messages.pop();
                const appEl = document.querySelector('[x-data]');
                Alpine.evaluate(appEl, '$data').showToast('Connection error', 'error');
            }

            this.sending = false;
            this.$nextTick(() => this.scrollToBottom());
        },

        handleStreamEvent(event) {
            if (event.type === 'thinking') {
                this.messages.push({ role: 'assistant', thinking: event.content });
            } else if (event.type === 'tool_call') {
                this.messages.push({
                    role: 'assistant',
                    tool_calls: [{ name: event.tool_name, arguments: event.tool_args }],
                });
            } else if (event.type === 'tool_result') {
                this.messages.push({ role: 'tool', name: event.tool_name, content: event.content });
            } else if (event.type === 'response') {
                this.messages.push({ role: 'assistant', content: event.content });
            } else if (event.type === 'error') {
                this.messages.push({ role: 'assistant', content: '⚠️ ' + (event.content || 'Unknown error') });
            }
            this.$nextTick(() => this.scrollToBottom());
        },

        async uploadFile(event) {
            const file = event.target.files[0];
            if (!file || !this.currentSession) return;

            const formData = new FormData();
            formData.append('file', file);

            this.sending = true;
            this.messages.push({ role: 'user', content: '📎 ' + file.name });
            this.$nextTick(() => this.scrollToBottom());

            try {
                const resp = await fetch('/admin/api/chat/' + encodeURIComponent(this.currentSession) + '/upload', {
                    method: 'POST',
                    body: formData,
                });

                if (resp.status === 401) {
                    window.location.hash = '#/login';
                    return;
                }

                const data = await resp.json();
                if (data.ok) {
                    await this.selectSession(this.currentSession);
                    this.getApp().showToast('File processed', 'success');
                } else {
                    this.getApp().showToast(data.error || 'Upload failed', 'error');
                }
            } catch (e) {
                this.getApp().showToast('Upload failed', 'error');
            }

            this.sending = false;
            event.target.value = '';
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
                await this.loadSessions();
                this.getApp().showToast('Session deleted', 'success');
            }
        },

        scrollToBottom() {
            const el = this.$refs.messageContainer;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        },

        shortId(sid) {
            // "web:session:abc123def456" → "abc123def456"
            if (!sid) return '';
            const parts = sid.split(':');
            return parts[parts.length - 1] || sid;
        },

        renderMarkdown(text) {
            if (!text) return '';
            // Escape HTML
            let s = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
            // Code blocks (```)
            s = s.replace(/```([\s\S]*?)```/g, '<pre class="chat-code-block">$1</pre>');
            // Inline code
            s = s.replace(/`([^`]+)`/g, '<code class="chat-inline-code">$1</code>');
            // Bold
            s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
            // Newlines → <br>
            s = s.replace(/\n/g, '<br>');
            return s;
        },
    };
};
export function init(app) { /* Alpine auto-discovers chatPage() via x-data */ }
