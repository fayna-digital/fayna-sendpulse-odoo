#!/usr/bin/env python3
"""Fill in real uk/pl translations for the newly added strings.

Reads the merged .po files and fills empty msgstr entries from a
translation dictionary. Strings that must stay identical (URLs, provider
names, placeholders) are mapped to themselves.

Usage: python3 tools/fill_translations.py
"""

import polib

BASE = 'addons/fayna_channel_bridge/i18n'

# msgid -> (uk, pl)
TRANS = {
    # --- URLs / placeholders / proper names: keep as-is ---
    'https://apps.odoo.com/': ('https://apps.odoo.com/', 'https://apps.odoo.com/'),
    'https://business.whatsapp.com/': (
        'https://business.whatsapp.com/',
        'https://business.whatsapp.com/',
    ),
    'https://core.telegram.org/bots#6-botfather': (
        'https://core.telegram.org/bots#6-botfather',
        'https://core.telegram.org/bots#6-botfather',
    ),
    'https://developers.facebook.com/docs/instagram-platform': (
        'https://developers.facebook.com/docs/instagram-platform',
        'https://developers.facebook.com/docs/instagram-platform',
    ),
    'https://developers.facebook.com/docs/messenger-platform': (
        'https://developers.facebook.com/docs/messenger-platform',
        'https://developers.facebook.com/docs/messenger-platform',
    ),
    'https://developers.tiktok.com/': (
        'https://developers.tiktok.com/',
        'https://developers.tiktok.com/',
    ),
    'https://partners.viber.com/': (
        'https://partners.viber.com/',
        'https://partners.viber.com/',
    ),
    '123456789:AA... (token from BotFather)': (
        '123456789:AA... (токен від BotFather)',
        '123456789:AA... (token z BotFather)',
    ),
    'Token from Viber Admin Panel': (
        'Токен з Viber Admin Panel',
        'Token z Viber Admin Panel',
    ),
    'EEA/EU, USA': ('ЄЕЗ/ЄС, США', 'EOG/UE, USA'),
    'Telegram': ('Telegram', 'Telegram'),
    'Viber': ('Viber', 'Viber'),
    'Email': ('Email', 'E-mail'),
    'SMS': ('SMS', 'SMS'),
    'LinkedIn': ('LinkedIn', 'LinkedIn'),
    'Facebook Messenger': ('Facebook Messenger', 'Facebook Messenger'),
    'Instagram': ('Instagram', 'Instagram'),
    'TikTok': ('TikTok', 'TikTok'),
    'WhatsApp': ('WhatsApp', 'WhatsApp'),
    'Telegram personal': ('Telegram особистий', 'Telegram osobisty'),
    'Viber personal': ('Viber особистий', 'Viber osobisty'),
    'Telegram особистий': ('Telegram особистий', 'Telegram osobisty'),
    'Viber особистий': ('Viber особистий', 'Viber osobisty'),
    'LinkedIn Chatbots': ('LinkedIn Chatbots', 'LinkedIn Chatbots'),
    '\n            https://www.odoo.com/documentation/17.0/applications/general/email_communication.html': (
        '\n            https://www.odoo.com/documentation/17.0/applications/general/email_communication.html',
        '\n            https://www.odoo.com/documentation/17.0/applications/general/email_communication.html',
    ),
    # --- OWL UI strings ---
    'Connect channels': ('Підключити канали', 'Podłącz kanały'),
    'Loading…': ('Завантаження…', 'Ładowanie…'),
    'Main': ('Основні', 'Główne'),
    'Marketplace integrations': (
        'Інтеграції з маркетплейсу',
        'Integracje z marketplace',
    ),
    'Marketplace': ('Маркетплейс', 'Marketplace'),
    'Disconnect': ("Від'єднати", 'Rozłącz'),
    'Disconnect %s?': ("Від'єднати %s?", 'Rozłączyć %s?'),
    'Learn more': ('Докладніше', 'Dowiedz się więcej'),
    'Live Chat (Odoo)': ('Live Chat (Odoo)', 'Live Chat (Odoo)'),
    'User consent required': (
        'Потрібна згода користувача',
        'Wymagana zgoda użytkownika',
    ),
    'Not configured': ('Не налаштовано', 'Nieskonfigurowane'),
    'Needs attention': ('Потребує уваги', 'Wymaga uwagi'),
    'Working': ('Працює', 'Działa'),
    'Preconditions are not confirmed.': (
        'Передумови не підтверджено.',
        'Warunki wstępne nie zostały potwierdzone.',
    ),
    'Channel %s is handled natively by Odoo — configure it in the Odoo settings.': (
        'Канал %s обробляється штатно Odoo — налаштуйте його в налаштуваннях Odoo.',
        'Kanał %s jest obsługiwany natywnie przez Odoo — skonfiguruj go w ustawieniach Odoo.',
    ),
    'Channel %s does not require connecting — just embed the widget or configure it in Odoo settings.': (
        'Канал %s не потребує підключення — просто вбудуйте віджет або налаштуйте його в налаштуваннях Odoo.',
        'Kanał %s nie wymaga podłączenia — wystarczy osadzić widget lub skonfigurować go w ustawieniach Odoo.',
    ),
    'This channel will be disconnected and messages will stop flowing. You can reconnect it later.': (
        "Цей канал буде від'єднано, і повідомлення перестануть надходити. Ви зможете підключити його пізніше.",
        'Ten kanał zostanie rozłączony, a wiadomości przestaną napływać. Możesz go później ponownie podłączyć.',
    ),
    # --- Connect button labels ---
    'Connect Telegram': ('Підключити Telegram', 'Podłącz Telegram'),
    'Connect Messenger': ('Підключити Messenger', 'Podłącz Messenger'),
    'Connect WhatsApp': ('Підключити WhatsApp', 'Podłącz WhatsApp'),
    'Connect Instagram': ('Підключити Instagram', 'Podłącz Instagram'),
    'Connect TikTok': ('Підключити TikTok', 'Podłącz TikTok'),
    'Connect Viber': ('Підключити Viber', 'Podłącz Viber'),
    'Open Email settings': ('Відкрити налаштування Email', 'Otwórz ustawienia e-mail'),
    'Open SMS settings': ('Відкрити налаштування SMS', 'Otwórz ustawienia SMS'),
    'Go to marketplace': ('Перейти до маркетплейсу', 'Przejdź do marketplace'),
    # --- Fallback labels ---
    'How to get a token': ('Як отримати токен', 'Jak uzyskać token'),
    'Messenger Platform docs': (
        'Документація Messenger Platform',
        'Dokumentacja Messenger Platform',
    ),
    'WhatsApp Business': ('WhatsApp Business', 'WhatsApp Business'),
    'Instagram Platform docs': (
        'Документація Instagram Platform',
        'Dokumentacja Instagram Platform',
    ),
    'TikTok for Developers': ('TikTok для розробників', 'TikTok dla deweloperów'),
    'Viber Admin Panel': ('Viber Admin Panel', 'Viber Admin Panel'),
    'Email docs': ('Документація Email', 'Dokumentacja e-mail'),
    'SMS docs': ('Документація SMS', 'Dokumentacja SMS'),
    # --- Value lines (what I get) ---
    'Receive and reply to customer messages right in Odoo.': (
        'Отримуйте та відповідайте на повідомлення клієнтів прямо в Odoo.',
        'Odbieraj i odpowiadaj na wiadomości klientów bezpośrednio w Odoo.',
    ),
    'Answer Messenger conversations without leaving Odoo.': (
        'Відповідайте на розмови Messenger, не виходячи з Odoo.',
        'Odpowiadaj na rozmowy Messenger bez wychodzenia z Odoo.',
    ),
    'Handle WhatsApp Business messages from one inbox.': (
        'Обробляйте повідомлення WhatsApp Business з однієї скриньки.',
        'Obsługuj wiadomości WhatsApp Business z jednej skrzynki.',
    ),
    'Reply to Instagram direct messages from Odoo.': (
        'Відповідайте на прямі повідомлення Instagram з Odoo.',
        'Odpowiadaj na wiadomości bezpośrednie Instagram z Odoo.',
    ),
    'Manage TikTok direct messages from Odoo.': (
        'Керуйте прямими повідомленнями TikTok з Odoo.',
        'Zarządzaj wiadomościami bezpośrednimi TikTok z Odoo.',
    ),
    'Answer Viber messages from the same inbox.': (
        'Відповідайте на повідомлення Viber з тієї самої скриньки.',
        'Odpowiadaj na wiadomości Viber z tej samej skrzynki.',
    ),
    'Turn customer emails into conversations in Odoo.': (
        'Перетворюйте електронні листи клієнтів на розмови в Odoo.',
        'Zamieniaj e-maile klientów na rozmowy w Odoo.',
    ),
    'Send and receive SMS through your existing SMS gateway.': (
        'Надсилайте та отримуйте SMS через наявний SMS-шлюз.',
        'Wysyłaj i odbieraj SMS-y przez istniejącą bramkę SMS.',
    ),
    'Connect your personal Telegram account via a marketplace app.': (
        'Підключіть особистий акаунт Telegram через застосунок з маркетплейсу.',
        'Podłącz osobiste konto Telegram przez aplikację z marketplace.',
    ),
    'Connect your personal Viber via a marketplace app.': (
        'Підключіть особистий Viber через застосунок з маркетплейсу.',
        'Podłącz osobisty Viber przez aplikację z marketplace.',
    ),
    'Automate LinkedIn conversations with chatbot flows.': (
        'Автоматизуйте розмови LinkedIn за допомогою чат-ботів.',
        'Automatyzuj rozmowy LinkedIn za pomocą chatbotów.',
    ),
    # --- Permission lines (what I give) ---
    'You give access to the bot you create in BotFather.': (
        'Ви надаєте доступ до бота, якого створили в BotFather.',
        'Udzielasz dostępu do bota utworzonego w BotFather.',
    ),
    'You give access to your Facebook page and its messages.': (
        'Ви надаєте доступ до своєї сторінки Facebook та її повідомлень.',
        'Udzielasz dostępu do swojej strony Facebook i jej wiadomości.',
    ),
    'You give access to your WhatsApp Business account.': (
        'Ви надаєте доступ до свого акаунта WhatsApp Business.',
        'Udzielasz dostępu do swojego konta WhatsApp Business.',
    ),
    'You give access to your Instagram business account.': (
        'Ви надаєте доступ до свого бізнес-акаунта Instagram.',
        'Udzielasz dostępu do swojego konta biznesowego Instagram.',
    ),
    'You give access to your TikTok business account.': (
        'Ви надаєте доступ до свого бізнес-акаунта TikTok.',
        'Udzielasz dostępu do swojego konta biznesowego TikTok.',
    ),
    'You give access to the bot you create in the Viber Admin\n            Panel.': (
        'Ви надаєте доступ до бота, якого створили в Viber Admin\n            Panel.',
        'Udzielasz dostępu do bota utworzonego w Viber Admin\n            Panel.',
    ),
    'You give access to the mailbox used for incoming mail.': (
        'Ви надаєте доступ до поштової скриньки, яка використовується для вхідної пошти.',
        'Udzielasz dostępu do skrzynki pocztowej używanej do poczty przychodzącej.',
    ),
    'You give access to your SMS gateway account.': (
        'Ви надаєте доступ до свого акаунта SMS-шлюзу.',
        'Udzielasz dostępu do swojego konta bramki SMS.',
    ),
    'You give access to your personal Telegram account.': (
        'Ви надаєте доступ до свого особистого акаунта Telegram.',
        'Udzielasz dostępu do swojego osobistego konta Telegram.',
    ),
    'You give access to your personal Viber account.': (
        'Ви надаєте доступ до свого особистого акаунта Viber.',
        'Udzielasz dostępu do swojego osobistego konta Viber.',
    ),
    'You give access to your LinkedIn company page.': (
        'Ви надаєте доступ до своєї сторінки компанії LinkedIn.',
        'Udzielasz dostępu do swojej strony firmy na LinkedIn.',
    ),
    # --- Descriptions ---
    'Official Telegram messenger. Connection via a bot token\n            created in BotFather.': (
        'Офіційний месенджер Telegram. Підключення через токен бота,\n            створеного в BotFather.',
        'Oficjalny komunikator Telegram. Połączenie przez token bota\n            utworzonego w BotFather.',
    ),
    'Facebook Messenger messages. Connection via\n            Facebook OAuth authorization.': (
        'Повідомлення Facebook Messenger. Підключення через\n            авторизацію Facebook OAuth.',
        'Wiadomości Facebook Messenger. Połączenie przez\n            autoryzację Facebook OAuth.',
    ),
    'WhatsApp Business Platform. Connection via\n            Meta OAuth authorization.': (
        'Платформа WhatsApp Business. Підключення через\n            авторизацію Meta OAuth.',
        'Platforma WhatsApp Business. Połączenie przez\n            autoryzację Meta OAuth.',
    ),
    'Instagram direct messages. Connection via\n            Meta OAuth authorization.': (
        'Прямі повідомлення Instagram. Підключення через\n            авторизацію Meta OAuth.',
        'Wiadomości bezpośrednie Instagram. Połączenie przez\n            autoryzację Meta OAuth.',
    ),
    'TikTok direct messages. Connection via TikTok\n            OAuth authorization.': (
        'Прямі повідомлення TikTok. Підключення через\n            авторизацію TikTok OAuth.',
        'Wiadomości bezpośrednie TikTok. Połączenie przez\n            autoryzację TikTok OAuth.',
    ),
    'Viber messenger. Connection via a bot token from the Viber\n            Admin Panel.': (
        'Месенджер Viber. Підключення через токен бота з Viber\n            Admin Panel.',
        'Komunikator Viber. Połączenie przez token bota z Viber\n            Admin Panel.',
    ),
    'Email is handled natively by Odoo: configure the incoming\n            and outgoing mail servers in the Odoo settings.': (
        'Email обробляється штатно Odoo: налаштуйте вхідні\n            та вихідні поштові сервери в налаштуваннях Odoo.',
        'E-mail jest obsługiwany natywnie przez Odoo: skonfiguruj serwery\n            poczty przychodzącej i wychodzącej w ustawieniach Odoo.',
    ),
    'SMS is handled by the fayna_sms_base and fayna_sms_turbosms\n            modules. Configure the gateway in the Odoo settings.': (
        'SMS обробляється модулями fayna_sms_base та fayna_sms_turbosms.\n            Налаштуйте шлюз у налаштуваннях Odoo.',
        'SMS jest obsługiwane przez moduły fayna_sms_base i fayna_sms_turbosms.\n            Skonfiguruj bramkę w ustawieniach Odoo.',
    ),
    'Personal Telegram integration available from the Odoo\n            marketplace.': (
        'Особиста інтеграція Telegram доступна з маркетплейсу\n            Odoo.',
        'Osobista integracja Telegram dostępna z marketplace\n            Odoo.',
    ),
    'Personal Viber integration available from the Odoo marketplace.': (
        'Особиста інтеграція Viber доступна з маркетплейсу Odoo.',
        'Osobista integracja Viber dostępna z marketplace Odoo.',
    ),
    'LinkedIn chatbot integration available from the Odoo marketplace.': (
        'Інтеграція чат-ботів LinkedIn доступна з маркетплейсу Odoo.',
        'Integracja chatbotów LinkedIn dostępna z marketplace Odoo.',
    ),
    # --- Preconditions ---
    'Create a bot in BotFather and get a token.': (
        'Створіть бота в BotFather та отримайте токен.',
        'Utwórz bota w BotFather i uzyskaj token.',
    ),
    'A Facebook page and a Meta developer app.': (
        'Сторінка Facebook та застосунок розробника Meta.',
        'Strona Facebook i aplikacja deweloperska Meta.',
    ),
    'A WhatsApp Business Account verified by Meta.': (
        'Акаунт WhatsApp Business, підтверджений Meta.',
        'Konto WhatsApp Business zweryfikowane przez Meta.',
    ),
    'An Instagram business account linked to a\n            Facebook page.': (
        "Бізнес-акаунт Instagram, прив'язаний до\n            сторінки Facebook.",
        'Konto biznesowe Instagram powiązane ze\n            stroną Facebook.',
    ),
    'A TikTok business account.': ('Бізнес-акаунт TikTok.', 'Konto biznesowe TikTok.'),
    'Create a bot in the Viber Admin Panel and get a token.': (
        'Створіть бота в Viber Admin Panel та отримайте токен.',
        'Utwórz bota w Viber Admin Panel i uzyskaj token.',
    ),
    'A mailbox and its IMAP/SMTP credentials.': (
        'Поштова скринька та її облікові дані IMAP/SMTP.',
        'Skrzynka pocztowa i jej dane logowania IMAP/SMTP.',
    ),
    'An SMS gateway account (e.g. TurboSMS).': (
        'Акаунт SMS-шлюзу (напр., TurboSMS).',
        'Konto bramki SMS (np. TurboSMS).',
    ),
    # --- Warnings ---
    'Paid plan: a fee is charged per message.': (
        'Платний тариф: стягується плата за кожне повідомлення.',
        'Plan płatny: pobierana jest opłata za każdą wiadomość.',
    ),
    'After connecting you lose control over conversations\n            from the WhatsApp mobile app.': (
        'Після підключення ви втрачаєте контроль над розмовами\n            з мобільного застосунку WhatsApp.',
        'Po podłączeniu tracisz kontrolę nad rozmowami\n            z aplikacji mobilnej WhatsApp.',
    ),
    # --- Field descriptions / help / selection labels ---
    'Connect button label': (
        'Текст кнопки підключення',
        'Etykieta przycisku podłączenia',
    ),
    'Fallback link label': ('Текст запасного посилання', 'Etykieta linku zapasowego'),
    'Fallback link URL': ('URL запасного посилання', 'URL linku zapasowego'),
    'Label of the single primary button (defaults to "Connect").': (
        'Текст єдиної головної кнопки (за замовчуванням — «Підключити»).',
        'Etykieta pojedynczego głównego przycisku (domyślnie „Podłącz”).',
    ),
    'Label of the fallback link (defaults to "Learn more").': (
        'Текст запасного посилання (за замовчуванням — «Докладніше»).',
        'Etykieta linku zapasowego (domyślnie „Dowiedz się więcej”).',
    ),
    'URL of the fallback link (help / manual setup instructions).': (
        'URL запасного посилання (довідка / інструкція ручного налаштування).',
        'URL linku zapasowego (pomoc / instrukcja ręcznej konfiguracji).',
    ),
    'Value line': ('Рядок вигоди', 'Linia wartości'),
    'Permission line': ('Рядок дозволу', 'Linia uprawnień'),
    'One line: "what I get" (benefit of connecting this channel).': (
        'Один рядок: «що я отримаю» (вигода від підключення цього каналу).',
        'Jedna linia: „co otrzymuję” (korzyść z podłączenia tego kanału).',
    ),
    'One line: "what I give" (permissions the channel requires).': (
        'Один рядок: «що я віддаю» (дозволи, які вимагає канал).',
        'Jedna linia: „co udostępniam” (uprawnienia wymagane przez kanał).',
    ),
    'Panel category': ('Категорія панелі', 'Kategoria panelu'),
    'State': ('Стан', 'Stan'),
    'State label': ('Текст стану', 'Etykieta stanu'),
    'Has credentials': ('Має облікові дані', 'Ma dane logowania'),
    'Native (Odoo)': ('Штатний (Odoo)', 'Natywny (Odoo)'),
    'External (marketplace)': ('Зовнішній (маркетплейс)', 'Zewnętrzny (marketplace)'),
    'Settings': ('Налаштування', 'Ustawienia'),
    'Instagram Account ID': ('ID акаунта Instagram', 'ID konta Instagram'),
    'Instagram Business Account ID linked to the parent Facebook page (used by the Instagram channel, which reuses the parent page token).': (
        "ID бізнес-акаунта Instagram, прив'язаного до батьківської сторінки Facebook (використовується каналом Instagram, який перевикористовує токен батьківської сторінки).",
        'ID konta biznesowego Instagram powiązanego z nadrzędną stroną Facebook (używane przez kanał Instagram, który ponownie wykorzystuje token strony nadrzędnej).',
    ),
    'Bot/page ID at the provider (to distinguish several bots of one channel)': (
        'ID бота/сторінки у провайдера (щоб розрізняти кількох ботів одного каналу)',
        'ID bota/strony u dostawcy (aby odróżnić kilku botów jednego kanału)',
    ),
    'User ID at the provider (chat_id for Telegram, PSID for Messenger, etc.)': (
        'ID користувача у провайдера (chat_id для Telegram, PSID для Messenger тощо)',
        'ID użytkownika u dostawcy (chat_id dla Telegram, PSID dla Messenger itd.)',
    ),
    'Telegram Bot Token (api.telegram.org/bot<TOKEN>). Stored in plain text (administrators only).': (
        'Токен бота Telegram (api.telegram.org/bot<TOKEN>). Зберігається у відкритому вигляді (лише для адміністраторів).',
        'Token bota Telegram (api.telegram.org/bot<TOKEN>). Przechowywany w postaci zwykłego tekstu (tylko administratorzy).',
    ),
    'JSON with provider tokens/keys. Stored in plain text (administrators only).': (
        'JSON з токенами/ключами провайдера. Зберігається у відкритому вигляді (лише для адміністраторів).',
        'JSON z tokenami/kluczami dostawcy. Przechowywany w postaci zwykłego tekstu (tylko administratorzy).',
    ),
    'Webhook signing secret (for Meta X-Hub-Signature-256, Viber Auth-Token)': (
        'Секрет підпису вебхука (для Meta X-Hub-Signature-256, Viber Auth-Token)',
        'Sekret podpisu webhooka (dla Meta X-Hub-Signature-256, Viber Auth-Token)',
    ),
    'Unique identifier of the Telegram webhook path (generated automatically, does not contain the bot token).': (
        'Унікальний ідентифікатор шляху вебхука Telegram (генерується автоматично, не містить токена бота).',
        'Unikalny identyfikator ścieżki webhooka Telegram (generowany automatycznie, nie zawiera tokena bota).',
    ),
    'Optional restriction: accept messages only from contacts with this email domain.': (
        "Необов'язкове обмеження: приймати повідомлення лише від контактів із цим доменом електронної пошти.",
        'Opcjonalne ograniczenie: przyjmuj wiadomości tylko od kontaktów z tej domeny e-mail.',
    ),
    'Time of the next retry attempt (exponential backoff + jitter). Empty — try on the next cron pass.': (
        'Час наступної спроби повтору (експоненційний backoff + jitter). Порожньо — спробувати на наступному проході cron.',
        'Czas następnej próby ponowienia (wykładniczy backoff + jitter). Puste — spróbuj przy następnym przebiegu cron.',
    ),
    'Aggregated channel status: disabled / working / check not supported / error': (
        'Агрегований стан каналу: вимкнено / працює / перевірку не підтримано / помилка',
        'Zagregowany stan kanału: wyłączony / działa / sprawdzanie nieobsługiwane / błąd',
    ),
    # --- Group / security descriptions ---
    'Channel Bridge administrator. Full access to channel\n            settings.': (
        'Адміністратор Channel Bridge. Повний доступ до налаштувань\n            каналів.',
        'Administrator Channel Bridge. Pełny dostęp do ustawień\n            kanałów.',
    ),
    'Support operator. Reads channels and the message journal of own\n            transport.': (
        'Оператор підтримки. Читає канали та журнал повідомлень власного\n            транспорту.',
        'Operator wsparcia. Czyta kanały i dziennik wiadomości własnego\n            transportu.',
    ),
    # --- Help texts (long) ---
    'Channels appear after connecting via the "Connect channels" menu.\n                Here you can see the status of each channel, the transport priority\n                and the result of the last availability check.': (
        "Канали з'являються після підключення через меню «Підключити канали».\n                Тут ви бачите стан кожного каналу, пріоритет транспорту\n                та результат останньої перевірки доступності.",
        'Kanały pojawiają się po podłączeniu przez menu „Podłącz kanały”.\n                Tutaj widzisz stan każdego kanału, priorytet transportu\n                i wynik ostatniego sprawdzenia dostępności.',
    ),
    'Conversations appear automatically when a customer writes to a\n                connected channel (Telegram, Messenger, Viber, etc.). To start\n                replying — open the conversation and click "Open in Discuss".': (
        "Розмови з'являються автоматично, коли клієнт пише на\n                підключений канал (Telegram, Messenger, Viber тощо). Щоб почати\n                відповідати — відкрийте розмову та натисніть «Відкрити в Discuss».",
        'Rozmowy pojawiają się automatycznie, gdy klient pisze na\n                podłączony kanał (Telegram, Messenger, Viber itd.). Aby zacząć\n                odpowiadać — otwórz rozmowę i kliknij „Otwórz w Discuss”.',
    ),
    'The journal records messages that pass through the own transport\n                of the channels. Here you can see the direction, delivery status\n                and errors. The "Only errors" filter shows messages with the\n                "Error" status.': (
        'Журнал фіксує повідомлення, що проходять через власний транспорт\n                каналів. Тут ви бачите напрямок, статус доставки\n                та помилки. Фільтр «Лише помилки» показує повідомлення зі\n                статусом «Помилка».',
        'Dziennik rejestruje wiadomości przechodzące przez własny transport\n                kanałów. Tutaj widzisz kierunek, status dostarczenia\n                i błędy. Filtr „Tylko błędy” pokazuje wiadomości ze\n                statusem „Błąd”.',
    ),
    # --- Python messages ---
    'Channel %s does not use OAuth authorization.': (
        'Канал %s не використовує авторизацію OAuth.',
        'Kanał %s nie używa autoryzacji OAuth.',
    ),
    'Channel %s is configured in the Odoo settings.': (
        'Канал %s налаштовується в налаштуваннях Odoo.',
        'Kanał %s jest konfigurowany w ustawieniach Odoo.',
    ),
    'Channel %s is not connected through this screen.': (
        'Канал %s не підключається через цей екран.',
        'Kanał %s nie jest podłączany przez ten ekran.',
    ),
    'Connecting %s is done manually by the administrator. OAuth authorization is not implemented yet.': (
        'Підключення %s виконується вручну адміністратором. Авторизацію OAuth ще не реалізовано.',
        'Podłączanie %s odbywa się ręcznie przez administratora. Autoryzacja OAuth nie jest jeszcze zaimplementowana.',
    ),
    'Connecting %s requires OAuth authorization, which is not configured yet. Please set up the Meta app first.': (
        'Підключення %s потребує авторизації OAuth, яку ще не налаштовано. Спочатку налаштуйте застосунок Meta.',
        'Podłączenie %s wymaga autoryzacji OAuth, która nie jest jeszcze skonfigurowana. Najpierw skonfiguruj aplikację Meta.',
    ),
    'Could not connect the channel. Contact the administrator for diagnostics.': (
        'Не вдалося підключити канал. Зверніться до адміністратора для діагностики.',
        'Nie udało się podłączyć kanału. Skontaktuj się z administratorem w celu diagnostyki.',
    ),
    'Channel connected. The Viber webhook subscription must be activated separately in the Viber panel.': (
        'Канал підключено. Підписку на вебхук Viber потрібно активувати окремо в панелі Viber.',
        'Kanał podłączony. Subskrypcję webhooka Viber należy aktywować osobno w panelu Viber.',
    ),
    'Connect this channel now? The system will contact the provider to register the webhook.': (
        'Підключити цей канал зараз? Система звернеться до провайдера для реєстрації вебхука.',
        'Podłączyć ten kanał teraz? System skontaktuje się z dostawcą w celu rejestracji webhooka.',
    ),
}


def main():
    for lang in ('uk', 'pl'):
        path = f'{BASE}/{lang}.po'
        po = polib.pofile(path)
        filled = 0
        missing = []
        for entry in po:
            if entry.msgstr or entry.msgstr_plural:
                continue
            pair = TRANS.get(entry.msgid)
            if pair:
                entry.msgstr = pair[0] if lang == 'uk' else pair[1]
                filled += 1
            else:
                missing.append(entry.msgid)
        po.save(path)
        print(f'{lang}: filled {filled}, still missing {len(missing)}')
        for m in missing:
            print(f'  MISSING: {m!r}')


if __name__ == '__main__':
    main()
