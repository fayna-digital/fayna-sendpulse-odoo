#!/usr/bin/env python3
"""UX-аудит Лінза V — прохід по реальних екранах модуля fayna_channel_bridge
з фіксацією скріншотів кожного екрана."""

import os

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
LOGIN = 'admin'
PASSWORD = 'admin'
SHOTS = os.path.join(os.path.dirname(__file__), 'screenshots')
os.makedirs(SHOTS, exist_ok=True)

# Дії модуля (з БД ir_ui_menu / ir.actions.act_window)
ACTION_CONVERSATIONS = 139
ACTION_JOURNAL = 137
ACTION_CHANNELS = 140
ACTION_CONNECT = 141


def shot(page, name):
    path = os.path.join(SHOTS, f'{name}.png')
    page.screenshot(path=path, full_page=False)
    print(f'  [shot] {name}.png')


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)

        # --- Логін ---
        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_timeout(4000)
        print('Logged in:', page.url)
        shot(page, '01_login_discuss')

        # --- Відкрити апп-світчер (Home Menu) ---
        home = page.query_selector('[title="Home Menu"]')
        if home:
            home.click()
            page.wait_for_timeout(2500)
        shot(page, '02_apps_switcher')

        # --- Клік по Channel Bridge ---
        cb = page.query_selector(
            '[data-menu-xmlid="fayna_channel_bridge.menu_channel_bridge_root"]'
        )
        if cb:
            cb.click()
            page.wait_for_timeout(3500)
            print('After Channel Bridge click:', page.url)
        shot(page, '03_channel_bridge_landing')

        # --- Connect channels (галерея) ---
        page.goto(f'{BASE}/web#action={ACTION_CONNECT}', wait_until='domcontentloaded')
        page.wait_for_timeout(3500)
        print('Connect channels:', page.url)
        shot(page, '04_connect_channels_gallery')

        # --- Порахувати картки провайдерів ---
        cards = page.query_selector_all('.o_kanban_record')
        print(f'  provider cards: {len(cards)}')
        for i, c in enumerate(cards):
            try:
                txt = c.inner_text()[:80].replace('\n', ' | ')
                print(f'    card[{i}]: {txt}')
            except Exception:
                pass

        # --- Форма провайдера (клік по картці) ---
        if cards:
            try:
                cards[0].click()
                page.wait_for_timeout(3000)
                print('Provider form:', page.url)
                shot(page, '05_provider_form')
            except Exception as e:
                print('  provider form click err:', e)

        # --- Назад до галереї ---
        page.goto(f'{BASE}/web#action={ACTION_CONNECT}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

        # --- Conversations list ---
        page.goto(f'{BASE}/web#action={ACTION_CONVERSATIONS}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        print('Conversations:', page.url)
        shot(page, '06_conversations_list')

        # --- Journal list ---
        page.goto(f'{BASE}/web#action={ACTION_JOURNAL}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        print('Journal:', page.url)
        shot(page, '07_journal_list')

        # --- Channels list ---
        page.goto(f'{BASE}/web#action={ACTION_CHANNELS}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        print('Channels:', page.url)
        shot(page, '08_channels_list')

        browser.close()
        print('\nDone.')


if __name__ == '__main__':
    main()
