#!/usr/bin/env python3
"""Точна інспекція галереї провайдерів — чи є порожні картки."""

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
        page.wait_for_timeout(3500)

        # Дамп усіх .o_kanban_record з деталями
        print('--- kanban records ---')
        for i, el in enumerate(page.query_selector_all('.o_kanban_record')):
            try:
                txt = el.inner_text()[:60].replace('\n', ' | ')
                cls = el.get_attribute('class')
                has_title = bool(el.query_selector('.o_kanban_record_title'))
                print(f"  [{i}] has_title={has_title} txt='{txt}' class='{cls}'")
            except Exception as e:
                print(f'  [{i}] err {e}')

        # Дамп усіх елементів з класом o_kanban (включно з placeholder)
        print('\n--- .o_kanban_record elements count ---')
        print(len(page.query_selector_all('.o_kanban_record')))

        # Перевірити чи є "create" placeholder
        print('\n--- create placeholder / quick create ---')
        for el in page.query_selector_all(
            '.o_kanban_quick_create, .o_kanban_record_quick_create, .o_kanban_ghost'
        ):
            try:
                print('  ghost:', el.inner_text()[:40], el.get_attribute('class'))
            except Exception:
                pass

        browser.close()


if __name__ == '__main__':
    main()
