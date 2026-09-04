#!/usr/bin/env python3
"""UX-аудит 4 аналітичні лінзи — збір рендер-контенту ключових екранів.

Збирає текст і структуру DOM кожного екрана, щоб оцінити евристики
Нільсена/Шнейдермана/Нормана/Тогнацці по РЕНДЕРУ (не по коду).
"""

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8071'
LOGIN = 'admin'
PASSWORD = 'admin'
ACTION_CONNECT = 141


def dump(page, label):
    print(f"\n{'=' * 70}\n### {label}\n{'=' * 70}")
    # Заголовок сторінки / breadcrumb
    try:
        title = page.title()
        print(f'TITLE: {title}')
    except Exception:
        pass
    # Видимий текст основного контенту
    try:
        body = page.inner_text('body')
        # Обрізати до розумної довжини
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        print('BODY TEXT (visible):')
        for l in lines[:60]:
            print(f'  | {l}')
    except Exception as e:
        print(f'  body err: {e}')


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = ctx.new_page()
        page.set_default_timeout(25000)

        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_timeout(4000)

        # 1. Галерея каналів
        page.goto(
            f'{BASE}/web#action={ACTION_CONNECT}&model=channel.provider&view_type=kanban',
            wait_until='domcontentloaded',
        )
        page.wait_for_timeout(3000)
        dump(page, 'GALLERY (Connect channels)')

        # 2. Форма провайдера (Telegram)
        for c in page.query_selector_all('.o_kanban_record:not(.o_kanban_ghost)'):
            if 'Telegram' in c.inner_text():
                c.click()
                page.wait_for_timeout(2500)
                break
        dump(page, 'PROVIDER FORM (Telegram)')

        # 3. Wizard
        btn = page.query_selector('button:has-text("Connect")')
        if btn:
            btn.click()
            page.wait_for_timeout(2500)
        dump(page, 'WIZARD (connect wizard)')

        # 4. Списки
        for aid, label in [
            (139, 'CONVERSATIONS LIST'),
            (137, 'JOURNAL LIST'),
            (140, 'CHANNELS LIST'),
        ]:
            page.goto(
                f'{BASE}/web#action={aid}&view_type=list',
                wait_until='domcontentloaded',
            )
            page.wait_for_timeout(3000)
            dump(page, label)

        browser.close()


if __name__ == '__main__':
    main()
