"""Verify the 4 yellow UX findings are fixed in the rendered DOM."""

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
USER = 'admin'
PASS = 'admin'


def login(page):
    page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
    page.wait_for_timeout(1500)
    page.fill('input[name="login"]', USER)
    page.fill('input[name="password"]', PASS)
    page.click('button[type="submit"]')
    page.wait_for_timeout(3000)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        login(page)

        # --- Fix 3 (Ш6/Т8): Disconnect button on connected card ---
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        print('===== GALLERY CARDS (check Disconnect on connected) =====')
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible():
                    txt = c.inner_text().replace('\n', ' | ')[:180]
                    has_disconnect = 'Disconnect' in c.inner_text()
                    print(f"  card: {txt}  [Disconnect={'YES' if has_disconnect else 'no'}]")
            except Exception:
                pass

        # --- Fix 4 (Н5): Connect button confirm on warnings card ---
        # Find a card with warnings (e.g. Telegram has cost/side-effect warnings)
        print('\n===== CONNECT BUTTON confirm attribute (warnings) =====')
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible() and 'Telegram' in c.inner_text():
                    btns = c.query_selector_all('button')
                    for b in btns:
                        try:
                            if b.is_visible():
                                print(
                                    f"  Telegram card button: '{b.inner_text().strip()}' confirm={b.get_attribute('confirm')}"
                                )
                        except Exception:
                            pass
            except Exception:
                pass

        # --- Fix 2 (Н9): Channels list last_error column + Retry check button ---
        page.goto(
            f'{BASE}/web#action=140&model=channel.backend&view_type=list',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        print('\n===== CHANNELS LIST (check last_error column) =====')
        headers = page.query_selector_all('th')
        for h in headers:
            try:
                if h.is_visible():
                    print(f"  header: '{h.inner_text().strip()}'")
            except Exception:
                pass

        # --- Fix 1 (Н1/Ш3/Нор2): Wizard Connect button confirm ---
        # Open Telegram provider form, click Connect to open wizard
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=form&id=1',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        print('\n===== PROVIDER FORM (Telegram) buttons =====')
        for b in page.query_selector_all('button'):
            try:
                if b.is_visible():
                    print(
                        f"  BUTTON: '{b.inner_text().strip()}' confirm={b.get_attribute('confirm')}"
                    )
            except Exception:
                pass

        # Open wizard
        try:
            btn = page.query_selector('button:has-text("Connect")')
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(2500)
        except Exception as e:
            print('connect click err', e)
        print('\n===== CONNECT WIZARD buttons =====')
        for m in page.query_selector_all('.modal'):
            try:
                if m.is_visible():
                    for b in m.query_selector_all('button'):
                        try:
                            if b.is_visible():
                                print(
                                    f"  WIZARD BUTTON: '{b.inner_text().strip()}' confirm={b.get_attribute('confirm')}"
                                )
                        except Exception:
                            pass
            except Exception:
                pass

        browser.close()


main()
