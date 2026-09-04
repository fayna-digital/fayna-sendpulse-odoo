#!/usr/bin/env python3
"""Інспекція DOM чекбоксів передумов — друкує outerHTML батьківських контейнерів."""

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

        page.goto(
            f'{BASE}/web#action={ACTION_CONNECT}&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        for c in page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)'):
            if 'TikTok' in c.inner_text():
                c.click()
                page.wait_for_timeout(2500)
                break

        print('=== ALL checkbox inputs (outerHTML of container) ===')
        for el in page.query_selector_all("input[type='checkbox']"):
            try:
                vis = el.is_visible()
                print(f'\n--- checkbox visible={vis} ---')
                # outerHTML самого чекбокса
                html = el.evaluate('e => e.outerHTML')
                print(f'CHECKBOX: {html}')
                # батьківський контейнер
                parent_html = el.evaluate(
                    "e => e.closest('.o_field_widget, .form-check, .custom-control, "
                    "label, .o_form_field, div') ? "
                    "e.closest('.o_field_widget, .form-check, .custom-control, "
                    "label, .o_form_field, div').outerHTML : 'NO PARENT'"
                )
                print(f'PARENT: {parent_html[:800]}')
            except Exception as e:
                print(f'  err {e}')

        browser.close()


if __name__ == '__main__':
    main()
