"""Verify the 4 yellow UX fixes render in the live UI (Odoo confirm modal)."""

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


def dump_confirm_modals(page, label):
    print(f'\n===== {label} =====')
    # Odoo confirm dialog is typically .modal with .o_confirm or a dialog
    for m in page.query_selector_all('.modal'):
        try:
            if m.is_visible():
                txt = m.inner_text().strip()[:300]
                print(f'  VISIBLE MODAL: {txt}')
        except Exception:
            pass
    # also check for o_dialog / confirm
    for d in page.query_selector_all('.o_dialog, .modal-dialog'):
        try:
            if d.is_visible():
                print(f'  DIALOG: {d.inner_text().strip()[:200]}')
        except Exception:
            pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        login(page)

        # --- Connect Viber ---
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible() and 'Viber' in c.inner_text():
                    c.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(2500)
        token_input = page.query_selector('input[type="password"]')
        if token_input:
            token_input.fill('test-viber-token-123')
            page.wait_for_timeout(500)
        for b in page.query_selector_all('button'):
            try:
                if b.is_visible() and b.inner_text().strip() == 'Connect':
                    b.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(3500)

        # --- Fix 3: Disconnect on connected card ---
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3500)
        print('===== GALLERY CARDS =====')
        cards = page.query_selector_all('.o_kanban_record')
        print(f'  total cards: {len(cards)}')
        for c in cards:
            try:
                if c.is_visible():
                    txt = c.inner_text().replace('\n', ' | ')[:160]
                    print(
                        f"  card: {txt}  [Disconnect={'YES' if 'Disconnect' in c.inner_text() else 'no'}]"
                    )
            except Exception:
                pass

        # --- Fix 2: Channels list last_error column ---
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

        # --- Fix 1: Wizard Connect -> Odoo confirm modal ---
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
        # click Connect in wizard
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
        dump_confirm_modals(page, 'AFTER WIZARD CONNECT (expect Odoo confirm)')

        browser.close()


main()
