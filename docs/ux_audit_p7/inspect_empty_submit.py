#!/usr/bin/env python3
"""Діагностика стану після submit з порожнім полем у wizard."""

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
ACTION_CONNECT = 141


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)

        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        page.fill('input[name="login"]', 'admin')
        page.fill('input[name="password"]', 'admin')
        page.click('button[type="submit"]')
        page.wait_for_timeout(4000)

        page.goto(f'{BASE}/web#action={ACTION_CONNECT}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

        for c in page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)'):
            if 'Telegram' in c.inner_text():
                c.click()
                page.wait_for_timeout(2500)
                break
        btn = page.query_selector('button:has-text("Connect")')
        if btn:
            btn.click()
            page.wait_for_timeout(2500)

        print('=== before empty submit ===')
        print('modals:', len(page.query_selector_all('.modal')))
        print('token inputs:', len(page.query_selector_all('input[name="token"]')))

        conn = page.query_selector('.modal button:has-text("Connect")')
        if conn:
            conn.click()
            page.wait_for_timeout(3000)

        print('\n=== after empty submit ===')
        print('modals:', len(page.query_selector_all('.modal')))
        for i, m in enumerate(page.query_selector_all('.modal')):
            try:
                print(f"  modal[{i}] class='{m.get_attribute('class')}' visible={m.is_visible()}")
            except Exception as e:
                print(f'  modal[{i}] err {e}')
        print('token inputs:', len(page.query_selector_all('input[name="token"]')))
        # Чи є підсвітка required?
        for inp in page.query_selector_all('input[name="token"]'):
            print(f"  token class='{inp.get_attribute('class')}'")
        # Чи є повідомлення про помилку валідації?
        for sel in [
            '.o_field_invalid',
            '.text-danger',
            '.invalid-feedback',
            '.o_notification',
        ]:
            els = page.query_selector_all(sel)
            if els:
                print(f'  {sel}: {len(els)}')
                for e in els[:3]:
                    try:
                        print(f"    -> '{e.inner_text()[:80]}'")
                    except Exception:
                        pass

        browser.close()


if __name__ == '__main__':
    main()
