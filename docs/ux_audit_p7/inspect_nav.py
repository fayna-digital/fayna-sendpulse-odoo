#!/usr/bin/env python3
"""Дамп верхньої навігації Odoo 17 — знайти правильний селектор апп-світчера."""

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
LOGIN = 'admin'
PASSWORD = 'admin'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(20000)

        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_timeout(4000)
        print('URL:', page.url)

        # Дамп усіх клікабельних елементів у верхній панелі
        print('\n--- top navbar buttons ---')
        for el in page.query_selector_all('header button, header a, .o_web_client > header *'):
            try:
                txt = el.inner_text()[:40].replace('\n', ' | ')
                cls = el.get_attribute('class') or ''
                title = el.get_attribute('title') or ''
                if txt.strip() or title:
                    print(f"  BTN: '{txt}' class='{cls}' title='{title}'")
            except Exception:
                pass

        # Знайти всі елементи з class, що містять 'menu' або 'app'
        print("\n--- elements with 'menu'/'app' in class ---")
        for el in page.query_selector_all("[class*='menu'], [class*='app']"):
            try:
                cls = el.get_attribute('class') or ''
                txt = el.inner_text()[:40].replace('\n', ' | ')
                if txt.strip():
                    print(f"  EL: '{txt}' class='{cls}'")
            except Exception:
                pass

        browser.close()


if __name__ == '__main__':
    main()
