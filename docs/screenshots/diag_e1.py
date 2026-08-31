"""Діагностика рендеру списку «Канали»: заголовки колонок і значення рядків."""

import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8069"
LOGIN = "admin"
PASSWORD = "admin"


def settle(page, ms=1500):
    page.wait_for_timeout(ms)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"{BASE}/web/login", wait_until="domcontentloaded")
        settle(page)
        page.fill('input[name="login"]', LOGIN)
        page.fill('input[name="password"]', PASSWORD)
        page.click('button[type="submit"]')
        settle(page, 2500)

        # Прямий перехід на список каналів через action (137 = Канали, menu 99)
        page.goto(
            f"{BASE}/web#action=137&cids=1&menu_id=99", wait_until="domcontentloaded"
        )
        settle(page, 4000)
        print("URL:", page.url)

        # Заголовки колонок
        headers = page.locator("thead th").all_inner_texts()
        print("HEADERS:", headers)

        # Рядки таблиці
        rows = page.locator("tr.o_data_row")
        print("ROW COUNT:", rows.count())
        for i in range(rows.count()):
            cells = rows.nth(i).locator("td").all_inner_texts()
            print(f"ROW {i}:", cells)

        # Текст заголовка колонки «Стан» — перевірити чи не обрізаний (без …)
        # Знайти th з текстом Стан
        th = page.locator("thead th", has_text="Стан").first
        if th.count():
            print("TH Стан text:", repr(th.inner_text()))
            print("TH Стан width:", th.bounding_box())

        browser.close()


if __name__ == "__main__":
    sys.exit(main())
