#!/usr/bin/env python3
"""Діагностика стану сторінки після Telegram wizard flow."""

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

        # Telegram flow
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
        modal = page.query_selector('.modal')
        tok = modal.query_selector('input[type="password"]')
        if tok:
            tok.fill('invalid-token-123')
        conn = modal.query_selector('button:has-text("Connect")')
        if conn:
            conn.click()
            page.wait_for_timeout(5000)
        # dismiss error dialog
        for m in page.query_selector_all('.modal'):
            try:
                if not m.is_visible():
                    continue
                cls = m.get_attribute('class') or ''
                if 'o_inactive_modal' in cls:
                    continue
                ok = m.query_selector('button:has-text("Ok"), button:has-text("Close")')
                if ok and ok.is_visible():
                    ok.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue
        # cancel wizard
        cancel = page.query_selector('.modal button:has-text("Cancel")')
        if cancel:
            cancel.click()
            page.wait_for_timeout(2000)

        print('=== after telegram flow ===')
        print('URL:', page.url)
        print('modals:', len(page.query_selector_all('.modal')))
        for i, m in enumerate(page.query_selector_all('.modal')):
            try:
                print(f"  modal[{i}] class='{m.get_attribute('class')}' visible={m.is_visible()}")
            except Exception:
                pass
        print('kanban records:', len(page.query_selector_all('.o_kanban_record')))
        print(
            'kanban non-ghost:',
            len(page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)')),
        )

        # Now goto gallery again
        page.goto(f'{BASE}/web#action={ACTION_CONNECT}', wait_until='domcontentloaded')
        page.wait_for_timeout(4000)
        print('\n=== after goto gallery ===')
        print('URL:', page.url)
        print('modals:', len(page.query_selector_all('.modal')))
        print(
            'kanban non-ghost:',
            len(page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)')),
        )
        for c in page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)'):
            try:
                print('  card:', c.inner_text()[:40].replace('\n', ' | '))
            except Exception:
                pass

        browser.close()


if __name__ == '__main__':
    main()
