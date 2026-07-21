/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/** UX-аудит 21.07.2026: мінімальна довжина цифр телефону, щоб вважати prefill валідним
 *  (лише проти явно биткого значення типу "901" — не повноцінна валідація формату). */
const MIN_PHONE_DIGITS = 9;

/** Код мови → людська назва для підпису біля ISO-коду в панелі. */
const LANGUAGE_LABELS = {
    uk: "Українська",
    pl: "Polski",
    en: "English",
    ru: "Русский",
    de: "Deutsch",
};

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
        this.dialog = useService("dialog");
        this.state = useState({
            connect: null,
            loading: true,
            error: false,
            refreshLoading: false,
            suggestions: [],
            suggestLoading: false,
            suggestError: false,
            copiedIdx: null,
            translatedText: "",
            translateSourceLang: "",
            translateLoading: false,
            translateError: "",
            translateCopied: false,
            // F13 lead-magnet
            pdfEmail: "",
            pdfLoading: false,
            pdfError: "",
            smsPhone: "",
            smsLoading: false,
            smsError: "",
            smsSuccess: null,
            unarchiveLoading: false,
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
            // F13: prefill email/phone — телефон лише якщо схожий на реальний
            // (UX-аудит 21.07.2026: явно биті значення типу "901" раніше
            // префілились і давали натиснути "Надіслати" не дивлячись).
            if (data) {
                this.state.pdfEmail = data.prefill_email || "";
                const digits = (data.prefill_phone || "").replace(/\D/g, "");
                this.state.smsPhone = digits.length >= MIN_PHONE_DIGITS ? data.prefill_phone : "";
            }
        } catch (e) {
            this.state.error = true;
            console.error("SendpulseInfoPanel: failed to load connect", e);
        } finally {
            this.state.loading = false;
        }
    }

    /**
     * F13: Надіслати PDF-каталог на email клієнта.
     * UX-аудит 21.07.2026: реальний зовнішній send — питаємо підтвердження,
     * бо помилковий клік не можна скасувати (лист уже пішов клієнту).
     */
    async onSendPdf() {
        if (!this.props.thread?.id || !this.state.pdfEmail) return;
        const email = this.state.pdfEmail;
        this.dialog.add(ConfirmationDialog, {
            title: "Надіслати PDF-каталог?",
            body: `Клієнту реально піде email на ${email}. Продовжити?`,
            confirmLabel: "Так, надіслати",
            cancelLabel: "Скасувати",
            confirm: () => this._doSendPdf(email),
        });
    }

    async _doSendPdf(email) {
        this.state.pdfLoading = true;
        this.state.pdfError = "";
        try {
            const result = await this.orm.call(
                "sendpulse.connect",
                "send_pdf_catalog_for_channel",
                [this.props.thread.id, email],
            );
            if (!result || !result.ok) {
                const errMap = {
                    disabled: "Lead magnet вимкнено у Settings",
                    no_email: "Email порожній",
                    no_attachment_configured: "PDF-файл не налаштовано у Settings",
                    attachment_missing: "PDF-файл не знайдено у filestore",
                    already_sent: "Уже надіслано на цей email",
                    no_connect: "Контакт не знайдено",
                };
                this.state.pdfError = errMap[result?.error] || "Сталася помилка, спробуйте пізніше";
                return;
            }
            this.notification.add("PDF-каталог надіслано на " + email, {
                type: "success",
            });
            await this._loadConnect(this.props.thread.id);
        } catch (e) {
            console.error("SendpulseInfoPanel: send PDF failed", e);
            this.state.pdfError = "Помилка RPC";
        } finally {
            this.state.pdfLoading = false;
        }
    }

    /** Груба перевірка, що в полі не явний сміттєвий ввід типу "901". */
    get smsPhoneValid() {
        return this.state.smsPhone.replace(/\D/g, "").length >= MIN_PHONE_DIGITS;
    }

    /**
     * F13: Надіслати SMS-купон 5% на телефон клієнта.
     * UX-аудит 21.07.2026: обмежений пул купонів + реальний зовнішній send —
     * питаємо підтвердження перед відправкою.
     */
    async onSendSmsCoupon() {
        if (!this.props.thread?.id || !this.state.smsPhone || !this.smsPhoneValid) return;
        const phone = this.state.smsPhone;
        this.dialog.add(ConfirmationDialog, {
            title: "Надіслати SMS-купон?",
            body: `Клієнту реально піде SMS з купоном на ${phone}, купон буде списано з пулу. Продовжити?`,
            confirmLabel: "Так, надіслати",
            cancelLabel: "Скасувати",
            confirm: () => this._doSendSmsCoupon(phone),
        });
    }

    async _doSendSmsCoupon(phone) {
        this.state.smsLoading = true;
        this.state.smsError = "";
        this.state.smsSuccess = null;
        try {
            const result = await this.orm.call(
                "sendpulse.connect",
                "send_sms_coupon_for_channel",
                [this.props.thread.id, phone],
            );
            if (!result || !result.ok) {
                const errMap = {
                    disabled: "Lead magnet вимкнено у Settings",
                    no_phone: "Телефон порожній",
                    no_program_configured: "Loyalty-програма не налаштована",
                    program_missing: "Loyalty-програма не знайдена",
                    coupon_exhausted: "Купони у програмі закінчились (points=0)",
                    already_sent: "Уже надіслано купон цьому клієнту",
                    no_connect: "Контакт не знайдено",
                };
                this.state.smsError = errMap[result?.error] || "Сталася помилка, спробуйте пізніше";
                return;
            }
            this.state.smsSuccess = {
                code: result.code,
                remaining: result.remaining,
            };
            this.notification.add(
                `SMS-купон ${result.code} надіслано на ${phone}`,
                { type: "success" }
            );
            await this._loadConnect(this.props.thread.id);
        } catch (e) {
            console.error("SendpulseInfoPanel: send SMS coupon failed", e);
            this.state.smsError = "Помилка RPC";
        } finally {
            this.state.smsLoading = false;
        }
    }

    async onRefreshClick() {
        if (!this.state.connect) return;
        this.state.refreshLoading = true;
        try {
            await this.orm.call(
                "sendpulse.connect",
                "action_fetch_contact_info",
                [[this.state.connect.id]],
            );
            // Перезавантажуємо дані після синхронізації
            await this._loadConnect(this.props.thread.id);
            this.notification.add("Профіль оновлено", { type: "success" });
        } catch (e) {
            console.error("SendpulseInfoPanel: refresh failed", e);
            this.notification.add("Не вдалося оновити профіль", { type: "danger" });
        } finally {
            this.state.refreshLoading = false;
        }
    }

    async onUnarchivePartner() {
        if (!this.props.thread?.id) return;
        this.state.unarchiveLoading = true;
        try {
            const result = await this.orm.call(
                "sendpulse.connect",
                "unarchive_partner_for_channel",
                [this.props.thread.id],
            );
            if (result?.ok) {
                this.notification.add(
                    result.already_active
                        ? "Контакт вже активний"
                        : `Розархівовано: ${result.partner_name || "контакт"}`,
                    { type: "success" }
                );
                await this._loadConnect(this.props.thread.id);
            } else {
                this.notification.add("Не вдалося розархівувати", { type: "danger" });
            }
        } catch (e) {
            console.error("SendpulseInfoPanel: unarchive failed", e);
            this.notification.add("Помилка RPC", { type: "danger" });
        } finally {
            this.state.unarchiveLoading = false;
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

    /** UX-аудит 21.07.2026: кнопка "Спробувати ще раз" на екрані помилки завантаження. */
    async onRetryLoad() {
        await this._loadConnect(this.props.thread.id);
    }

    get languageLabel() {
        const code = this.state.connect?.language_code;
        if (!code) return "";
        return LANGUAGE_LABELS[code] || code;
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
