# План міграції: git-делівері `fayna_channel_bridge` на прод

> Статус: **ЧЕРНЕТКА НА РЕВ'Ю** — жодних змін на проді не виконувати, поки план не затверджено.
> Дата: 2026-09-01 · Автор: виконавець · Рев'ю: користувач

---

## 0. Контекст і проблема

Зараз модуль `fayna_channel_bridge` на проді лежить у
`/opt/campscout/custom-addons/fayna_channel_bridge` як **звичайна тека без `.git`**.
Доставка коду на сервер відбувалась через `rsync` — це **порушує #4ZONES**
(CLAUDE.md) та golden-rules-developer #3 («Сервер — тільки через Git»).

Наслідок, який уже проявився: **код на проді і код у git — різні** (md5 трьох
ключових файлів розбіжні). Версія `17.0.1.5.0` позначає два різні стани коду.
Наступний деплой стає неоднозначним.

**Мета плану:** перевести доставку `fayna_channel_bridge` на git-флоу
`local → push (VladSh77) → server pull`, зняти неоднозначність версії, зберегти
працездатність прода і мати чіткий відкат.

---

## 1. Факти (перевірено)

| Факт | Значення |
|------|----------|
| Прод-тека модуля | `/opt/campscout/custom-addons/fayna_channel_bridge` (без `.git`) |
| Docker-mount | `/opt/campscout/custom-addons` → `/mnt/custom-addons` |
| `addons_path` | `…,/mnt/custom-addons,…` (див. `/opt/campscout/config/odoo.conf`) |
| Репо (робоче) | `git@github.com:VladSh77/fayna-sendpulse-odoo.git` |
| Гілка | `feature/direct-transport` → коміт `972fa25` |
| Корінь репо | це **сам Odoo-модуль** `Fayna SendPulse Odoo` (v17.0.1.15.14) — старий SendPulse-модуль, свідомо знятий з прода |
| `addons/` у репо | містить **лише** `fayna_channel_bridge` |
| SSH-доступ сервера | `git@github.com` автентифікується як `VladSh77/fayna-sendpulse-odoo` (read OK); є окремий аліас `github-channelbridge` → `~/.ssh/id_ed25519_channelbridge` |
| git на сервері | 2.43.0 |

---

## 2. Дві пастки (відповіді обов'язкові)

### Пастка 1 — що додавати в `addons_path`

**Не можна** додавати корінь клону `<clone>` у `addons_path`, бо корінь репо — це
сам старий SendPulse-модуль (`__manifest__.py` з `name='Fayna SendPulse Odoo'`,
v17.0.1.15.14). Odoo почне його сканувати як модуль, а ми його свідомо зняли з
прода.

**Рішення:** у `addons_path` додаємо **лише `<clone>/addons`** (де лежить
`fayna_channel_bridge`). Корінь клону в `addons_path` не потрапляє.

> **Додаткова пастка (Дефект 1 з рев'ю):** навіть якщо корінь клону не в
> `addons_path`, сам факт розміщення клону **безпосередньо** в
> `/opt/campscout/custom-addons/` створює проблему: `/mnt/custom-addons` **уже є** в
> `addons_path`, а Odoo (`get_modules()`) ітерує **безпосередні** підтеки кожного
> шляху і реєструє будь-яку теку з `__manifest__.py`. Корінь репо — це сам старий
> SendPulse-модуль (`__manifest__.py` з `name='Fayna SendPulse Odoo'`), тож клон
> став би модулем у базі — Пастка 1 обходиться з чорного ходу.
>
> **Розв'язка — `_src/`:** оскільки Odoo **не рекурсує**, ховаємо клон на рівень
> глибше під теку **без маніфесту**: `custom-addons/_src/fayna-sendpulse-odoo/`.
> Odoo перевірить `_src/__manifest__.py` — його немає, тека пропускається. А
> `_src/fayna-sendpulse-odoo/addons` вказаний у `addons_path` явно, тож
> `fayna_channel_bridge` знайдеться. Усе лишається всередині mount-у, зміна
> docker-compose не потрібна.

### Пастка 2 — Docker-mount

Усе, на що вказує `addons_path`, **мусить бути всередині змонтованої теки**
`/opt/campscout/custom-addons` (→ `/mnt/custom-addons`). Клон поза mount-ом або
симлінк назовні в контейнері **не резолвиться** — Odoo просто не побачить модуль,
помилка буде невиразна.

**Рішення:** клон розміщуємо **всередині** `/opt/campscout/custom-addons/`, під
текою без маніфесту `_src/` (див. Пастка 1):
`/opt/campscout/custom-addons/_src/fayna-sendpulse-odoo/`. Тоді
`<clone>/addons/fayna_channel_bridge` = `/opt/campscout/custom-addons/_src/fayna-sendpulse-odoo/addons/fayna_channel_bridge`
— це всередині mount-у, резолвиться коректно.

---

## 3. Цільова структура (після міграції)

```
/opt/campscout/custom-addons/
├── _src/                            # тека БЕЗ маніфесту — Odoo її пропускає (Пастка 1)
│   └── fayna-sendpulse-odoo/        # git-клон VladSh77/fayna-sendpulse-odoo (гілка feature/direct-transport)
│       ├── addons/
│       │   └── fayna_channel_bridge/    # ← модуль, який читає Odoo
│       ├── __manifest__.py              # старий SendPulse-модуль (НЕ в addons_path)
│       └── ...
├── fayna_channel_bridge/            # ← СТАРА тека, буде замінена/прибрана
├── fayna_channel_bridge_old_170100/ # ← фантом, буде прибраний (Крок 4)
├── campscout_management/
├── fayna_camp_lead_sms/
├── fayna_rodo_compliance/
├── fayna_sentry/
└── zadarma_odoo/
```

`addons_path` змінюється:
```
старе:  /mnt/extra-addons,/mnt/extra-addons/odoo17-l10n_pl_ksef_margin,/mnt/custom-addons,/usr/lib/python3/dist-packages/odoo/addons
нове:   /mnt/extra-addons,/mnt/extra-addons/odoo17-l10n_pl_ksef_margin,/mnt/custom-addons/_src/fayna-sendpulse-odoo/addons,/mnt/custom-addons,/usr/lib/python3/dist-packages/odoo/addons
```
(додано `/mnt/custom-addons/_src/fayna-sendpulse-odoo/addons` перед `/mnt/custom-addons`).

---

## 4. Кроки міграції (порядок виконання)

> Усі команди — на хості через `ssh campscout` (користувач `deploy` + `sudo` де треба).
> Нічого не видаляється, поки новий шлях не підтверджено робочим.

### Крок 4.0 — Підготовка (без зміни прода)
1. **Бекап конфігу:** `sudo cp /opt/campscout/config/odoo.conf /opt/campscout/config/odoo.conf.bak.$(date +%Y%m%d)`
2. **Бекап теки модуля** — **поза `addons_path`**, у `/opt/campscout/backups/` (тека вже існує, `drwxr-xr-x deploy deploy`). Не в `custom-addons/` — тека з маніфестом там створила б новий фантом-модуль (це буквально інцидент `fayna_channel_bridge_old_170100`):
   `sudo cp -a /opt/campscout/custom-addons/fayna_channel_bridge /opt/campscout/backups/fayna_channel_bridge.bak.$(date +%Y%m%d)`
3. **Бекап БД** (стандартний): `docker exec campscout_db pg_dump -U odoo campscout | gzip > /opt/campscout/backup/db_$(date +%Y%m%d).sql.gz`

### Крок 4.1 — Клон репо (без перемикання Odoo)
```bash
mkdir -p /opt/campscout/custom-addons/_src
cd /opt/campscout/custom-addons/_src
git clone git@github.com:VladSh77/fayna-sendpulse-odoo.git fayna-sendpulse-odoo
cd fayna-sendpulse-odoo
git checkout feature/direct-transport
sudo chmod -R o+rX .
```
> Клон — усередині mount-у (Пастка 2), під текою `_src/` без маніфесту (Пастка 1).
> `chmod -R o+rX` — обов'язково (INC-244), щоб контейнер (інший uid) міг читати файли.

### Крок 4.2 — Перевірка без перемикання
```bash
# модуль видно в клоні:
ls /opt/campscout/custom-addons/_src/fayna-sendpulse-odoo/addons/fayna_channel_bridge/__manifest__.py
# версія в клоні:
grep '"version"' /opt/campscout/custom-addons/_src/fayna-sendpulse-odoo/addons/fayna_channel_bridge/__manifest__.py
```

### Крок 4.3 + 4.4 — АТОМАРНО (перемикання `addons_path` + `-u` + рестарт)
> **Атомарність (вимога рев'ю):** Кроки 4.3 і 4.4 виконуються **одним блоком, без
> паузи між ними**. Модуль додає **17 нових полів** (translate=True → jsonb). Якщо
> перемкнути `addons_path` і рестартнути БЕЗ `-u`, модуль впаде на неіснуючих полях.
> Тому: перемикання конфігу → одразу `-u` → одразу рестарт → перевірка.

### Крок 4.3 — Перемикання `addons_path` + рестарт
1. Відредагувати `/opt/campscout/config/odoo.conf`: додати
   `/mnt/custom-addons/_src/fayna-sendpulse-odoo/addons` у `addons_path` (див. §3).
2. `docker compose restart web` (або `docker restart campscout_web`).
3. **Перевірка:** сайт живий, модуль видно:
   ```sql
   SELECT name, latest_version, state FROM ir_module_module WHERE name='fayna_channel_bridge';
   ```
   → має бути `state='installed'`, `latest_version` = актуальна.

### Крок 4.4 — Підняти версію до 17.0.1.6.0 (усунути неоднозначність)
> Версія `17.0.1.5.0` зараз позначає два різні стани коду (прод позаду git).
> Перед деплоєм Фази 1 номер піднімаємо, щоб номер однозначно вказував на стан у git.

1. Локально в `addons/fayna_channel_bridge/__manifest__.py`: `'version': '17.0.1.6.0'`.
2. Коміт + push у `VladSh77` (гілка `feature/direct-transport`).
3. На сервері: `cd /opt/campscout/custom-addons/_src/fayna-sendpulse-odoo && git pull && sudo chmod -R o+rX .`
4. Оновлення модуля (docker exec на запущеному, НЕ `docker compose run --rm`):
   ```bash
   docker exec campscout_web odoo -c /etc/odoo/odoo.conf -d campscout -u fayna_channel_bridge --stop-after-init
   docker restart campscout_web
   ```
5. Перевірка: `SELECT latest_version FROM ir_module_module WHERE name='fayna_channel_bridge';` → `17.0.1.6.0`.

### Крок 4.4a — `-u` на копії прод-бази ПЕРЕД продом (вимога рев'ю)
> Перед тим як чіпати прод, прогнати міграцію translate=True → jsonb на **копії**
> прод-бази, щоб переконатись, що міграція проходить чисто на реальних даних.

1. Створити копію прод-бази:
   ```bash
   docker exec campscout_db pg_dump -U odoo campscout | docker exec -i campscout_db psql -U odoo -d campscout_mig_test
   ```
   (попередньо створити порожню `campscout_mig_test` через `createdb -U odoo campscout_mig_test`).
2. Прогнати `-u` на копії (з `--db-filter=.*`, на запущеному контейнері):
   ```bash
   docker exec campscout_web odoo -c /etc/odoo/odoo.conf -d campscout_mig_test --db-filter=.* -u fayna_channel_bridge --stop-after-init
   ```
3. Перевірка: міграція пройшла без помилок, поля jsonb заповнені:
   ```sql
   SELECT name, latest_version, state FROM ir_module_module WHERE name='fayna_channel_bridge';
   ```
   → `installed`, `17.0.1.6.0`.
4. Після успіху — видалити тестову копію: `docker exec campscout_db dropdb -U odoo campscout_mig_test`.

### Крок 4.5 — Прибрати стару теку (після підтвердження)
- **Виконувати того ж дня, що й Крок 4.4** — тримати вікно з двома однойменними
  теками (`fayna_channel_bridge` стара + у клоні) якомога коротшим.
- Лише після того, як новий шлях працює і версія підтверджена:
  `sudo rm -rf /opt/campscout/custom-addons/fayna_channel_bridge`
- Фантом `fayna_channel_bridge_old_170100` — окремий Крок 4 (див. нижче).

---

## 5. Відкат (rollback)

Прод працює, аварії немає — відкат має бути тривіальним і швидким.

### Відкат до стану «до міграції»
1. Повернути конфіг: `sudo cp /opt/campscout/config/odoo.conf.bak.$(date +%Y%m%d) /opt/campscout/config/odoo.conf`
   (тобто прибрати `/mnt/custom-addons/_src/fayna-sendpulse-odoo/addons` з `addons_path`).
2. Повернути стару теку модуля (з бекапу **поза** `addons_path`):
   `sudo mv /opt/campscout/backups/fayna_channel_bridge.bak.$(date +%Y%m%d) /opt/campscout/custom-addons/fayna_channel_bridge`
3. `docker restart campscout_web`.
4. Перевірка: сайт живий, модуль `state='installed'`.

> Якщо вже виконано `-u` (Крок 4.4) — відкат коду не відкочує зміни БД (jsonb-міграція
> ідемпотентна, зворотна конвертація не потрібна для роботи). БД-бекап з Кроку 4.0
> дає повний відкат БД за потреби.

---

## 6. Ризики та пом'якшення

| Ризик | Ймовірність | Вплив | Пом'якшення |
|-------|-------------|-------|-------------|
| Odoo не бачить модуль (mount/шлях) | середня | сайт 502 або модуль зник | Клон усередині mount-у; перевірка до рестарту; відкат конфігу |
| Старий SendPulse-модуль сканується | низька | зайвий модуль у списку | У `addons_path` лише `<clone>/addons`, не корінь |
| Права доступу (uid контейнера) | середня | модуль не читається | `chmod -R o+rX` обов'язково (INC-244) |
| Версія неоднозначна | висока (вже є) | неясно, що на сервері | Підняти до 17.0.1.6.0 перед деплоєм |
| `-u` на проді | низька | короткий даунтайм | Вікно обслуговування; бекап БД; ідемпотентна міграція |

---

## 7. Що НЕ входить у цей план (окремі кроки)

- **Крок 4 (окремий):** прибрати фантом `fayna_channel_bridge_old_170100` — після
  підтвердження нового шляху.
- **Деплой Фази 1 (OWL-SPA)** — сам по собі, через новий git-флоу, після затвердження
  цього плану і підняття версії.

---

## 8. Критерії успіху

1. `addons_path` містить `/mnt/custom-addons/_src/fayna-sendpulse-odoo/addons`, корінь клону — НЕ містить.
2. Клон лежить усередині `/opt/campscout/custom-addons/_src/` (mount-сумісний, під текою без маніфесту).
3. `SELECT name, latest_version, state FROM ir_module_module WHERE name='fayna_channel_bridge';`
   → `installed`, версія `17.0.1.6.0`.
4. **Нічого зайвого не з'явилось** (пастки не спрацювали):
   ```sql
   SELECT name, state FROM ir_module_module
   WHERE name ILIKE '%sendpulse%' OR name ILIKE '%bak%' OR name ILIKE '%_src%';
   ```
   → порожньо або лише знайомі рядки (`fayna_channel_bridge`, `fayna_channel_bridge_old_170100`).
5. Сайт живий, галерея каналів відкривається, тестовий прогін зелений.
6. Подальша доставка — тільки `git pull` + `chmod -R o+rX` + `-u` (жодного rsync).
