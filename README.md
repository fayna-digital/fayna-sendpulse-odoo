# Odoo 17 Integracja SendPulse — AI + Lead Magnet + Multi-Page FB/IG

![Odoo Version](https://img.shields.io/badge/Odoo-17.0%20Community-purple)
![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Meta Graph](https://img.shields.io/badge/Meta%20Graph-v25.0-red)
![License](https://img.shields.io/badge/License-OPL--1-green.svg)
![Status](https://img.shields.io/badge/Status-Production-brightgreen)

**Opracowane przez [Fayna Digital](https://www.fayna.agency) dla CampScout**
**Autor: Volodymyr Shevchenko**

---

Dwukierunkowy most **SendPulse ↔ Odoo Discuss** z asystentem AI dla operatorów, flow lead magnet (PDF-katalog + SMS-kupon), świadomością dostępności miejsc na wydarzeniach, kampaniami drip, testowaniem A/B szablonów, automatycznym tłumaczeniem oraz obsługą wielu stron Facebook/Instagram z klasyfikacją komentarzy przez LLM. **Auto-tworzenie crm.lead** z czatu (gdy klient odpowiedział) — lead trafia do lejka Sales **bez przypisanego opiekuna** (pula + claim), aby dwóch menedżerów nie prowadziło jednego klienta. Zobacz [docs/TZ_F4_ENABLE_LEAD.md](docs/TZ_F4_ENABLE_LEAD.md).

Referencyjne wdrożenie: [CampScout](https://campscout.eu) — dziecięce obozy w Polsce.

---

## Możliwości

- **Jedna skrzynka** — Telegram / Instagram / Facebook / Messenger / Viber / WhatsApp / LiveChat / TikTok — wszystko trafia do jednego `mail.channel` w Odoo Discuss
- **Wiele stron FB/IG** — 11 stron Facebook + 7 Instagram przez tokeny System User; przeszło Meta App Review 2026-04-20
- **Asystent AI dla operatora** — Claude Haiku 4.5 generuje odpowiedzi w panelu bocznym Discuss (komponent OWL)
- **Flow lead magnet** — email → brandowany PDF-katalog; telefon → SMS-kupon z puli `loyalty.program`
- **Dostępność miejsc na wydarzeniach** — AI otrzymuje rzeczywistą liczbę `seats_available` dla każdego obozu → uczciwy FOMO lub wiadomość zapasowa
- **Kampanie drip** — przypomnienia po 6 h / 24 h z weryfikacją cooldown i zgody
- **Publiczne szablony A/B** — wybór epsilon-greedy ze śledzeniem konwersji wariantów
- **Automatyczne tłumaczenie** — UA ↔ PL przez Claude, bezpośrednio w Discuss
- **Autoodpowiedź FAQ RAG** — Claude z progiem pewności automatycznie wysyła bezpieczne odpowiedzi
- **Klasyfikator komentarzy** — 8 kategorii (pytanie, skarga, spam, pochwała itd.) przez LLM + routing alertów do Telegram
- **RODO/GDPR** — każde zdarzenie zgody rejestrowane w `sendpulse.privacy.consent.log` (dziennik append-only z ochroną przed modyfikacją)

---

## Architektura

```
sendpulse-odoo/
├── models/
│   ├── sendpulse_connect.py              # Model główny — jedna rozmowa na rekord (~4000 linii)
│   ├── sendpulse_message.py              # Dziennik wiadomości
│   ├── sendpulse_facebook_page.py        # Stan dla wielu stron FB/IG
│   ├── sendpulse_faq_entry.py            # Baza wiedzy FAQ dla RAG
│   ├── sendpulse_public_template.py      # Publiczne szablony A/B + konwersje
│   ├── sendpulse_identify_wizard.py      # Kreator ręcznego powiązania z partnerem
│   ├── sendpulse_privacy_consent_log.py  # Dziennik zgód RODO (append-only)
│   ├── res_config_settings.py            # Ustawienia modułu
│   ├── res_partner.py                    # Rozszerzenie partnera (UTM, historia kanałów)
│   └── mail_channel.py                   # Rozszerzenie kanału Discuss
├── controllers/
│   └── main.py                           # SendPulse webhook + Meta Graph callbacks
├── views/
│   ├── sendpulse_connect_views.xml       # Kanban, formularz, lista, panel boczny Discuss
│   └── ...
├── data/
│   ├── sendpulse_data.xml                # Menu + akcje
│   ├── sendpulse_faq_seed.xml            # Początkowe wpisy FAQ
│   ├── mail_template_lead_magnet.xml     # Brandowany email dla lead magnet
│   └── clean_data_cron.xml               # Harmonogram auto-czyszczenia
├── static/src/
│   ├── components/                       # Komponenty OWL (panel AI, panel informacyjny)
│   └── scss/
└── docs/
    ├── INDEX.md                          # Nawigacja po dokumentacji
    ├── ARCHITECTURE.md
    ├── CONFIGURATION.md
    ├── DEPLOYMENT.md
    └── TZ_V2_AUTOMATION.md
```

---

## Stos technologiczny

| Komponent | Technologia |
|-----------|-----------|
| Framework ERP | Odoo 17.0 Community |
| Główne zależności | `mail`, `contacts`, `crm`, `web` |
| Dostawca komunikatorów | SendPulse Chatbot API + webhooks |
| Graf społecznościowy | Meta Graph API v25.0 (przez tokeny System User) |
| AI | Claude Haiku 4.5 (Anthropic API) |
| SMS | TurboSMS (przez `kw_sms_api`) |
| Strategia ponowień | Exponential backoff, dziennik audytu przez ir.logging |
| Race-safety | PostgreSQL advisory lock + partial unique index |
| Wersja modułu | 17.0.1.15.14 |
| Licencja | OPL-1 (Odoo Proprietary) |

---

## Instalacja

### 1. Klonowanie do custom-addons

```bash
cd /opt/<client>/custom-addons
git clone https://github.com/fayna-digital/fayna-sendpulse-odoo.git odoo_chatwoot_connector
```

> **Uwaga:** techniczna nazwa katalogu — `odoo_chatwoot_connector` (z przyczyn historycznych po zmianie nazwy repo). Techniczna nazwa modułu Odoo pozostaje `odoo_chatwoot_connector` w manifeście.

### 2. Instalacja modułu

```bash
docker exec <client>_web odoo -c /etc/odoo/odoo.conf -d <db> \
    -i odoo_chatwoot_connector --stop-after-init --no-http
```

Lub przez UI: **Aplikacje → Zaktualizuj listę aplikacji → szukaj `SendPulse` → Zainstaluj**.

### 3. Restart Odoo

```bash
docker restart <client>_web
```

---

## Konfiguracja

### Krok 1 — Dane logowania SendPulse

1. Zaloguj się na [login.sendpulse.com](https://login.sendpulse.com) → **Ustawienia → REST API**
2. Skopiuj **ID** i **Secret**
3. W Odoo: **Ustawienia → Techniczne → Parametry systemowe** (wymagany tryb deweloperski):

| Klucz | Wartość |
|-----|-------|
| `sendpulse.api_id` | Twoje SendPulse REST API ID |
| `sendpulse.api_secret` | Twój SendPulse REST API Secret |
| `sendpulse.webhook_secret` | losowy ciąg (wspólny z konfiguracją webhook) |

### Krok 2 — URL webhook w SendPulse

W panelu SendPulse → **Chatbot → Ustawienia → Webhook**:

- URL: `https://<your-odoo>.com/sendpulse/webhook`
- Zdarzenia: `income_message`, `outcome_message`, `bot_comment` (jeśli używany FB)

### Krok 3 — Meta App dla FB/IG (opcjonalnie)

Zobacz [docs/CONFIGURATION.md](docs/CONFIGURATION.md) dla pełnego flow z Meta App Review i konfiguracją System User.

### Krok 4 — Dane logowania AI

| Klucz | Wartość |
|-----|-------|
| `sendpulse.anthropic_api_key` | Anthropic API key dla Claude |
| `sendpulse.claude_model` | `claude-haiku-4-5-20251001` (domyślnie) |

### Krok 5 — TurboSMS (dla SMS-kuponów)

Skonfiguruj dostawcę `kw_sms_api` z danymi TurboSMS — zobacz `campscout-management/docs/DEPLOYMENT.md`.

---

## Użycie

### Operator otrzymuje czat

1. Klient pisze na dowolnym podłączonym kanale (np. Telegram)
2. Webhook trafia na `/sendpulse/webhook`
3. Tworzony jest `sendpulse.connect` (wątek), powiązany z `mail.channel`
4. Operator widzi wiadomość w Odoo Discuss z kartą informacji o partnerze
5. Operator odpowiada — most wysyła przez SendPulse API → z powrotem do Telegram

### Uruchomienie lead magnet

1. Otwórz rekord `sendpulse.connect` w panelu bocznym
2. Kliknij **Wyślij PDF-katalog** → poprosi o email (lub uzupełni automatycznie, jeśli wykryty)
3. Moduł:
   - Wysyła brandowany PDF przez AWS SES
   - Rejestruje zgodę w `sendpulse.privacy.consent.log` z `purpose='lead_magnet_email'`
   - Aktualizuje czat potwierdzeniem

### Odpowiedzi AI

1. W trybie deweloperskim w panelu bocznym Discuss pojawia się przycisk „Wygeneruj odpowiedź AI"
2. Claude Haiku otrzymuje:
   - Ostatnie 20 wiadomości rozmowy
   - Segment RFM partnera
   - Kontekst dostępności miejsc (komunikat FOMO, jeśli < 30%)
   - Top-3 wpisy FAQ RAG
3. Operator przegląda, edytuje, wysyła

Zobacz [docs/TZ_V2_AUTOMATION.md](docs/TZ_V2_AUTOMATION.md) dla wszystkich zautomatyzowanych flow.

---

## RODO / GDPR — Dziennik zgód

Każde wywołanie `sendpulse.privacy.consent.log.record_consent()` tworzy append-only rekord w `sendpulse.privacy.consent.log` — prawnie chroniony dziennik z blokadą modyfikacji i usunięcia.

```python
# Wewnętrzny flow, automatycznie:
self.env['sendpulse.privacy.consent.log'].record_consent(
    purpose='lead_magnet_email',
    channel='email',
    email=email,
    partner_id=partner.id,
    exact_response=user_text,
    source='sendpulse_chat',
)
```

Automatyzacja przez `base.automation`:
- Dodanie do `mail.blacklist` → automatyczny zapis wycofania (withdrawal) w dzienniku RODO

---

## Webhook Flow (technicznie)

```
1. SendPulse otrzymuje wiadomość od kanału klienta (Telegram/IG/FB/…)
2. POST https://<odoo>/sendpulse/webhook z podpisanym payload
3. sendpulse/controllers/main.py:
   a. Weryfikacja podpisu (HMAC-SHA256 z webhook_secret)
   b. Deduplikacja po (service + sendpulse_contact_id + timestamp)
   c. Advisory lock na (contact_id, service) dla ochrony przed race condition
4. Utworzenie lub aktualizacja rekordu sendpulse.connect (wątek)
5. Utworzenie rekordu sendpulse.message (dziennik)
6. Duplikacja do mail.channel (Discuss):
   a. Nowy kontakt → utworzenie kanału
   b. Publikacja wiadomości przez mail.channel._message_post_feedback()
7. Uruchomienie zadania AI wg warunków (zgodność FAQ, harmonogram drip)
8. Zwrot 200 OK
```

---

## Meta Graph API Flow (technicznie)

```
1. Klient komentuje publikację na Facebook Page
2. Działa webhook subskrypcji strony → /sendpulse/webhook/meta
3. Pobranie page_access_token z sendpulse.facebook.page (11 stron w pracy)
4. Pobranie pełnego tekstu komentarza przez Graph API v25.0
5. Klasyfikacja przez LLM (8 kategorii: pytanie/spam/pochwała/…)
6. Routing:
   - Kategoria 'question' → autoodpowiedź przez Graph API send_message
   - Kategoria 'spam' → ukrycie komentarza
   - Kategoria 'complaint' → alert Telegram do dyżurnego menedżera
7. Zapis w ir.logging (audyt)
```

---

## Rozwój lokalny

```bash
git clone https://github.com/fayna-digital/fayna-sendpulse-odoo.git
cd fayna-sendpulse-odoo

# Uruchomienie tymczasowego Odoo z podłączonym modułem:
docker run -d --name test_odoo -v $(pwd)/..:/mnt/custom-addons \
    -p 8069:8069 odoo:17

# Symulacja SendPulse webhook:
curl -X POST http://localhost:8069/sendpulse/webhook \
    -H "Content-Type: application/json" \
    -d '{"service": "telegram", "contact": {...}, "message": {...}}'
```

Zobacz [docs/CONFIGURATION.md](docs/CONFIGURATION.md) dla konfiguracji sekretów deweloperskich.

---

## Rozwiązywanie problemów

| Błąd | Przyczyna | Rozwiązanie |
|-------|-------|-----|
| `ValueError: Invalid field 'sent_at' on model 'sendpulse.message'` | Stary błąd — pole `date`, nie `sent_at` | Naprawione w v17.0.13.1; jeśli widzisz — zaktualizuj moduł |
| Weryfikacja podpisu nie przechodzi | Niezgodność webhook secret | Zsynchronizuj `sendpulse.webhook_secret` między Odoo a panelem SendPulse |
| Duplikaty `sendpulse.connect` dla tego samego kontaktu | Brak advisory lock / partial unique index | v17.0.10.x dodał `_sendpulse_dedup_idx`, upewnij się że aktualizacja przeszła |
| Błąd Meta Graph 401 | Token System User wygasł lub token strony odwołany | Cotygodniowy cron sprawdza tokeny; ponownie autoryzuj w Meta Business Settings |
| Panel AI nie renderuje się w Discuss | Zbuforowany bundle OWL | Twarde odświeżenie (Ctrl+Shift+R); jeśli nie pomaga — wyczyść cache przez `odoo shell` → `self.env['ir.qweb']._clear_cache()` |
| Email lead magnet nie wysyła się | AWS SES sandbox (tylko zweryfikowani odbiorcy) | Poproś o dostęp produkcyjny SES; lub dodaj odbiorców do whitelist |

---

## Dostęp operatorów

Standardowy model dostępu Odoo Discuss — nie jest potrzebna osobna grupa modułu. Wszyscy użytkownicy z `mail.group_user` mogą:

- Przeglądać wiadomości przychodzące podłączonych kanałów
- Odpowiadać w wątkach
- Przeglądać panel boczny partnera

**Admin modułu** (`group_omnichannel_admin` w `sendpulse-odoo`) dodatkowo:

- Konfiguruje dane logowania SendPulse
- Zarządza stronami FB/IG
- Edytuje wpisy FAQ
- Przegląda dzienniki LLM

---

## Ekosystem modułów

Ten moduł jest częścią stosu Odoo Fayna Digital:

| Moduł powiązany | Związek |
|----------------|--------------|
| [fayna-omnichannel-bridge](https://github.com/fayna-digital/fayna-omnichannel-bridge) | Abstrakcyjny agregator komunikatorów — sendpulse-odoo jest jednym z adapterów |
| [fayna-zadarma-odoo](https://github.com/fayna-digital/fayna-zadarma-odoo) | Kanał głosowy (uzupełnia komunikatory) |
| [fayna-campscout](https://github.com/fayna-digital/fayna-campscout) | Warstwa pionowa CampScout — używa sendpulse-odoo dla wszystkich chat flow |

Dokumentacja architektury: `fayna-digital-docs` (repozytorium prywatne, dostęp wewnętrzny).

---

## Licencja

OPL-1 (Odoo Proprietary License v1.0) — zobacz [LICENSE](LICENSE)

---

*Opracowane przez [Fayna Digital](https://www.fayna.agency) · Volodymyr Shevchenko*
