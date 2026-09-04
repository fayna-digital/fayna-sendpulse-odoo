#!/usr/bin/env python3
"""Інспекція DOM полів підтвердження передумов (region_confirmed/consent_confirmed)."""

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

        # TikTok form
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

        print('=== TikTok form inputs ===')
        for el in page.query_selector_all('input, textarea, select, .o_checkbox, .custom-checkbox'):
            try:
                tag = el.evaluate('e => e.tagName')
                name = el.get_attribute('name')
                typ = el.get_attribute('type')
                cls = el.get_attribute('class')
                vis = el.is_visible()
                print(f"  <{tag}> name='{name}' type='{typ}' class='{cls}' visible={vis}")
            except Exception as e:
                print(f'  err {e}')

        # Шукаємо будь-який checkbox
        print('\n=== checkboxes ===')
        for el in page.query_selector_all(
            "input[type='checkbox'], .o_checkbox, .custom-control-input"
        ):
            try:
                tag = el.evaluate('e => e.tagName')
                name = el.get_attribute('name')
                cls = el.get_attribute('class')
                print(f"  <{tag}> name='{name}' class='{cls}'")
            except Exception:
                pass

        # Текст форми
        print('\n=== form text (Precondition area) ===')
        txt = page.inner_text('body')
        idx = txt.find('Precondition')
        if idx >= 0:
            print(txt[idx : idx + 300])
        else:
            print("'Precondition' not found in body text")

        browser.close()


if __name__ == '__main__':
    main()
