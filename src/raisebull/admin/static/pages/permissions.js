// Permissions page Alpine component
window.permissionsPage = function() {
    return {
        roleMappings: [],
        channelConfig: [],
        saving: false,
        discordRoles: [],
        discordChannels: [],
        discordAvailable: false,

        getApp() {
            const appEl = document.querySelector('[x-data]');
            return Alpine.evaluate(appEl, '$data');
        },

        async load() {
            const app = this.getApp();

            // Fetch Discord roles and channels in parallel, then saved permissions
            const [rolesData, channelsData, permData] = await Promise.all([
                app.api('/api/permissions/discord-roles'),
                app.api('/api/permissions/discord-channels'),
                app.api('/api/permissions'),
            ]);

            if (rolesData) {
                this.discordRoles = rolesData.roles || [];
                this.discordAvailable = rolesData.available || false;
            }
            if (channelsData) {
                this.discordChannels = channelsData.channels || [];
                // Only mark available if both endpoints agree
                this.discordAvailable = this.discordAvailable && (channelsData.available || false);
            }

            if (permData) {
                this.roleMappings = (permData.role_mappings || []).map(r => ({
                    discord_role: r.discord_role,
                    erp_role: r.erp_role,
                }));
                this.channelConfig = (permData.channel_config || []).map(c => ({
                    channel_name: c.channel_name,
                    role_ceiling: c.role_ceiling,
                }));
            }
        },

        async save() {
            this.saving = true;

            // Filter out empty rows
            const roles = this.roleMappings.filter(r => r.discord_role.trim());
            const channels = this.channelConfig.filter(c => c.channel_name.trim());

            const result = await this.getApp().api('/api/permissions', {
                method: 'PUT',
                body: JSON.stringify({
                    role_mappings: roles,
                    channel_config: channels,
                }),
            });
            this.saving = false;

            if (result && result.ok) {
                this.getApp().showToast('Permissions saved', 'success');
                await this.load();
            }
        },
    };
};
export function init(app) { /* Alpine auto-discovers permissionsPage() via x-data */ }
