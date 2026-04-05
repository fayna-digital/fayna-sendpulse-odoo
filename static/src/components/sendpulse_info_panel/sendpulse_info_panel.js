/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * SendpulseInfoPanel — бічна панель в Odoo Discuss для SendPulse каналів.
 * Показує дані клієнта: аватар, username, мову, bot-змінні, партнера.
 *
 * Отримує дані через RPC → sendpulse.connect.get_connect_for_channel(channelId)
 */
export class SendpulseInfoPanel extends Component {
    static template = "odoo_chatwoot_connector.SendpulseInfoPanel";
    static props = {
        thread: { type: Object },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            connect: null,
            loading: true,
            error: false,
        });

        onWillStart(async () => {
            await this._loadConnect(this.props.thread.id);
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.thread.id !== this.props.thread.id) {
                await this._loadConnect(nextProps.thread.id);
            }
        });
    }

    async _loadConnect(channelId) {
        if (!channelId) return;
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "sendpulse.connect",
                "get_connect_for_channel",
                [channelId],
            );
            this.state.connect = data || null;
        } catch (e) {
            this.state.error = true;
            console.error("SendpulseInfoPanel: failed to load connect", e);
        } finally {
            this.state.loading = false;
        }
    }

    async onRefreshClick() {
        if (!this.state.connect) return;
        try {
            await this.orm.call(
                "sendpulse.connect",
                "action_fetch_contact_info",
                [[this.state.connect.id]],
            );
            // Перезавантажуємо дані після синхронізації
            await this._loadConnect(this.props.thread.id);
        } catch (e) {
            console.error("SendpulseInfoPanel: refresh failed", e);
        }
    }

    async onOpenFormClick() {
        if (!this.state.connect) return;
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sendpulse.connect",
            res_id: this.state.connect.id,
            views: [[false, "form"]],
            target: "new",
        });
    }

    get serviceIcon() {
        const icons = {
            telegram: "✈️",
            instagram: "📸",
            facebook: "👍",
            messenger: "💬",
            viber: "📳",
            whatsapp: "🟢",
            tiktok: "🎵",
            livechat: "🌐",
        };
        return icons[this.state.connect?.service] ?? "💬";
    }

    get statusBadgeClass() {
        const classes = {
            active: "badge text-bg-success",
            unsubscribed: "badge text-bg-secondary",
            deleted: "badge text-bg-danger",
            unconfirmed: "badge text-bg-warning",
        };
        return classes[this.state.connect?.subscription_status] ?? "badge text-bg-light";
    }
}
