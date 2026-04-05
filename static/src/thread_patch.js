/** @odoo-module **/
/**
 * Патч Thread моделі — додає поле sendpulseConnectId.
 * Поле встановлюється з даних каналу (discuss.channel._to_store includesit).
 *
 * Використовується в sendpulse_thread_actions.js для умовного показу панелі.
 */
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    /** @type {number|false} */
    sendpulseConnectId: false,

    /**
     * @override
     * Обробляємо sendpulse_connect_id з серверних даних каналу.
     */
    update(data) {
        super.update(data);
        if ("sendpulse_connect_id" in data) {
            this.sendpulseConnectId = data.sendpulse_connect_id || false;
        }
    },
});
