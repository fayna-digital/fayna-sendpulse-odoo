"""Dump detailed DOM of the connect wizard and provider form for lens analysis."""

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


def dump_modal(page, label):
    print(f'\n===== {label} =====')
    modals = page.query_selector_all('.modal')
    for i, m in enumerate(modals):
        try:
            if not m.is_visible():
                continue
            cls = m.get_attribute('class') or ''
            print(f'--- modal[{i}] class={cls} ---')
            # buttons
            for b in m.query_selector_all('button'):
                try:
                    if b.is_visible():
                        print(
                            f"  BUTTON: '{b.inner_text().strip()}' class={b.get_attribute('class')}"
                        )
                except Exception:
                    pass
            # inputs
            for inp in m.query_selector_all('input'):
                try:
                    if inp.is_visible():
                        print(
                            f"  INPUT: type={inp.get_attribute('type')} placeholder={inp.get_attribute('placeholder')} name={inp.get_attribute('name')} id={inp.get_attribute('id')}"
                        )
                except Exception:
                    pass
            # labels
            for lb in m.query_selector_all('label'):
                try:
                    if lb.is_visible():
                        print(
                            f"  LABEL: for={lb.get_attribute('for')} text='{lb.inner_text().strip()}'"
                        )
                except Exception:
                    pass
            # text
            print(f'  TEXT: {m.inner_text()[:600]}')
        except Exception as e:
            print(f'  modal[{i}] err {e}')


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        login(page)

        # Open Telegram provider form
        page.goto(
            f'{BASE}/web#action=141&model=channel.provider&view_type=form&id=1',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        dump_modal(page, 'PROVIDER FORM (Telegram)')

        # Open wizard via Connect
        try:
            btn = page.query_selector('button:has-text("Connect")')
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(2500)
        except Exception as e:
            print('connect click err', e)
        dump_modal(page, 'CONNECT WIZARD')

        browser.close()


main()
