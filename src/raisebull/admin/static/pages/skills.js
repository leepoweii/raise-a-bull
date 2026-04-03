// Skills editor page Alpine component
window.skillsPage = function() {
    return {
        skills: [],
        selectedSkill: null,
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
            this.skills = await this.getApp().api('/api/skills') || [];
            const last = localStorage.getItem('rac-skills-lastfile');
            if (last && this.skills.some(s => s.name === last)) {
                await this.selectSkill(last);
            }
        },

        async selectSkill(name) {
            if (this.dirty) {
                this._saveToLocalStorage();
            }

            this.selectedSkill = name;
            localStorage.setItem('rac-skills-lastfile', name);
            this._autosaveKey = 'rac-skill-draft:' + name;

            const draft = localStorage.getItem(this._autosaveKey);

            const data = await this.getApp().api('/api/skills/' + name);
            if (data) {
                this.originalContent = data.content;
                if (draft && draft !== data.content) {
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
            clearTimeout(this._autosaveTimer);
            this._autosaveTimer = setTimeout(() => this._saveToLocalStorage(), 2000);
        },

        _saveToLocalStorage() {
            if (this._autosaveKey && this.content !== this.originalContent) {
                localStorage.setItem(this._autosaveKey, this.content);
            }
        },

        async save() {
            if (!this.selectedSkill || this.saving) return;
            this.saving = true;

            const result = await this.getApp().api('/api/skills/' + this.selectedSkill, {
                method: 'PUT',
                body: JSON.stringify({ content: this.content }),
            });

            this.saving = false;
            if (result && result.ok) {
                this.originalContent = this.content;
                this.dirty = false;
                localStorage.removeItem(this._autosaveKey);
                this.getApp().showToast('Saved', 'success');
                this.skills = await this.getApp().api('/api/skills') || [];
            }
        },

        formatSize(bytes) {
            if (bytes < 1024) return bytes + ' B';
            return (bytes / 1024).toFixed(1) + ' KB';
        },
    };
};
export function init(app) { /* Alpine auto-discovers skillsPage() via x-data */ }
