#!/usr/bin/env python3
"""Інспекція технічного модала помилки — знайти кнопку закриття."""

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
LOGIN = 'admin'
PASSWORD = 'admin'
ACTION_CONNECT = 141


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)

        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_timeout(4000)

        page.goto(f'{BASE}/web#action={ACTION_CONNECT}', wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

        # Telegram card → form → Connect → wizard
        for c in page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)'):
            if 'Telegram' in c.inner_text():
                c.click()
                page.wait_for_timeout(2500)
                break
        btn = page.query_selector('button:has-text("Connect")')
        if btn:
            btn.click()
            page.wait_for_timeout(2500)

        # Submit empty
        conn = page.query_selector('.modal button:has-text("Connect")')
        if conn:
            conn.click()
            page.wait_for_timeout(3000)

        # Дамп усіх модалів
        print('--- modals ---')
        for i, m in enumerate(page.query_selector_all('.modal')):
            try:
                cls = m.get_attribute('class')
                vis = m.is_visible()
                print(f"  modal[{i}] class='{cls}' visible={vis}")
                # Дамп кнопок у модалі
                for b in m.query_selector_all('button'):
                    try:
                        print(
                            f"    btn: '{b.inner_text()[:30]}' class='{b.get_attribute('class')}'"
                        )
                    except Exception:
                        pass
            except Exception as e:
                print(f'  modal[{i}] err {e}')

        # Дамп тексту модала
        print('\n--- modal text ---')
        for m in page.query_selector_all('.modal'):
            try:
                txt = m.inner_text()[:300]
                print(txt)
            except Exception:
                pass

        browser.close()


if __name__ == '__main__':
    main()
