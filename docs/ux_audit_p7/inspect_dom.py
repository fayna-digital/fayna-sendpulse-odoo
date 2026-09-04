#!/usr/bin/env python3
"""Інспекція DOM — знайти селектори апп-меню та пунктів Channel Bridge."""

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

        # Клік по бренду (апп-світчер) — верхній лівий кут
        for sel in ['.o_menu_brand', '.o_mail_sidebar_brand', '.o_app_switcher_button']:
            els = page.query_selector_all(sel)
            print(f"\nBrand selector '{sel}': {len(els)}")
            if els:
                try:
                    els[0].click()
                    page.wait_for_timeout(2500)
                    print('  clicked brand')
                    break
                except Exception as e:
                    print(f'  click err {e}')

        # Після кліку — знайти всі data-menu-xmlid
        print('\n--- data-menu-xmlid after brand click ---')
        els = page.query_selector_all('[data-menu-xmlid]')
        for i, el in enumerate(els[:60]):
            try:
                xmlid = el.get_attribute('data-menu-xmlid')
                txt = el.inner_text()[:60].replace('\n', ' | ')
                vis = el.is_visible()
                print(f"  [{i}] {xmlid} :: '{txt}' visible={vis}")
            except Exception:
                pass

        # Знайти елементи з текстом Channel Bridge
        els = page.query_selector_all('text=Channel Bridge')
        print(f"\nElements with 'Channel Bridge' text: {len(els)}")
        for i, el in enumerate(els[:10]):
            try:
                tag = el.evaluate("e => e.tagName + '.' + e.className")
                vis = el.is_visible()
                print(f'  [{i}] {tag} visible={vis}')
            except Exception as e:
                print(f'  [{i}] err {e}')

        browser.close()


if __name__ == '__main__':
    main()
