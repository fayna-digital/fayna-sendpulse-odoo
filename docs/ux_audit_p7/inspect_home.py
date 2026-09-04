#!/usr/bin/env python3
"""Клік по 'Home Menu' (апп-світчер) і дамп усіх застосунків."""

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

        # Клік по Home Menu (апп-світчер)
        home = page.query_selector('[title="Home Menu"]')
        if home:
            home.click()
            page.wait_for_timeout(3000)
            print('\n--- after Home Menu click ---')
            # Дамп усіх пунктів меню у відкритому дропдауні
            for el in page.query_selector_all(
                '.o_menu_entry, .o_app, [data-menu-xmlid], .dropdown-menu a, .o-dropdown-menu a, .o_app_switcher_item, .o_menu_apps a'
            ):
                try:
                    xmlid = el.get_attribute('data-menu-xmlid') or ''
                    txt = el.inner_text()[:60].replace('\n', ' | ')
                    vis = el.is_visible()
                    if vis and (txt.strip() or xmlid):
                        print(f"  MENU: '{txt}' xmlid={xmlid}")
                except Exception:
                    pass
        else:
            print('Home Menu button not found')

        # Пошук Channel Bridge у всьому DOM
        print("\n--- search 'Channel Bridge' ---")
        found = page.evaluate(
            """() => {
                const results = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.includes('Channel Bridge')) {
                        const el = node.parentElement;
                        results.push({
                            tag: el.tagName, cls: el.className,
                            xmlid: el.getAttribute && el.getAttribute('data-menu-xmlid'),
                            visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                        });
                    }
                }
                return results;
            }"""
        )
        for r in found:
            print(f'  FOUND: {r}')

        page.screenshot(path='screenshots/home_menu.png', full_page=False)
        print('\nScreenshot: screenshots/home_menu.png')

        browser.close()


if __name__ == '__main__':
    main()
