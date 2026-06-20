# CivitAI Integration — Research & Roadmap

> **Shipped:** model browser (CivitAI search + version/file pick + download) inside a
> unified Models page (Hugging Face / CivitAI / Direct URL), plus CivitAI auth
> (API key + native session cookie).
> **Deferred (by owner):** uploading generated images to CivitAI.

## Зафіксовані рішення

1. **Сторінка моделей** — єдиний браузер із перемикачем джерела **Hugging Face /
   CivitAI / Direct URL**; курований стартовий каталог лишається зверху.
2. **Авторизація** — два креденшели поряд: API-ключ (стабільний, для завантаження) і
   **нативна сесія** (cookie `__Secure-civitai-token`), що діє «від імені акаунта» і
   перевикористається для майбутнього аплоаду.
3. **Аплоад — без сторонніх файлових хостів.** Прийнятно «відкрити сторінку в браузері»,
   але так, щоб картинка вже була в пості від залогіненого акаунта. **Відкладено.**
4. **civitai.com vs civitai.red** — перемикач «дорослий контент» (off за замовчуванням);
   пізніше — вибір призначення поста при аплоаді.

---

## 1. Дослідження CivitAI

### 1.1 Завантаження моделей — повноцінний REST API v1

База `https://civitai.com/api/v1/`:

| Ендпоінт | Призначення | Ключові поля |
|---|---|---|
| `GET /models` | пошук/каталог | `query`, `tag`, `username`, `types`, `sort`, `period`, `baseModels`, `nsfw`, `limit`, `page`/`cursor` |
| `GET /models/:id` | деталі моделі | `name`, `type`, `nsfw`, `modelVersions[]`, `creator` |
| `GET /model-versions/:id` | деталі версії | `files[]`, `images[]`, `baseModel`, `trainedWords` |
| `GET /api/download/models/:versionId` | сам файл | редірект на підписаний URL; ім'я у `Content-Disposition` |

`types`: `Checkpoint`, `LORA`, `LoCon`, `DoRA`, `TextualInversion`, `Hypernetwork`,
`Controlnet`, `Upscaler`, `VAE`, `Poses`, `Wildcards`, `Workflows`, `Other`.
`files[]`: `name`, `sizeKB`, `type`, `metadata.format` (SafeTensor/PickleTensor),
`downloadUrl`, `primary`, `hashes.SHA256` (для верифікації). `trainedWords` дає
тригер-слова LoRA; `images[]` — прев'ю для карток.

### 1.2 Авторизація для завантаження (CivitAI гейтить майже все)

Перевірено напряму: `GET /api/download/models/<versionId>` повертає **401 Unauthorized**
без креденшела навіть для моделей із `availability: Public`. Частина старих публічних
моделей ще качається анонімно, але більшість — ні. Отже:
- креденшел **фактично обов'язковий** (API-ключ `?token=`/bearer, **або** сесійна кука
  `__Secure-civitai-token`);
- 401/403 → зрозуміла помилка, битий/HTML-файл не зберігається.

### 1.3 Аплоад зображень — публічного write-API НЕМАЄ

Публічний API **read-only**; завантажити можна лише через веб-UI. Єдиний задокументований
місток — **Post Intent System**:
`https://civitai.com/intent/post?mediaUrl=<URL>&title=…&description=…&tags=a,b&detailsUrl=<URL>`
(`mediaUrl` — абсолютний публічний URL, який CivitAI тягне сам; png/jpg/webp ≤ 50 МБ;
завжди напівавтоматично — браузер + ручне підтвердження). **Проблема:** ми на
`localhost`, тож CivitAI не дістане `mediaUrl` без зовнішнього хосту/тунелю — а зовнішні
хости власник відхилив.

### 1.4 Session-based «native web API» аплоад — вердикт

Внутрішня кухня: NextAuth v4, cookie `__Secure-civitai-token` (`httpOnly`); веб-аплоад
через недокументовані tRPC-мутації + presigned upload у S3/R2; перед усім — CSRF і
ймовірний Cloudflare/Turnstile. **Технічно можливо, але крихко й ToS-сіро.** Потрібно
одночасно: (1) захопити httpOnly-сесію (ручна вставка cookie, або керований
Playwright-браузер), (2) відтворити presigned+tRPC недокументованих ендпоінтів,
(3) пережити CSRF/Cloudflare. Справжній one-click аплоад зламається щоразу, як CivitAI
змінить внутрянку.

### 1.5 civitai.com (SFW) vs civitai.red (NSFW)

З **15 квітня 2026** CivitAI розділили фронтенди: `civitai.com` — лише SFW, `civitai.red`
— SFW + NSFW. Один акаунт/база, відрізняється тільки видимість. Після переносу NSFW на
`.red` пошук через `.com` перестав бачити частину моделей. Тож для NSFW треба бити в
**`civitai.red`** базу + `nsfw=true`. У UI — перемикач **RED** (off → `.com`).

---

## 2. Що реалізовано (Фази A–C)

**Бекенд**
- [`civitai_service.py`](../backend/app/services/civitai_service.py) — `search_models`
  + `version_files` (нормалізація, мапінг типів → папки реєстру, перемикання
  `.com`/`.red`, прокидання auth-заголовків).
- [`civitai_auth.py`](../backend/app/services/civitai_auth.py) — секрет-стор
  `data/secrets.json` (loopback-only): API-ключ і session-cookie; `auth_headers()`
  (browse) та `download_auth(url)` (download, ключ→cookie→анонім); `verify_key`/
  `verify_cookie` (пінг auth-only `favorites`).
- [`api/civitai.py`](../backend/app/api/civitai.py) — `GET /search`,
  `GET /versions/:id/files`, `GET/PUT/DELETE /auth`. Завантаження йде наявним
  custom-пайплайном ([`model_download_service.py`](../backend/app/services/model_download_service.py),
  source `civitai`) — спільні статус/прогрес/disk-budget/rescan + SHA256-верифікація.

**Фронтенд**
- [`CivitaiBrowser.tsx`](../frontend/src/components/CivitaiBrowser.tsx) — пошук із
  прев'ю-картинками, вибір версії/файлу, тригер-слова, пагінація, RED-перемикач
  (персистентний), панель Account (API key + Session login).
- [`ModelDownloads.tsx`](../frontend/src/components/ModelDownloads.tsx) — три секції:
  **Recommended** (преселект, 1 CTA) → **Browse & install** (HF/CivitAI/URL, відкрито,
  автозавантаження топ-моделей) → **Installed** (згорнуто).

Примітки: CivitAI не має публічного `whoami`, тож verify лише підтверджує, що креденшел
приймається. Cookie протухає → перевставити. One-click Playwright-логін свідомо НЕ
беремо (важка залежність + ToS) — лишаємо опцією на момент аплоаду.

---

## 3. Відкладено — аплоад зображень

Дворівневий план, коли візьмемось:
- **Tier 1 (Assisted, MVP):** застосунок готує пост із метаданих галереї
  (title/description/tags), кладе картинку в clipboard і відкриває `civitai.com/posts/create`
  у залогіненому браузері; користувач вставляє (1–2 кліки). Нуль інфраструктури, ToS-чисто.
- **Tier 2 (Session automation, опційно):** Playwright-логін → захоплення сесії →
  presigned+tRPC аплоад. Справжній one-click, але крихко/ToS-сіро — за прапорцем, з
  fallback на Tier 1.

**Відкрите питання:** старт із Tier 1, а Tier 2 — окремою фазою за окремим рішенням?
(рекомендація: так.) civitai.com vs civitai.red як вибір призначення поста.

---

## 4. Ризики

- **Tier 2 аплоад** залежить від недокументованих ендпоінтів + CSRF/Cloudflare —
  ламатиметься без попередження; тримати опційним із fallback.
- **Сесійна кука протухає** — UI має підказувати ре-логін.
- **Ліцензії моделей** — показувати поля дозволів; не качати в обхід gating.
- **NSFW/RED** — off за замовчуванням, явний перемикач.
