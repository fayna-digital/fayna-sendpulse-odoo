#!/usr/bin/env python3
"""UX-аудит Лінза V — інтерактивні флоу: wizard, oauth, блокери, empty states.

Поведінка wizard (з'ясовано інспекцією):
- Порожнє поле token (required) → валідація на клієнті: червона підсвітка поля,
  wizard лишається відкритим, ЖОДНОГО окремого модала помилки.
- Невалідний token → action_connect() → register_telegram_webhook() падає →
  UserError → з'являється окремий діалог помилки з кнопкою "Ok".
- Кнопка Cancel закриває wizard.
"""

import os

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
LOGIN = 'admin'
PASSWORD = 'admin'
SHOTS = os.path.join(os.path.dirname(__file__), 'screenshots')
os.makedirs(SHOTS, exist_ok=True)

ACTION_CONNECT = 141


def shot(page, name):
    path = os.path.join(SHOTS, f'{name}.png')
    page.screenshot(path=path, full_page=False)
    print(f'  [shot] {name}.png')


def dismiss_error_dialog(page):
    """Закрити діалог помилки UserError. Повертає True, якщо був.

    Діалог помилки Odoo — окремий .modal поверх wizard (wizard стає
    o_inactive_modal). Кнопка закриття — 'Ok' АБО 'Close' (з'ясовано
    інспекцією: 'Invalid Operation' → кнопка 'Close').
    """
    try:
        # Діалог помилки — останній активний .modal (не o_inactive_modal)
        for m in page.query_selector_all('.modal'):
            try:
                if not m.is_visible():
                    continue
                cls = m.get_attribute('class') or ''
                if 'o_inactive_modal' in cls:
                    continue
                ok = m.query_selector('button:has-text("Ok"), button:has-text("Close")')
                if ok and ok.is_visible():
                    ok.click()
                    page.wait_for_timeout(1500)
                    print(f"  [dialog] error dialog dismissed ('{ok.inner_text().strip()}')")
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def wizard_token_input(page):
    """Поле token у wizard: password-input без name (з'ясовано інспекцією)."""
    modal = page.query_selector('.modal')
    if not modal:
        return None
    return modal.query_selector('input[type="password"]')


def check_precondition(page, field_name):
    """Позначити checkbox передумови за id (Odoo рендерить id='<field>_0',
    без name-атрибута). Повертає True, якщо знайдено і позначено."""
    try:
        cb = page.query_selector(f"input[type='checkbox'][id^='{field_name}']")
        if cb and cb.is_visible():
            cb.check()
            page.wait_for_timeout(1500)
            print(f"  [precondition] checked '{field_name}'")
            return True
    except Exception as e:
        print(f'  [precondition] error: {e}')
    print(f"  [precondition] checkbox for '{field_name}' NOT found")
    return False


def login(page):
    page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    page.fill('input[name="login"]', LOGIN)
    page.fill('input[name="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_timeout(4000)


def open_gallery(page):
    # Явно запитуємо kanban-галерею: після перегляду форми Odoo тримає
    # view_type=form у hash, тому #action=141 лишає форму. Примусово скидаємо.
    page.goto(
        f'{BASE}/web#action={ACTION_CONNECT}&model=channel.provider&view_type=kanban',
        wait_until='domcontentloaded',
    )
    page.wait_for_timeout(3000)


def get_cards(page):
    return page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)')


def find_card(page, name):
    for c in get_cards(page):
        if name in c.inner_text():
            return c
    return None


def open_provider_form(page, name):
    """Відкрити форму провайдера з галереї. Повертає картку або None."""
    open_gallery(page)
    card = find_card(page, name)
    if not card:
        # Повторна спроба: повне перезавантаження сторінки
        print(f"  [nav] card '{name}' not found on first try, reloading...")
        page.reload(wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        card = find_card(page, name)
    if card:
        card.click()
        page.wait_for_timeout(2500)
    else:
        print(f"  [nav] card '{name}' STILL not found after reload")
    return card


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)
        login(page)

        # ── 1. Галерея ──
        open_gallery(page)
        print(f'Real provider cards: {len(get_cards(page))}')

        # ── 2. Telegram (token) wizard ──
        if open_provider_form(page, 'Telegram'):
            shot(page, '10_telegram_provider_form')
            btn = page.query_selector('button:has-text("Connect")')
            if btn:
                btn.click()
                page.wait_for_timeout(2500)
                shot(page, '11_connect_wizard_empty')

                # 2a. Submit з порожнім полем → валідація required (без модала)
                conn = page.query_selector('.modal button:has-text("Connect")')
                if conn:
                    conn.click()
                    page.wait_for_timeout(2500)
                    shot(page, '12_connect_wizard_empty_submit')
                    # Перевірити, чи з'явилась підсвітка required
                    token_input = wizard_token_input(page)
                    if token_input:
                        cls = token_input.get_attribute('class') or ''
                        has_err = 'invalid' in cls or 'o_field_invalid' in cls
                        print(
                            f"  [wizard] empty submit: token field class='{cls}' "
                            f'required-error={has_err}'
                        )
                    # Odoo показує клієнтську валідацію (o_notification), не діалог
                    notif = page.query_selector('.o_notification')
                    if notif:
                        print(f"  [wizard] empty submit: notification='{notif.inner_text()[:60]}'")
                    # Жодного окремого діалогу помилки бути не повинно
                    if not dismiss_error_dialog(page):
                        print('  [wizard] empty submit: no error dialog (expected)')

                # 2b. Невалідний ключ → UserError → діалог помилки
                token_input = wizard_token_input(page)
                if token_input:
                    token_input.fill('invalid-token-123')
                    conn = page.query_selector('.modal button:has-text("Connect")')
                    if conn:
                        conn.click()
                        page.wait_for_timeout(4000)
                        shot(page, '13_connect_wizard_invalid')
                        # З'явився діалог помилки з Ok
                        if dismiss_error_dialog(page):
                            print('  [wizard] invalid token: error dialog shown (expected)')
                        else:
                            print('  [wizard] invalid token: NO error dialog (check!)')

                # 2c. Скасувати wizard
                cancel = page.query_selector('.modal button:has-text("Cancel")')
                if cancel:
                    cancel.click()
                    page.wait_for_timeout(2000)
                    print('  [wizard] cancelled')

        # ── 3. OAuth Messenger ──
        if open_provider_form(page, 'Messenger'):
            shot(page, '14_messenger_provider_form')
            btn = page.query_selector('button:has-text("Connect")')
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
                shot(page, '15_messenger_oauth_message')
                if dismiss_error_dialog(page):
                    print('  [oauth] Messenger: manual-by-admin message shown (expected)')
                else:
                    print('  [oauth] Messenger: NO message (check!)')

        # ── 4. TikTok blocker (region_blocklist) ──
        # Connect прихований (invisible=has_unconfirmed_preconditions), поки не
        # підтверджено region_confirmed. Спершу показуємо блокер, потім
        # підтверджуємо передумову → з'являється Connect.
        if open_provider_form(page, 'TikTok'):
            shot(page, '16_tiktok_blocked_form')
            # Блокер видимий, Connect прихований
            alert = page.query_selector('.alert-danger')
            btn = page.query_selector('button:has-text("Connect")')
            print(
                f'  [blocker] TikTok: blocking alert present={bool(alert)}, '
                f'connect btn visible={bool(btn)}'
            )
            # Підтвердити передумову region_confirmed (checkbox без name)
            if check_precondition(page, 'region_confirmed'):
                shot(page, '17_tiktok_confirmed')
                btn = page.query_selector('button:has-text("Connect")')
                if btn:
                    btn.click()
                    page.wait_for_timeout(3000)
                    shot(page, '17b_tiktok_connect')
                    if dismiss_error_dialog(page):
                        print('  [blocker] TikTok: connect message shown (expected)')
                    else:
                        print('  [blocker] TikTok: NO message (check!)')
            else:
                print('  [blocker] TikTok: region_confirmed checkbox NOT found (check!)')

        # ── 5. WhatsApp (consent_required + cost + side_effect) ──
        if open_provider_form(page, 'WhatsApp'):
            shot(page, '18_whatsapp_form')
            alert = page.query_selector('.alert-danger')
            btn = page.query_selector('button:has-text("Connect")')
            print(
                f'  [blocker] WhatsApp: blocking alert present={bool(alert)}, '
                f'connect btn visible={bool(btn)}'
            )
            # Підтвердити consent_confirmed (checkbox без name)
            if check_precondition(page, 'consent_confirmed'):
                shot(page, '19_whatsapp_confirmed')
                btn = page.query_selector('button:has-text("Connect")')
                if btn:
                    btn.click()
                    page.wait_for_timeout(3000)
                    shot(page, '19b_whatsapp_connect')
                    if dismiss_error_dialog(page):
                        print('  [blocker] WhatsApp: connect message shown (expected)')
                    else:
                        print('  [blocker] WhatsApp: NO message (check!)')
            else:
                print('  [blocker] WhatsApp: consent_confirmed checkbox NOT found (check!)')

        # ── 6. LiveChat widget ──
        if open_provider_form(page, 'LiveChat'):
            shot(page, '20_livechat_form')
            btn = page.query_selector('button:has-text("Connect")')
            if btn:
                btn.click()
                page.wait_for_timeout(3000)
                shot(page, '21_livechat_widget_message')
                if dismiss_error_dialog(page):
                    print('  [widget] LiveChat: embed-widget message shown (expected)')
                else:
                    print('  [widget] LiveChat: NO message (check!)')

        # ── 7. Успішне підключення (Viber — token-канал без мережі) ──
        # Viber створює channel.backend БЕЗ виклику мережі (на відміну від
        # Telegram, який кличе setWebhook). Тому фейковий ключ Viber дає
        # реальний успішний флоу в UI: wizard закривається, галерея показує
        # «Підключено» і кнопку «Відкрити канал» (кроки 10-12 протоколу).
        if open_provider_form(page, 'Viber'):
            shot(page, '22_viber_provider_form')
            btn = page.query_selector('button:has-text("Connect")')
            if btn:
                btn.click()
                page.wait_for_timeout(2500)
                shot(page, '23_viber_wizard')
                token_input = wizard_token_input(page)
                if token_input:
                    token_input.fill('viber_test_token_123')
                    conn = page.query_selector('.modal button:has-text("Connect")')
                    if conn:
                        conn.click()
                        page.wait_for_timeout(4000)
                        # Успіх → wizard закривається, помилки немає
                        if dismiss_error_dialog(page):
                            print('  [connect] Viber: unexpected error dialog (check!)')
                        else:
                            print('  [connect] Viber: wizard closed (success expected)')
                        # Галерея після підключення — статус «Підключено»
                        open_gallery(page)
                        shot(page, '24_gallery_after_connect')
                        # Знайти картку Viber і перевірити статус/кнопку
                        viber_card = find_card(page, 'Viber')
                        if viber_card:
                            txt = viber_card.inner_text()
                            print(f"  [connect] Viber card text: " f"{' '.join(txt.split())[:120]}")
                            # Кнопка «Відкрити канал»
                            open_btn = viber_card.query_selector(
                                'button:has-text("Open channel"), '
                                'a:has-text("Open channel"), '
                                'button:has-text("Відкрити"), '
                                'a:has-text("Відкрити")'
                            )
                            if open_btn:
                                open_btn.click()
                                page.wait_for_timeout(3000)
                                shot(page, '25_open_channel')
                                print('  [connect] Viber: Open channel clicked')
                            else:
                                print('  [connect] Viber: Open channel btn NOT found (check!)')

        # ── 8. Списки модуля + порожні стани (кроки «плюс решта екранів») ──
        # Після успішного підключення Viber: Conversations/Journal порожні,
        # Channels має 1 запис (Viber). Навігація action-URL з явним view_type
        # (прямі #model=... в Odoo 17 не працюють — лишають у Discuss).
        def open_list(page, action_id, label):
            page.goto(
                f'{BASE}/web#action={action_id}&view_type=list',
                wait_until='domcontentloaded',
            )
            page.wait_for_timeout(3000)
            empty = page.query_selector('.o_view_nocontent')
            rows = page.query_selector_all('.o_data_row')
            print(f'  [list] {label}: empty-state={bool(empty)} rows={len(rows)}')
            return empty, rows

        # Conversations (порожній стан)
        empty, _ = open_list(page, 139, 'Conversations')
        shot(page, '30_conversations_empty')
        # Journal (порожній стан)
        empty, _ = open_list(page, 137, 'Journal')
        shot(page, '31_journal_empty')
        # Channels (має 1 запис — Viber)
        empty, rows = open_list(page, 140, 'Channels')
        shot(page, '32_channels_list')

        browser.close()
        print('\nDone.')


if __name__ == '__main__':
    main()
