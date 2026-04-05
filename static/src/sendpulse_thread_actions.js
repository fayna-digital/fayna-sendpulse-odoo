/** @odoo-module **/
/**
 * Реєструє SendPulse Info Panel як дію (кнопка + панель) у ThreadView.
 *
 * Відображається тільки для SendPulse каналів — визначаємо по префіксу назви
 * ([TG], [IG], [FB], [MSG], [VB], [WA], [TT], [LC]) або по sendpulseConnectId.
 */
import { threadActionsRegistry } from "@mail/core/common/thread_actions";
import { SendpulseInfoPanel } from "./components/sendpulse_info_panel/sendpulse_info_panel";

/** Префікси назв каналів що генеруються нашим модулем у _get_service_label() */
const SP_CHANNEL_PREFIXES = ["[TG] ", "[IG] ", "[FB] ", "[MSG] ", "[VB] ", "[WA] ", "[TT] ", "[LC] "];

function isSendpulseThread(thread) {
    if (!thread) return false;
    // Перевіряємо по полю sendpulseConnectId (якщо _to_store/Thread.update спрацювали)
    if (thread.sendpulseConnectId) return true;
    // Fallback: перевіряємо по назві каналу
    if (thread.type === "channel" || thread.channel_type === "group") {
        const name = thread.name || "";
        return SP_CHANNEL_PREFIXES.some((prefix) => name.startsWith(prefix));
    }
    return false;
}

threadActionsRegistry.add("sendpulse-client-info", {
    condition: (component) => isSendpulseThread(component.thread),
    icon: "fa fa-user-circle-o",
    iconLarge: "fa-lg fa-user-circle-o",
    id: "sendpulse-client-info",
    label: "Клієнт SendPulse",
    name: "Клієнт",
    Panel: SendpulseInfoPanel,
    sequence: 30,
});
