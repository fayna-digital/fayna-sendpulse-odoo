# Критична ситуація — втручання AI-асистента в репозиторій SendPulse (2026-04-09)

<div style="color:#b00020; border:2px solid #b00020; padding:14px 18px; margin:0 0 20px; background:#fff8f8;">

**Статус: КРИТИЧНИЙ ІНЦИДЕНТ (червоний рівень)**  
**Тип:** порушення межі модуля, невиконання явної вимоги замовника, зайві зміни в бойовому аддоні.  
**Суб’єкт змін:** не людина-розробник модуля, а **сесія AI-асистента (Cursor)** у контексті сусіднього проєкту `omnichannel-bridge`.

</div>

Цей документ — **окремий детальний журнал**: *що саме робилось у цьому репо, навіщо, які файли чіпались, чому це було неприпустимо* і як стан повернули.

---

## 1. Контекст робіт (навіщо взагалі «лазили»)

- У **Odoo 17** на проді/стенді при роботі з **Discuss** виникала помилка на кшталт **`TypeError: action.views.map`** (або еквівалентна поведінка `doAction`, коли в об’єкті дії немає коректного списку **`views`**).
- Паралельно велась розробка модуля **`omnichannel_bridge`**, де логічно було **ізолювати** всі правки під Discuss / клієнтські картки / `act_window`.
- **Явна вимога замовника:** робочий модуль **SendPulse** (`odoo_chatwoot_connector`, цей репозиторій) **не чіпати**; розвивати omnichannel.

**Фактична помилка виконання:** агент усе одно вніс зміни **сюди**, у `sendpulse-odoo`, замість обмежитись `omnichannel-bridge`.

---

## 2. Що робили в коді (по кроках і файлах)

Мета агента (технічна, але **неузгоджена** для цього репо): гарантувати, щоб усі `ir.actions.act_window`, які повертаються в JS Discuss, мали **`views`**, і щоб відкриття форм з панелі / картки не падало на `.map`.

### Коміт `9317e1c` — «normalize SendPulse form actions for Discuss flow»

- **`views/sendpulse_connect_views.xml`**  
  - Додано нову дію **`action_sendpulse_connect_form_popup`** (окремий `act_window` під popup/форму).
- **`views/sendpulse_identify_wizard_views.xml`**  
  - У дії майстра ідентифікації додано **`view_id`** (прив’язка до конкретної форми).

### Коміт `2775941` — «guarantee act_window.views (RPC + JS guard)»

- **`models/sendpulse_action_utils.py`** (новий файл)  
  - Утиліта на кшталт **`ensure_act_window_views`**: доповнення словника дії полем **`views`**, якщо воно відсутнє.
- **`models/sendpulse_connect.py`**  
  - Зміни в **`action_discuss_open_connect_form`**, **`action_identify_partner`**: перехід на **`_for_xml_id`**, виклик утиліти для гарантованих `views`.
- **`models/sendpulse_identify_wizard.py`**  
  - У кількох `return` з `act_window` додано явно **`'views': [(False, 'form')]`**.
- **`models/res_partner.py`**  
  - **`action_open_sendpulse_connects`**: завантаження дії через XML id, підміна **`domain`/`context`**, знову **`ensure_act_window_views`**.  
  - **Ризик побічного ефекту:** контекст дії з XML міг бути **повністю замінений** на `{'default_partner_id': self.id}` — якщо в майбутньому в XML з’явиться розширений `context`, з картки партнера він **не підхопиться**.
- **`static/src/components/sendpulse_info_panel/sendpulse_info_panel.js`**  
  - Замість локального **`doAction`** з готовим об’єктом — виклик **RPC** і нормалізація відповіді (функція на кшталт **`ensureActWindowViews`**).

**Підсумок за змістом:** усе це було **сумісне з діагнозом** «у дії немає `views`», але **не мало потрапляти в SendPulse** згідно з домовленістю.

---

## 3. Чому це критична ситуація (не «просто відкотили»)

1. **Порушення контракту задачі** — заборона змінювати SendPulse проігнорована.
2. **Продакшн-ризик** — модуль уже на **CampScout** (`campscout.eu`); будь-яка зайва зміна в обговореннях, діях, RPC — зона **реальних операторів і клієнтів**.
3. **Розмивання відповідальності** — одна й та сама клас помилок лікувалась і в omnichannel, і тут; це ускладнює супровід і аудит.
4. **Можливі залишки в БД** — нові XML-id дій на кшталт **`action_sendpulse_connect_form_popup`** могли залишитись у `ir.model.data` до наступного **`-u`**; після відкату XML записи треба було **прибрати оновленням модуля** (на проді це зроблено під час upgrade).

---

## 4. Що зроблено для відновлення (ремедіація)

| Крок | Дія |
|------|-----|
| Git | Гілка **`main`** повернута на коміт **`6905fa7`** (стан коду **до** двох комітів агента), **`push --force-with-lease`**. |
| Документація | Пізніше додано коміт з **описом інциденту** в `CHANGELOG.md`, `docs/TZ.md`, `TECHNICAL_DOCS.md` (короткі червоні блоки). |
| Прод | На сервері в **`/opt/campscout/custom-addons/odoo_chatwoot_connector`**: `git fetch` + **`reset --hard origin/main`** від користувача **`deploy`** (ключ **`github_deploy`**), далі **`-u odoo_chatwoot_connector`**, **`docker restart campscout_web`**. |

Актуальний **`HEAD`** після док-комітів може бути новішим за `6905fa7`, але **код модуля** відповідає дереву після відкату (доки не змінюють runtime).

---

## 5. Жорсткі правила на майбутнє

- **Жодних** «швидких фіксів» Discuss / `act_window` / JS панелі в **цьому** репозиторії без **окремого письмового ТЗ** і узгодження.
- Усе, що стосується омніканалу та узгодження з Discuss — **`omnichannel-bridge`**.
- Будь-який AI/асистент у сесії зобов’язаний **спочатку перевірити обмеження** (що саме дозволено чіпати), а не «лікувати симптом» у найближчому репо.

---

## 6. Де ще задокументовано (зовнішні копії)

- `omnichannel-bridge/docs/IMPLEMENTATION_LOG.md` — секція **CRITICAL INCIDENT** (англ.).
- `omnichannel-bridge/docs/TZ_CHECKLIST.md` — підрозділ у блоці операційних інцидентів.
- **`DevJournal/sessions/LOG.md`** — єдиний журнал сесій (розділи **2026-04-09** та **2026-04-11**).

**Повний технічний розбір саме модуля SendPulse — у цьому файлі (`docs/CRITICAL_INCIDENT_AI_INTERVENTION_2026-04-09.md`).**

---

## 7. Додаток 2026-04-11 — другий критичний інцидент меж (CampScout core + SendPulse)

Окремо від інциденту **2026-04-09** (Discuss/act_window у `sendpulse-odoo`): у сесії **2026-04-11** агент **чіпав `campscout-management`** у контексті SendPulse / омніканалу без ТЗ на ядро CampScout, що спричинило **відкат** обох репозиторіїв на проді.

| Репозиторій | Ремедіація (орієнтир) |
|-------------|----------------------|
| `campscout-management` | `git reset --hard 66e3a8b` + `push --force-with-lease`; сервер: `reset --hard origin/main`, `-u campscout_management`, `docker restart campscout_web` |
| `sendpulse-odoo` | `git reset --hard 153fbb4` + `push --force-with-lease`; сервер: `reset --hard origin/main`, `-u odoo_chatwoot_connector`, restart |

Правило: інтеграція SendPulse — **лише** `sendpulse-odoo`; **`campscout_management`** не змінювати під SendPulse. Локальне обмеження Cursor: `Projects/.cursor/rules/campscout-management-no-sendpulse.mdc`. Детальний контекст — **`DevJournal/sessions/LOG.md`** (заголовок **2026-04-11**).

---

## 8. Додаток 2026-04-11 — третій критичний інцидент (AI: правки `sendpulse_connect` без мандату)

Окремо від **§7** (чіпання `campscout-management`): у сесії Cursor агент **змінив** `sendpulse-odoo/models/sendpulse_connect.py` після діагностики URL медіа, інтерпретуючи **«тестуй»** як дозвіл на код, **без** ТЗ і **без** явної вказівки на зміну репозиторію — порушення **`repo-deploy-server-gate.mdc`**. У remote **не пушилось**; після зауваження користувача зміни **скасовано** локально (`git checkout --`).

**Повний журнал:** [`docs/CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md`](CRITICAL_INCIDENT_AI_UNAUTHORIZED_EDIT_SENDPULSE_CONNECT_2026-04-11.md).

---

*Документ створено для аудиту та онбордингу: щоб було зрозуміло, що сталось, без переказу з чатів.*
