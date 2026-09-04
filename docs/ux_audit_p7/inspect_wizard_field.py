#!/usr/bin/env python3
"""Інспекція DOM поля token у wizard — знайти правильний селектор."""

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

        # Дамп усіх input/textarea у модалі
        modal = page.query_selector('.modal')
        print('=== inputs in modal ===')
        for el in modal.query_selector_all('input, textarea, select'):
            try:
                tag = el.evaluate('e => e.tagName')
                name = el.get_attribute('name')
                typ = el.get_attribute('type')
                ph = el.get_attribute('placeholder')
                cls = el.get_attribute('class')
                print(f"  <{tag}> name='{name}' type='{typ}' placeholder='{ph}' class='{cls}'")
            except Exception as e:
                print(f'  err {e}')

        # Дамп тексту модала
        print('\n=== modal text ===')
        print(modal.inner_text()[:400])

        browser.close()


if __name__ == '__main__':
    main()
