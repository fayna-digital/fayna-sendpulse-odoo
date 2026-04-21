/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";

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
        this.notification = useService("notification");
        this.state = useState({
            connect: null,
            loading: true,
            error: false,
            suggestions: [],
            suggestLoading: false,
            suggestError: false,
            copiedIdx: null,
            translatedText: "",
            translateSourceLang: "",
            translateLoading: false,
            translateError: "",
            translateCopied: false,
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

    /**
     * F10: Request 3 AI-drafted reply suggestions з Claude через backend RPC.
     * Не викликається автоматично — треба клікнути «Згенерувати».
     */
    async onSuggestReply() {
        if (!this.props.thread?.id) return;
        this.state.suggestLoading = true;
        this.state.suggestError = false;
        this.state.suggestions = [];
        try {
            const result = await this.orm.call(
                "sendpulse.connect",
                "suggested_reply_for_channel",
                [this.props.thread.id, 3],
            );
            this.state.suggestions = Array.isArray(result) ? result : [];
            if (this.state.suggestions.length === 0) {
                this.state.suggestError = true;
            }
        } catch (e) {
            console.error("SendpulseInfoPanel: suggest reply failed", e);
            this.state.suggestError = true;
        } finally {
            this.state.suggestLoading = false;
        }
    }

    /**
     * F11: Перекласти останнє вхідне повідомлення клієнта на target_lang.
     */
    async onTranslate(targetLang) {
        if (!this.props.thread?.id) return;
        this.state.translateLoading = true;
        this.state.translateError = "";
        this.state.translatedText = "";
        this.state.translateSourceLang = "";
        this.state.translateCopied = false;
        try {
            const result = await this.orm.call(
                "sendpulse.connect",
                "translate_last_inbound_for_channel",
                [this.props.thread.id, targetLang],
            );
            if (result?.error) {
                const errMap = {
                    disabled: "Переклад вимкнено у Settings",
                    no_api_key: "Anthropic API key не налаштовано",
                    no_inbound: "Немає вхідних повідомлень",
                    no_connect: "Контакт не знайдено",
                    parse_failed: "Не вдалось розібрати відповідь LLM",
                };
                this.state.translateError = errMap[result.error] || result.error;
                return;
            }
            this.state.translatedText = result?.translated || "";
            this.state.translateSourceLang = result?.source_lang || "";
            if (!this.state.translatedText) {
                this.state.translateError = "Порожня відповідь";
            }
        } catch (e) {
            console.error("SendpulseInfoPanel: translate failed", e);
            this.state.translateError = "Помилка RPC";
        } finally {
            this.state.translateLoading = false;
        }
    }

    async onCopyTranslation() {
        const text = this.state.translatedText;
        if (!text) return;
        try {
            await browser.navigator.clipboard.writeText(text);
            this.state.translateCopied = true;
            this.notification.add("Переклад скопійовано — вставляйте у композер (Cmd+V)", {
                type: "success",
            });
            setTimeout(() => {
                this.state.translateCopied = false;
            }, 2500);
        } catch (e) {
            console.error("SendpulseInfoPanel: clipboard (translate) failed", e);
            this.notification.add("Не вдалось скопіювати", { type: "danger" });
        }
    }

    /**
     * Копіює варіант у clipboard. Показує notification що скопійовано.
     */
    async onCopySuggestion(idx) {
        const text = this.state.suggestions[idx];
        if (!text) return;
        try {
            await browser.navigator.clipboard.writeText(text);
            this.state.copiedIdx = idx;
            this.notification.add("Варіант скопійовано — вставляйте у композер (Cmd+V)", {
                type: "success",
                sticky: false,
            });
            setTimeout(() => {
                if (this.state.copiedIdx === idx) {
                    this.state.copiedIdx = null;
                }
            }, 2500);
        } catch (e) {
            console.error("SendpulseInfoPanel: clipboard write failed", e);
            this.notification.add("Не вдалось скопіювати — скопіюйте вручну", {
                type: "danger",
            });
        }
    }
}
