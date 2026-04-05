/** @odoo-module **/
/**
 * Реєструє SendPulse Info Panel як дію в threadActionsRegistry.
 *
 * Правильний API Odoo 17 (mail.thread/actions):
 *  - `component` (не `Panel`)
 *  - `toggle: true` для перемикача
 *  - `componentProps(action, component)` для передачі пропсів
 *  - import через registry.category("mail.thread/actions")
 */
import { registry } from "@web/core/registry";
import { SendpulseInfoPanel } from "./components/sendpulse_info_panel/sendpulse_info_panel";
import { _t } from "@web/core/l10n/translation";

const threadActionsRegistry = registry.category("mail.thread/actions");

/** Префікси SendPulse-каналів що генеруються _get_service_label() */
const SP_CHANNEL_PREFIXES = ["[TG] ", "[IG] ", "[FB] ", "[MSG] ", "[VB] ", "[WA] ", "[TT] ", "[LC] "];

function isSendpulseChannel(thread) {
    if (!thread) return false;
    // По полю з Thread model (patch у thread_patch.js + _to_store на Python)
    if (thread.sendpulseConnectId) return true;
    // Fallback: по префіксу назви каналу
    const name = thread.name || "";
    return SP_CHANNEL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

threadActionsRegistry.add("sendpulse-client-info", {
    component: SendpulseInfoPanel,

    condition(component) {
        const thread = component.thread;
        return thread?.model === "discuss.channel" && isSendpulseChannel(thread);
    },

    componentProps(_action, component) {
        return { thread: component.thread };
    },

    panelOuterClass: "o-sendpulse-InfoPanel",
    icon: "fa fa-fw fa-user-circle-o",
    iconLarge: "fa-lg fa-user-circle-o",
    name: _t("Клієнт SendPulse"),
    nameActive: _t("Закрити"),
    sequence: 30,
    toggle: true,
});
