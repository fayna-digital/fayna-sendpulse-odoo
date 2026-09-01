/* @odoo-module */

import { Component, onWillStart, useState } from "@odoo/owl";

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * OWL-SPA «Підключити канали» (ТЗ_OMNI_DASHBOARD_OWL.md, Фаза 1).
 *
 * Патерн — Master-Detail, як у Discuss (addons/mail/static/src/core/web/
 * discuss_client_action.js): OWL client action, ліворуч список каналів,
 * праворуч контент, перемикання без перезавантаження сторінки.
 *
 * Джерело даних — `channel.provider` через один RPC `get_dashboard_data()`
 * на відкриття екрана (ТЗ §2.3). Захардкодженим у JS лишається ТІЛЬКИ
 * порядок груп лівої панелі («Основні» / «Інтеграції з маркетплейсу»).
 *
 * Заборони (ТЗ §2.5, UX-14): жодного токена/секрету/ідентифікатора
 * вебхука/URL вебхука на екрані; жодного порожнього блоку з підписом;
 * жодного службового поля; руйнівна дія «Від'єднати» окремо, з
 * підтвердженням; стан не суперечить дії; одна мова на екрані.
 */

// Порядок категорій лівої панелі (ТЗ §2.3, §2.3-bis): склад категорій — з
// даних (поле `category`), порядок — тут.
const CATEGORY_ORDER = ["main", "marketplace"];

// Позначки стану (ТЗ §0.1): три чесні стани, джерело правди —
// last_healthcheck_ok + last_error у channel.backend.
const STATE_BADGE = {
    not_configured: { class: "o-fcb-state-not-configured", label: "Not configured" },
    needs_attention: { class: "o-fcb-state-needs-attention", label: "Needs attention" },
    working: { class: "o-fcb-state-working", label: "Working" },
};

export class ChannelDashboard extends Component {
    static template = "fayna_channel_bridge.ChannelDashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialogService = useService("dialog");
        this.notificationService = useService("notification");
        this.state = useState({
            loading: true,
            providers: [],
            activeId: null,
        });
        onWillStart(async () => {
            await this._load();
        });
    }

    /**
     * Один RPC на відкриття екрана (ТЗ §2.3). Ліва панель і вміст правої
     * беруться з `channel.provider`.
     */
    async _load() {
        this.state.loading = true;
        try {
            const providers = await this.orm.call(
                "channel.provider",
                "get_dashboard_data",
                []
            );
            this.state.providers = providers;
            // Активний канал за замовчуванням — перший у порядку груп.
            const first = this._orderedProviders()[0];
            this.state.activeId = first ? first.id : null;
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * Канали, згруповані за полем `category`, у порядку CATEGORY_ORDER.
     * Склад категорій — з даних, порядок категорій — тут (ТЗ §2.3).
     */
    _groupedProviders() {
        const groups = {};
        for (const category of CATEGORY_ORDER) {
            groups[category] = [];
        }
        for (const provider of this.state.providers) {
            const key = CATEGORY_ORDER.includes(provider.category)
                ? provider.category
                : "main";
            groups[key].push(provider);
        }
        return groups;
    }

    _orderedProviders() {
        const groups = this._groupedProviders();
        return CATEGORY_ORDER.flatMap((category) => groups[category] || []);
    }

    get activeProvider() {
        return this.state.providers.find((p) => p.id === this.state.activeId) || null;
    }

    get categoryOrder() {
        return CATEGORY_ORDER;
    }

    get categoryLabels() {
        return {
            main: this.env._t("Main"),
            marketplace: this.env._t("Marketplace integrations"),
        };
    }

    _stateBadge(state) {
        return STATE_BADGE[state] || STATE_BADGE.not_configured;
    }

    /**
     * Головна кнопка за `connect_method` (ТЗ §2.4, §2.3-bis):
     * - oauth    → RPC у Python по URL авторизації → редирект window.location.href;
     * - token    → відкрити наявний wizard channel.connect.wizard;
     * - widget / settings → показати інструкцію або відкрити налаштування;
     * - native   → це вміє сам Odoo (Email/SMS) — відкрити налаштування Odoo;
     * - external → маркетплейс — ведемо посиланням назовні («Перейти»).
     */
    async onClickConnect() {
        const provider = this.activeProvider;
        if (!provider) {
            return;
        }
        if (provider.has_unconfirmed_preconditions) {
            this.notificationService.add(
                provider.blocking_reason || this.env._t("Preconditions are not confirmed."),
                { type: "danger" }
            );
            return;
        }
        if (provider.connect_method === "token") {
            await this.actionService.doAction({
                name: this.env._t("Connect %s", provider.name),
                type: "ir.actions.act_window",
                res_model: "channel.connect.wizard",
                view_mode: "form",
                target: "new",
                context: { default_provider_id: provider.id },
            });
            return;
        }
        if (provider.connect_method === "oauth") {
            // Фаза 2: RPC повертає URL авторизації Meta. Поки що — чесна відмова.
            try {
                const url = await this.orm.call(
                    "channel.provider",
                    "get_oauth_url",
                    [provider.id]
                );
                if (url) {
                    window.location.href = url;
                }
            } catch (error) {
                this.notificationService.add(error.message, { type: "danger" });
            }
            return;
        }
        if (provider.connect_method === "external") {
            // Маркетплейс: кнопка «Перейти» веде посиланням назовні.
            if (provider.fallback_url) {
                window.open(provider.fallback_url, "_blank");
            }
            return;
        }
        if (provider.connect_method === "native") {
            // Це вміє сам Odoo (Email/SMS) — ведемо в його налаштування.
            this.notificationService.add(
                this.env._t(
                    "Channel %s is handled natively by Odoo — configure it in the Odoo settings.",
                    provider.name
                ),
                { type: "info" }
            );
            return;
        }
        // widget / settings — інструкція або налаштування.
        this.notificationService.add(
            this.env._t(
                "Channel %s does not require connecting — just embed the widget or configure it in Odoo settings.",
                provider.name
            ),
            { type: "info" }
        );
    }

    /**
     * Руйнівна дія «Від'єднати» — окремо від головної, з підтвердженням
     * (ТЗ §2.5). Викликає серверну дію `action_disconnect` (архівація).
     */
    async onClickDisconnect() {
        const provider = this.activeProvider;
        if (!provider) {
            return;
        }
        const confirmed = await this.dialogService.confirm(
            this.env._t("Disconnect %s?", provider.name),
            this.env._t(
                "This channel will be disconnected and messages will stop flowing. You can reconnect it later."
            )
        );
        if (!confirmed) {
            return;
        }
        await this.orm.call("channel.provider", "action_disconnect", [provider.id]);
        this.notificationService.add(
            this.env._t("%s has been disconnected.", provider.name),
            { type: "success" }
        );
        await this._load();
    }

    /**
     * Відкрити штатний застосунок Odoo Live Chat (im_livechat) — замість
     * пункту меню (ТЗ §2.2). Онлайн-чат у список каналів НЕ додаємо.
     */
    async onClickLiveChat() {
        await this.actionService.doAction("im_livechat.im_livechat_action");
    }
}

registry.category("actions").add(
    "fayna_channel_bridge.channel_dashboard",
    ChannelDashboard
);
