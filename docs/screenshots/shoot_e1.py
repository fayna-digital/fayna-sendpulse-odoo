"""Знімає скріни Е-1: список «Канали» (1440) і форма каналу.

Запуск: python3 shoot_e1.py
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = 'http://localhost:8069'
OUT = Path(__file__).parent

LOGIN = 'admin'
PASSWORD = 'admin'

# Прямі посилання (action 137 = список channel.backend, menu 99 = «Канали»)
LIST_URL = f'{BASE}/web#action=137&cids=1&menu_id=99'


def settle(page, ms=1500):
    page.wait_for_timeout(ms)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        # Вхід
        page.goto(f'{BASE}/web/login', wait_until='domcontentloaded')
        settle(page)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        settle(page, 2500)
        print('URL after login:', page.url)

        # Прямий перехід на список каналів
        page.goto(LIST_URL, wait_until='domcontentloaded')
        settle(page, 4000)
        print('List URL:', page.url)

        # Скрін списку
        page.screenshot(path=str(OUT / 'e1_backends_list_1440.png'), full_page=False)
        print('Saved list screenshot')

        # Відкрити форму першого каналу (E1-Працює)
        row = page.locator('tr.o_data_row', has_text='E1-Працює').first
        if row.count():
            row.click()
            settle(page, 2500)
            print('Form URL:', page.url)
            page.screenshot(path=str(OUT / 'e1_backend_form.png'), full_page=False)
            print('Saved form screenshot')
        else:
            print('Row E1-Працює not found')

        browser.close()


if __name__ == '__main__':
    sys.exit(main())
