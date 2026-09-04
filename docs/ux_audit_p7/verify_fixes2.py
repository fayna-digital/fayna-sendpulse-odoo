"""Verify the 4 yellow UX fixes render in the live UI (with a connected channel)."""

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

        # --- Connect a Viber channel (no network needed) ---
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        # click Viber card
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible() and 'Viber' in c.inner_text():
                    c.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(2500)

        # Fill token field (password input) and connect
        token_input = page.query_selector('input[type="password"]')
        if token_input:
            token_input.fill('test-viber-token-123')
            page.wait_for_timeout(500)
        # click Connect (form button)
        for b in page.query_selector_all('button'):
            try:
                if b.is_visible() and b.inner_text().strip() == 'Connect':
                    b.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(3000)

        # --- Fix 3 (Ш6/Т8): Disconnect button on connected card ---
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        print('===== GALLERY CARDS (Disconnect on connected) =====')
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible():
                    txt = c.inner_text().replace('\n', ' | ')[:160]
                    has_disconnect = 'Disconnect' in c.inner_text()
                    print(f"  card: {txt}  [Disconnect={'YES' if has_disconnect else 'no'}]")
            except Exception:
                pass

        # --- Fix 2 (Н9): Channels list last_error column ---
        page.goto(
            f'{BASE}/web#action=140&model=channel.backend&view_type=list',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        print('\n===== CHANNELS LIST headers =====')
        for h in page.query_selector_all('th'):
            try:
                if h.is_visible():
                    print(f"  header: '{h.inner_text().strip()}'")
            except Exception:
                pass

        # --- Fix 1 (Н1/Ш3/Нор2): Wizard Connect confirm dialog ---
        # Open Telegram provider form, click Connect to open wizard, click Connect -> expect confirm dialog
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=form&id=1',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        try:
            btn = page.query_selector('button:has-text("Connect")')
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(2500)
        except Exception as e:
            print('connect click err', e)

        # In wizard, click Connect and capture dialog
        print('\n===== WIZARD Connect confirm dialog =====')
        dialog_msg = None

        def on_dialog(d):
            nonlocal dialog_msg
            dialog_msg = d.message
            d.accept()

        page.on('dialog', on_dialog)
        for m in page.query_selector_all('.modal'):
            try:
                if m.is_visible():
                    for b in m.query_selector_all('button'):
                        try:
                            if b.is_visible() and b.inner_text().strip() == 'Connect':
                                b.click()
                                page.wait_for_timeout(1500)
                                break
                        except Exception:
                            pass
            except Exception:
                pass
        print(f'  confirm dialog message: {dialog_msg!r}')

        browser.close()


main()
