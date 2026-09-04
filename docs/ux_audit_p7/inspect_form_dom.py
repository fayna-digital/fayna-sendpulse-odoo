"""Dump provider form fields and gallery card DOM for lens analysis."""

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


def dump_form_fields(page, label):
    print(f'\n===== {label} =====')
    for inp in page.query_selector_all('input'):
        try:
            if inp.is_visible():
                print(
                    f"  INPUT: type={inp.get_attribute('type')} placeholder={inp.get_attribute('placeholder')} name={inp.get_attribute('name')} id={inp.get_attribute('id')} disabled={inp.is_disabled()}"
                )
        except Exception:
            pass
    for lb in page.query_selector_all('label'):
        try:
            if lb.is_visible():
                print(f"  LABEL: for={lb.get_attribute('for')} text='{lb.inner_text().strip()}'")
        except Exception:
            pass
    for sel in page.query_selector_all('select'):
        try:
            if sel.is_visible():
                print(f"  SELECT: name={sel.get_attribute('name')} id={sel.get_attribute('id')}")
        except Exception:
            pass


def dump_gallery_cards(page, label):
    print(f'\n===== {label} =====')
    cards = page.query_selector_all('.o_kanban_record')
    print(f'  total cards: {len(cards)}')
    for i, c in enumerate(cards):
        try:
            if c.is_visible():
                txt = c.inner_text().replace('\n', ' | ')[:200]
                print(f'  card[{i}]: {txt}')
        except Exception:
            pass


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        login(page)

        # Gallery
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        dump_gallery_cards(page, 'GALLERY CARDS')

        # Telegram provider form
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=form&id=1',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        dump_form_fields(page, 'PROVIDER FORM (Telegram)')

        # TikTok provider form (blocked) - find id
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(2500)
        # click TikTok card
        for c in page.query_selector_all('.o_kanban_record'):
            try:
                if c.is_visible() and 'TikTok' in c.inner_text():
                    c.click()
                    break
            except Exception:
                pass
        page.wait_for_timeout(2500)
        dump_form_fields(page, 'PROVIDER FORM (TikTok blocked)')

        browser.close()


main()
