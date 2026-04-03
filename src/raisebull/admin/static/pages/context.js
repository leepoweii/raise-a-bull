// Context editor page Alpine component
window.contextPage = function() {
    return {
        files: [],
        selectedFile: null,
        content: '',
        originalContent: '',
        dirty: false,
        mobileEditing: false,
        saving: false,
        _autosaveTimer: null,
        _autosaveKey: null,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            this.files = await this.getApp().api('/api/context') || [];
            // Restore last selected file
            const last = localStorage.getItem('rac-context-lastfile');
            if (last && this.files.some(f => f.filename === last)) {
                await this.selectFile(last);
            }
        },

        async selectFile(filename) {
            // Check for unsaved changes
            if (this.dirty) {
                this._saveToLocalStorage();
            }

            this.selectedFile = filename;
            localStorage.setItem('rac-context-lastfile', filename);
            this._autosaveKey = 'rac-context-draft:' + filename;

            // Check localStorage for draft
            const draft = localStorage.getItem(this._autosaveKey);

            const data = await this.getApp().api('/api/context/' + filename);
            if (data) {
                this.originalContent = data.content;
                if (draft && draft !== data.content) {
                    // Recovered draft differs from server
                    this.content = draft;
                    this.dirty = true;
                    this.getApp().showToast('Draft recovered from local storage', 'info');
                } else {
                    this.content = data.content;
                    this.dirty = false;
                    localStorage.removeItem(this._autosaveKey);
                }
            }
            this.mobileEditing = true;
        },

        mobileShowList() {
            this.mobileEditing = false;
        },

        markDirty() {
            this.dirty = true;
            // Auto-save to localStorage with 2s debounce
            clearTimeout(this._autosaveTimer);
            this._autosaveTimer = setTimeout(() => this._saveToLocalStorage(), 2000);
        },

        _saveToLocalStorage() {
            if (this._autosaveKey && this.content !== this.originalContent) {
                localStorage.setItem(this._autosaveKey, this.content);
            }
        },

        async save() {
            if (!this.selectedFile || this.saving) return;
            this.saving = true;

            const result = await this.getApp().api('/api/context/' + this.selectedFile, {
                method: 'PUT',
                body: JSON.stringify({ content: this.content }),
            });

            this.saving = false;
            if (result && result.ok) {
                this.originalContent = this.content;
                this.dirty = false;
                localStorage.removeItem(this._autosaveKey);
                this.getApp().showToast('Saved', 'success');
                // Refresh file list for updated size/modified
                this.files = await this.getApp().api('/api/context') || [];
            }
        },

        formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            return (bytes / 1024).toFixed(1) + ' KB';
        },
    };
};
export function init(app) { /* Alpine auto-discovers contextPage() via x-data */ }
