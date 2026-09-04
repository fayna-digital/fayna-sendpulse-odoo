#!/usr/bin/env python3
"""Глибока інспекція апп-меню Odoo 17 — знайти Channel Bridge у світчері застосунків."""

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

        # Спробувати відкрити апп-світчер кількома способами
        # 1) Клік по бренду
        brand = page.query_selector('.o_menu_brand')
        if brand:
            brand.click()
            page.wait_for_timeout(3000)
            print('\n--- after .o_menu_brand click ---')
            # Вивести всі видимі пункти меню
            for el in page.query_selector_all(
                '.o_menu_entry, .o_app, [data-menu-xmlid], .dropdown-menu a, .o_app_switcher_item'
            ):
                try:
                    xmlid = el.get_attribute('data-menu-xmlid') or ''
                    txt = el.inner_text()[:80].replace('\n', ' | ')
                    vis = el.is_visible()
                    if vis:
                        print(f"  MENU: '{txt}' xmlid={xmlid}")
                except Exception:
                    pass

        # 2) Пошук усіх елементів з текстом Channel Bridge у всьому DOM
        print("\n--- search 'Channel Bridge' in full DOM ---")
        found = page.evaluate(
            """() => {
                const results = [];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    if (node.textContent.includes('Channel Bridge')) {
                        const el = node.parentElement;
                        results.push({
                            tag: el.tagName,
                            cls: el.className,
                            xmlid: el.getAttribute && el.getAttribute('data-menu-xmlid'),
                            visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length),
                            html: el.outerHTML.slice(0, 200)
                        });
                    }
                }
                return results;
            }"""
        )
        for r in found:
            print(f'  FOUND: {r}')

        # 3) Перевірити чи є апп-меню взагалі (Apps dropdown)
        print('\n--- apps menu structure ---')
        apps = page.query_selector_all('.o_menu_apps, .o_apps, .o_web_client_apps, .o_app_switcher')
        print(f'apps containers: {len(apps)}')
        for a in apps:
            print('  container:', a.evaluate('e => e.className'))

        # 4) Зняти скріншот
        page.screenshot(path='screenshots/apps_switcher.png', full_page=False)
        print('\nScreenshot saved: screenshots/apps_switcher.png')

        browser.close()


if __name__ == '__main__':
    main()
