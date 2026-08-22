# Deployment — Fayna SendPulse Odoo

**Module version:** `17.0.1.15.13` · **Last updated:** 2026-07-21

Інструкції для установки, оновлення і rollback на production (Odoo у Docker).

---

## Зміст

1. [Prerequisites](#1-prerequisites)
2. [Initial installation](#2-initial-installation)
3. [Upgrade procedure (standard)](#3-upgrade-procedure-standard)
4. [Rollback](#4-rollback)
5. [Post-deploy verification](#5-post-deploy-verification)
6. [Incident playbook](#6-incident-playbook)

---

## 1. Prerequisites

### 1.1 Server

- Ubuntu 22.04+ або Debian 12+
- Docker 24+ з `docker compose`
- Python 3.10+ всередині Odoo container
- PostgreSQL 14+ (usually в окремому контейнері)
- Nginx / Traefik як reverse proxy (для HTTPS + webhook)

### 1.2 Odoo modules

- `mail`, `contacts`, `crm`, `web` (всі з Odoo 17 core)
- `requests` Python package (зазвичай вже встановлений)

### 1.3 External accounts

- SendPulse account з OAuth API access
- (Для коментів) Meta Developer App з App Review approved на потрібні permissions
- (Для LLM) Anthropic API key
- (Для Telegram) Bot Token з @BotFather

### 1.4 SSH access

Робоча ssh-alias `campscout` (приклад) з ключем. Якщо нема:
```bash
ssh-copy-id -i ~/.ssh/id_ed25519_fayna.pub deploy@<server>
# + додати у ~/.ssh/config alias 'campscout'
```

---

## 2. Initial installation

### 2.1 Клонування

```bash
ssh campscout
cd /opt/campscout/custom-addons
git clone git@github.com:fayna-digital/fayna-sendpulse-odoo.git odoo_chatwoot_connector
```

**⚠️ Важливо:** папка називається `odoo_chatwoot_connector` (legacy ім'я з першої версії, не міняти — backward compatibility з `ir.config_parameter` ключами і addons_path).

### 2.2 Перевірка прав

```bash
ls -la /opt/campscout/custom-addons/odoo_chatwoot_connector
# Owner = deploy (не root)
```

Якщо root:
```bash
chown -R deploy:deploy /opt/campscout/custom-addons/odoo_chatwoot_connector
```

### 2.3 Install module

```bash
docker exec <odoo_web_container> /usr/bin/odoo \
    -d <db_name> \
    --stop-after-init --no-http \
    -i odoo_chatwoot_connector
```

Перевірка:
```bash
docker exec <db_container> psql -U odoo -d <db> -tAc \
    "SELECT state, latest_version FROM ir_module_module WHERE name='odoo_chatwoot_connector';"
# Очікувано: installed | 17.0.1.15.13
```

### 2.4 Restart web

```bash
cd /opt/campscout
docker compose restart web
```

### 2.5 Verify

```bash
curl -sI https://<your-domain>/
# HTTP/1.1 200 OK
```

Далі — **Configuration** у Odoo UI (див. [CONFIGURATION.md](CONFIGURATION.md)).

---

## 3. Upgrade procedure (standard)

### 3.1 Pull і upgrade

Одна команда для standard upgrade:

```bash
ssh campscout "cd /opt/campscout/custom-addons/odoo_chatwoot_connector && \
  git pull 2>&1 | tail -5 && \
  chmod -R o+rX . && \
  docker exec campscout_web /usr/bin/odoo -d campscout --stop-after-init --no-http -u odoo_chatwoot_connector 2>&1 | tail -3 && \
  cd /opt/campscout && docker compose restart web 2>&1 | tail -2 && \
  sleep 5 && \
  docker exec campscout_db psql -U odoo -d campscout -tAc \"SELECT latest_version FROM ir_module_module WHERE name='odoo_chatwoot_connector';\""
```

**`chmod -R o+rX .` після `git pull` — обов'язковий, не опційний.** Odoo-процес у контейнері читає модуль під іншим UID, ніж `deploy`-юзер що робить `git pull` — без world-read апдейт падає з `PermissionError` на будь-якому зміненому файлі (INC-244, 2026-07-20). Той самий крок потрібен і на staging. На staging встановлено `.git/hooks/post-merge`, що робить це автоматично при кожному `git pull`; на prod — робити вручну (або встановити ідентичний hook, ще не зроблено).

Очікуваний output — остання строка показує нову версію (напр. `17.0.1.15.13`).

### 3.2 Правила upgrade

- **Не використовувати** `docker compose run --rm web` — зупиняє контейнер назавжди (див. LOG.md inc. 2026-04-13)
- **Завжди** `docker exec <container>` на вже запущеному container
- Після upgrade — `docker compose restart web` щоб перезавантажити registry
- Перевірка версії **обов'язкова** — якщо модуль падає при завантаженні, `latest_version` не оновиться

### 3.3 Багатоступінчастий upgrade (якщо є міграції)

Якщо upgrade додає нові SQL поля:
1. `-u` автоматично викликає `_auto_init` → створює колонки
2. Дефолтні значення застосовуються до існуючих рядків
3. Indexed fields — індекс створюється в кінці (може зайняти час на великих таблицях)

Для великих таблиць (>1M рядків) — робити в off-peak time.

### 3.4 Upgrade з видаленням deprecated полів

Якщо нове повернення видаляє поле, Odoo скидає колонку **тільки** якщо `_auto_init` і ручне видалення через upgrade script. Без цього — поле залишається у БД (безпечно), але не юзабельне з Python.

---

## 4. Rollback

### 4.1 Якщо upgrade ламає registry (не запускається)

```bash
ssh campscout
cd /opt/campscout/custom-addons/odoo_chatwoot_connector

# Знайти попередню робочу версію
git log --oneline | head -10

# Відкотити на попередній коміт
git checkout <prev_commit_sha>

# Upgrade на попередній
docker exec campscout_web /usr/bin/odoo -d campscout --stop-after-init --no-http -u odoo_chatwoot_connector

cd /opt/campscout
docker compose restart web
```

### 4.2 Якщо potial данні зіпсувалися

- Має бути daily backup через `/opt/campscout/backup.sh`
- Відновлення: `pg_restore` конкретної таблиці, або full DB restore

### 4.3 Якщо git pull створив untracked/stashed файли

**Переконатися що stash не захоронений:**
```bash
git stash list
```

Якщо є `auto-stash before pull` — потрібно **pop вручну** (див. LOG.md 2026-04-20):
```bash
git stash show -p 0  # перегляд
git stash pop 0      # застосувати
```

⚠️ **Історична пастка:** 2026-04-19 auto-stash зберіг цілий реліз, а меморі/summary агента брехали що все закоммічено. Завжди `git status` + `git stash list` після `git pull`.

---

## 5. Post-deploy verification

Після кожного upgrade виконати:

### 5.1 Module state

```bash
docker exec campscout_db psql -U odoo -d campscout -c \
  "SELECT name, state, latest_version, write_date FROM ir_module_module WHERE name='odoo_chatwoot_connector';"
```

**Expected:** `state='installed'`, `latest_version` = нова версія, `write_date` = зараз.

### 5.2 Site health

```bash
curl -sI https://campscout.eu/ | head -3
# HTTP/1.1 200 OK
```

### 5.3 No errors у logs

```bash
docker logs campscout_web --tail 50 2>&1 | grep -iE "error|traceback|exception" | head -20
```

Помилки з часом до upgrade — OK. Свіжі — треба розбиратись.

### 5.4 Config parameters збережені

```bash
docker exec campscout_db psql -U odoo -d campscout -c \
  "SELECT key FROM ir_config_parameter WHERE key LIKE 'odoo_chatwoot_connector.%' ORDER BY key;"
```

Перевірити що всі потрібні ключі на місці (особливо токени).

### 5.5 Cron tasks active

```bash
docker exec campscout_db psql -U odoo -d campscout -c \
  "SELECT cron_name, active, nextcall FROM ir_cron WHERE cron_name LIKE 'SendPulse Odoo%';"
```

### 5.6 Test webhook receive

SendPulse: Settings → Webhooks → Test webhook → чи прийшов POST, чи створився `sendpulse.webhook.data` запис.

### 5.7 (Якщо увімкнено) Telegram alerts

```bash
docker exec -i campscout_web /usr/bin/odoo shell -d campscout --no-http << 'EOF'
env['sendpulse.connect'].sudo()._notify_telegram(
    '✅ Deploy OK — module v17.0.1.15.13', silent=False
)
EOF
```

Перевірити що прийшло у Telegram-групу.

---

## 6. Incident playbook

### 6.1 «Автовідповіді не летять»

Діагностика:
1. `ir.logging` → filter `name=odoo_chatwoot_connector.fb_api` — подивитись останні помилки
2. Token status:
   ```sql
   SELECT name, token_status, last_checked_at
   FROM sendpulse_facebook_page WHERE active=true;
   ```
3. Якщо `token_status='invalid: Session has expired...'` → токен User-Token, не Page — регенерувати через `/me/accounts` (див. Multi-page у CONFIGURATION.md)
4. Якщо cron `cron_check_fb_token_expiry` не запускав давно — запустити вручну

### 6.2 «Створюються дубль розмов»

Ознака: 2 записи `sendpulse.connect` з однаковим `sendpulse_contact_id` створені за < 5 секунд.

Фікс у v17.0.3.7.1 через `pg_advisory_xact_lock`. Якщо бачимо після — перевірити:
```bash
docker exec campscout_db psql -U odoo -d campscout -c \
  "SELECT sendpulse_contact_id, COUNT(*) FROM sendpulse_connect
   WHERE stage != 'close' GROUP BY sendpulse_contact_id HAVING COUNT(*) > 1;"
```

Cleanup скрипт — у LOG.md 2026-04-20 («14/14 merge»).

### 6.3 «Public User контамінація»

Ознака: у chatter системних записів «Olha Lipowa / Emiliia Protsenko — Contact created» замість OdooBot.

Фікс (SQL):
```bash
docker exec campscout_db psql -U odoo -d campscout -c \
  "UPDATE res_partner SET name='', email=NULL, street=NULL, street2=NULL, city=NULL,
   zip=NULL, country_id=NULL, phone=NULL, mobile=NULL, vat=NULL WHERE id=4;"
```

Причина: ручний merge партнерів через Odoo UI включає `base.public_partner (id=4)`. Правило: не мержити якщо один з партнерів без email/phone.

### 6.4 «Discuss channel exists але порожній (0 members)»

Canonical behaviour: нова розмова з черги — 0 members до pickup. Оператор кликає на запис → `action_open_discuss` додає його.

Якщо треба вручну додати себе:
```bash
docker exec -i campscout_web /usr/bin/odoo shell -d campscout --no-http << 'EOF'
connect = env['sendpulse.connect'].sudo().browse(<REC_ID>)
connect.action_open_discuss()
env.cr.commit()
EOF
```

### 6.5 «Site 502 після upgrade»

Типові причини:
1. **Синтаксична помилка у Python/XML** — перевірити `docker logs campscout_web --tail 100`
2. **Missing field у БД** — upgrade не встиг applyнути — перезапустити upgrade
3. **Wrong addons_path** — перевірити `/opt/campscout/config/odoo.conf` `addons_path`
4. **DB password issue** — див. INC-012, 014 у LOG.md (відсутній пароль в `odoo.conf` після ротації)

---

## 7. Reference: команди

```bash
# SSH
ssh campscout

# Логи Odoo (реалтайм)
ssh campscout "docker logs -f campscout_web --tail 100"

# Odoo shell (інтерактивно)
ssh campscout "docker exec -it campscout_web /usr/bin/odoo shell -d campscout --no-http"

# Відновлення контейнера після аварії
ssh campscout "cd /opt/campscout && docker compose up -d web && docker compose restart web"

# Force rebuild registry
ssh campscout "cd /opt/campscout && docker compose restart web"

# Запуск cron вручну (приклад)
ssh campscout "docker exec -i campscout_web /usr/bin/odoo shell -d campscout --no-http" << 'EOF'
env['sendpulse.connect'].sudo().cron_check_fb_token_expiry()
env.cr.commit()
EOF

# Backup БД
ssh campscout "docker exec campscout_db pg_dump -U odoo campscout | gzip > /opt/campscout/backup/db_$(date +%Y%m%d).sql.gz"
```

---

*Всі зміни інфраструктури логуються у `DevJournal/sessions/LOG.md`. Підозрілі падіння → postmortem у `docs/CRITICAL_INCIDENT_*.md`.*
