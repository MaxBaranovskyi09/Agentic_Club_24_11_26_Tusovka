# Тусовка — сервіс подій

Спрощений Meetup: створюйте події (публічні та приватні), записуйтеся, коментуйте.
Django 5 (SSR-шаблони) + PostgreSQL, без SPA.

## Локальний запуск (WSL Ubuntu)

### 1. PostgreSQL

```bash
sudo apt update
sudo apt install -y postgresql python3-venv
sudo service postgresql start
```

Створіть користувача і базу (`CREATEDB` потрібен, щоб pytest міг створити тестову БД):

```bash
sudo -u postgres psql
```

```sql
CREATE USER tusovka WITH PASSWORD 'tusovka' CREATEDB;
CREATE DATABASE tusovka OWNER tusovka;
\q
```

### 2. Проєкт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # відредагуйте SECRET_KEY і DATABASE_URL
python manage.py migrate
python manage.py createsuperuser   # опційно, для /admin/
python manage.py runserver
```

Відкрийте http://127.0.0.1:8000/.

Згенерувати SECRET_KEY:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### 3. Тести

```bash
pytest
```

Тести використовують ту ж конфігурацію (`.env`) і створюють окрему тестову БД `test_tusovka`.
Тести на паралельний запис (потоки + `select_for_update`) виконуються лише на PostgreSQL.

## Змінні середовища

| Змінна | Обовʼязкова | За замовчуванням | Опис |
|---|---|---|---|
| `SECRET_KEY` | так | — | Секретний ключ Django. Довгий випадковий рядок. |
| `DEBUG` | ні | `False` | Режим налагодження. У проді — тільки `False`. |
| `DATABASE_URL` | так | — | `postgres://user:pass@host:5432/db`. На Railway підставляється з плагіна Postgres. |
| `ALLOWED_HOSTS` | так (прод) | порожньо | Список хостів через кому, напр. `.up.railway.app`. |
| `CSRF_TRUSTED_ORIGINS` | так (прод) | порожньо | Origins через кому, напр. `https://*.up.railway.app`. |
| `MEDIA_ROOT` | ні | `./media` | Каталог для обкладинок. На Railway — `/data/media` (volume). |
| `USE_X_FORWARDED_FOR` | ні | `False` | Брати IP клієнта з останнього значення `X-Forwarded-For` (для rate limit). Вмикати лише за довіреним проксі (Railway). |
| `SECURE_SSL_REDIRECT` | ні | `False` | Редірект HTTP → HTTPS. |
| `SECURE_HSTS_SECONDS` | ні | `0` | HSTS. Вмикайте (напр. `31536000`), коли впевнені, що сайт працює лише по HTTPS. |
| `LOG_LEVEL` | ні | `INFO` | Рівень логування (логи йдуть у stdout). |

`.env` ігнорується git; шаблон — `.env.example`.

## Прийняті рішення

**Доступ (усе на сервері, `events/permissions.py`).**
- `can_view`: публічна подія — всім; приватна — автору або користувачу з `PrivateAccess`.
- `can_edit`: лише автор.
- Кожен view (GET і POST) отримує подію тільки через `get_viewable_event` / `get_editable_event`.
- Приватна подія без доступу → **404** скрізь (перегляд, запис, скасування, коментар, обкладинка, редагування, видалення), щоб не розкривати її існування. Для публічної події чужий користувач на редагуванні/видаленні отримує 403.
- Події адресуються за `public_id` (UUID), а не за послідовним id.
- Форми — `ModelForm` з явним `fields`; `author`, `invite_token`, `public_id` ніколи не беруться із запиту.

**Запис на подію (`events/services.py`).**
- `transaction.atomic()` + `select_for_update()` на рядку події → підрахунок записів → створення. Паралельні запити серіалізуються, перевищити `capacity` неможливо.
- `IntegrityError` (дубль) → повідомлення «Ви вже записані», а не 500.
- Автор **не може** записатися на власну подію (він організатор, місце не займає).
- Не можна записатися на подію, що почалась/минула, або коли місць немає. Скасувати можна лише власний запис і лише до початку події.
- Редагування: `capacity` не може бути меншою за кількість записаних — перевірка під тим же `select_for_update`. Дату не можна перенести в минуле (якщо дата не змінюється — збереження дозволене).

**Приватні події та інвайти.**
- Кожна подія має `invite_token = secrets.token_urlsafe(32)`. Автор бачить посилання `/invite/<token>/` (лише для приватних) і може його перегенерувати — старе одразу перестає працювати (404). Ті, хто вже отримав доступ, його зберігають.
- Відкриття інвайту залогіненим користувачем створює `PrivateAccess` (ідемпотентно) — це єдиний GET зі зміною стану, як того вимагає сценарій «перейти за посиланням». Незалогіненого перенаправляє на вхід з `next`.

**Приватність даних.** Скрізь показується `name`. Email бачить лише автор події (у списку учасників) і сам користувач у профілі.

**Обкладинки.**
- Лише JPEG/PNG/WebP — формат визначає Pillow за вмістом (`Image.open().verify()`); розширення й content-type клієнта ігноруються. ≤ 5 МБ, ≤ 6000×6000 px (захист від decompression bomb), запити > ~5.5 МБ відхиляються middleware ще до розбору (413).
- Імʼя файлу — `covers/<uuid4>.<ext>`.
- `MEDIA_ROOT` не роздається як статика. Обкладинка віддається через `/events/<public_id>/cover/` з перевіркою `can_view`, правильним content-type і `X-Content-Type-Options: nosniff`.
- Старий файл видаляється з диска при заміні/очищенні обкладинки та при видаленні події (після commit транзакції).

**Автентифікація.**
- Кастомна модель `User` без username: вхід за email (зберігається в lower case), обовʼязкове `name`.
- Вбудовані Django auth views + стандартні валідатори паролів і хешери.
- Помилка входу завжди загальна: «Невірний email або пароль.»
- Rate limit: 5 невдалих входів / 15 хв на email+IP; 5 реєстрацій / година на IP; коментар не частіше 1 разу / 5 с на користувача. Лічильники — у кеші Django в БД (спільний для всіх воркерів gunicorn; таблиця створюється міграцією).
- Вихід — лише POST (GET → 405).

**Безпека загалом.** Жодного `|safe`/`mark_safe` для даних користувачів; опис і коментарі — plain text з `linebreaksbr`. Усі зміни стану — POST + CSRF. `DEBUG=False` за замовчуванням, secure-cookies поза DEBUG, `X_FRAME_OPTIONS=DENY`, `nosniff`, `Referrer-Policy: same-origin`, `SECURE_PROXY_SSL_HEADER`. Власні сторінки 400/403/404/500 без stack trace, помилки логуються у stdout.

## Деплой на Railway

1. **Новий проєкт** на https://railway.com → *Deploy from GitHub repo* → оберіть цей репозиторій. Railway збере застосунок (Python 3.12 з `.python-version`, залежності з `requirements.txt`).
2. **Postgres:** у проєкті *+ New → Database → PostgreSQL*.
3. **Змінні web-сервісу** (*Variables*):
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   SECRET_KEY=<довгий випадковий рядок>
   DEBUG=False
   ALLOWED_HOSTS=.up.railway.app
   CSRF_TRUSTED_ORIGINS=https://*.up.railway.app
   MEDIA_ROOT=/data/media
   USE_X_FORWARDED_FOR=True
   SECURE_SSL_REDIRECT=True
   ```
   Якщо підключаєте власний домен — додайте його в `ALLOWED_HOSTS` і `https://ваш.домен` у `CSRF_TRUSTED_ORIGINS`.
4. **Volume:** у web-сервісі *Settings → Volumes → Add volume*, mount path `/data`. Обкладинки зберігаються в `/data/media` і переживають редеплой.
5. **Домен:** *Settings → Networking → Generate Domain* (отримаєте `*.up.railway.app`).
6. **Старт:** команда задана в `railway.json` (і дубльована в `Procfile`):
   ```
   python manage.py migrate --noinput && python manage.py collectstatic --noinput && gunicorn config.wsgi --bind 0.0.0.0:$PORT
   ```
   Міграції та збирання статики виконуються при кожному деплої; статику роздає whitenoise.
7. Адміністратор (опційно): `railway run python manage.py createsuperuser` або через *Shell* сервісу.
8. Коли HTTPS перевірено — можна ввімкнути `SECURE_HSTS_SECONDS=31536000`.

## Структура

```
config/      налаштування, urls, middleware (ліміт розміру запиту), сторінки помилок
accounts/    кастомний User, реєстрація/вхід/вихід, rate limit
events/      моделі, permissions.py, services.py (запис), forms, views, валідація обкладинок
templates/   SSR-шаблони
static/css/  стилі
tests/       pytest
```
