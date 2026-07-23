# HFabric — підсумок стабілізації та release roadmap

> Станом на 2026-07-23 попередній план повністю замінено.
> Усі пункти, які можна реалізувати й перевірити локально, завершені.
> Незакритими залишені лише перевірки, для яких потрібні окремі ОС або реальне
> GPU-обладнання.

## 1. Результат

Проєкт приведено до стабільнішої та простішої для підтримки структури:

- життєвий цикл GPU, Voice і зовнішніх процесів канонізовано та покрито
  детермінованими тестами;
- локальні налаштування, секрети, пресети й SQLite захищено від часткових записів,
  пошкодження та конкурентного доступу;
- видалення моделей, завантаження файлів, ZIP-розпакування, asset-доступ і LAN-bind
  отримали fail-closed перевірки;
- OpenAPI, Pydantic-схеми та frontend-типи синхронізовано;
- великі backend/frontend-модулі розділено за відповідальністю;
- UI отримав boundary помилок, адаптивність, клавіатурну доступність, відновлення
  після WebSocket reconnect і стійкість до некоректних API-відповідей;
- залежності розкладено за профілями з відтворюваними lock-файлами;
- CI перевіряє тести, контракти, безпеку, залежності, dead code і shell-скрипти.

## 2. Фінальна перевірена базова лінія

| Контур | Результат |
| --- | --- |
| Backend tests | 612 зібрано: **611 passed, 1 skipped** |
| Детермінізм backend | coverage-прогін, повторний прогін і shuffled seed `20260723` — green |
| Backend coverage | **82.73%** lines/statements, **65.81%** branches, **79.25%** combined |
| Frontend unit tests | **125/125** у 27 test files |
| Frontend coverage | 30.32% statements, 25.97% branches, 26.86% functions, 31.37% lines |
| Browser E2E | **10/10** |
| Accessibility | axe green у dark, dim і light themes |
| Responsive UI | перевірено 320, 360, 390, 768, 1024 і 1440 px |
| Initial JS bundle | 258.09 KB / **80.16 KB gzip**, без warning про завеликий initial chunk |
| Backend quality | Ruff, Vulture, `pip check`, lock/profile consistency — green |
| Frontend quality | ESLint, strict TypeScript, OpenAPI freshness, Knip, build — green |
| Security | secret scan, production/dev `pip-audit`, `npm audit` — green з контрольованими винятками нижче |
| Launch scripts | PowerShell parser, Git Bash `bash -n`, ownership tests — green |

### Покриття критичних backend-модулів

| Модуль | Lines | Branches | Combined |
| --- | ---: | ---: | ---: |
| GPU arbiter | 95.5% | 90.5% | 94.1% |
| Scheduler | 100% | 94.1% | 98.6% |
| Atomic JSON store | 95.0% | 96.9% | 95.3% |
| Settings overrides | 99.2% | 88.5% | 95.9% |
| Model storage | 87.8% | 88.3% | 87.9% |
| Security policy | 100% | 100% | 100% |
| Queue service | 100% | 100% | 100% |

## 3. Реалізований план

### P0 — стабільність життєвого циклу

- [x] Ізолювати runtime і БД кожного тесту; усунути order/state dependence.
- [x] Перетворити GPU arbiter на типізований state machine з явними lease,
  pin/free/handoff і rollback.
- [x] Зробити Voice ексклюзивною GPU lane та заборонити паралельний важкий
  resident.
- [x] Додати bounded shutdown для scheduler, Voice, LLM і зовнішніх процесів.
- [x] Канонізувати запуск процесів, PID metadata та перевірку ownership.
- [x] Прибрати глобальні `pkill`, `fuser -k` і завершення сторонніх власників портів.
- [x] Зробити non-loopback bind без автентифікації fail-closed.
- [x] Додати регресійні тести busy, cancellation, retry, shutdown і rollback paths.

### P1 — дані, сховище та мережа

- [x] Запровадити спільний `AtomicJSONStore` з lock, fsync, backup і quarantine.
- [x] Перевести settings, secrets і presets на атомарне збереження.
- [x] Увімкнути SQLite WAL, foreign keys, busy timeout і bounded retry.
- [x] Додати reconciliation для DB/media та fallback thumbnail → original.
- [x] Захистити model deletion від parent/child, symlink, active model, LoRA,
  `mmproj` і check/use race.
- [x] Винести блокувальні файлові операції з async event loop.
- [x] Додати обмеження upload/ZIP, path traversal і ZIP-bomb перевірки.
- [x] Додати SSRF policy з DNS/IP revalidation для зовнішніх завантажень.
- [x] Замінити bearer token у URL на короткоживучу підписану HttpOnly asset session.
- [x] Виключити секрети й runtime-файли з Code API.

### P1 — API, помилки та спостережуваність

- [x] Замінити generic успішні відповіді на іменовані Pydantic response models.
- [x] Канонізувати помилки як структурований API contract.
- [x] Генерувати TypeScript API types з актуального OpenAPI.
- [x] Додати перевірку freshness контракту в CI.
- [x] Додати request ID до HTTP/WebSocket потоку й структурованих логів.
- [x] Додати метрики черги, scheduler, GPU handoff, reconnect і помилок.
- [x] Зберегти сумісність зовнішніх download/model test hooks після декомпозиції.

### P1 — UI та UX

- [x] Додати глобальний React Error Boundary і єдиний `ApiError`.
- [x] Не падати на частково некоректних settings/runtime API-відповідях.
- [x] Після WebSocket reconnect виконувати REST reconciliation замість показу
  застарілого стану.
- [x] Канонізувати query cache та інвалідацію після mutations/events.
- [x] Додати стійке зображення з fallback і зрозумілим empty/error state.
- [x] Виправити dialog/select/focus/keyboard semantics та aria-атрибути.
- [x] Прибрати горизонтальне переповнення на 320–1440 px.
- [x] Перевірити чергу, історію, settings retry, model-delete guard і Voice gating
  у браузері.
- [x] Ліниво завантажувати workspaces; скоротити initial bundle.

### P2 — канонізація та зменшення сміттєвого коду

- [x] Розділити `scheduler.py` на orchestration, planning і result handling.
- [x] Розділити settings specs на доменні секції.
- [x] Розділити image backend на core, editing і LoRA responsibilities.
- [x] Розділити model download service на catalog, transport і validation.
- [x] Декомпозувати App, Chat, Voice, Video й Image frontend-контролери та секції.
- [x] Видалити невикористані exports і дублікати ручних типів.
- [x] Додати Vulture і Knip як обов'язкові dead-code gates.
- [x] Додати allowlist-based cleanup лише для відтворюваних dev-артефактів.
- [x] Прибрати застарілі коментарі, тимчасові обходи й дубльовані конфігурації.

### P2 — залежності, CI та документація

- [x] Виділити foundation, accelerator-common, CUDA, ROCm, MPS і dev profiles.
- [x] Створити хешовані lock-файли й автоматичну перевірку profile drift.
- [x] Перевіряти production та development dependencies на відомі вразливості.
- [x] Зафіксувати GitHub Actions за immutable SHA.
- [x] Додати secret scan, OpenAPI contract, dead-code і launcher syntax gates.
- [x] Оновити README, configuration, developer, security та known-issues docs.
- [x] Додати Windows-compatible stub/full verification path.

## 4. Канонічні джерела

| Область | Канонічне джерело | Похідні/споживачі |
| --- | --- | --- |
| HTTP API | Pydantic response/request models | OpenAPI → generated TypeScript |
| Помилки API | backend error contract | frontend `ApiError` і UI states |
| Налаштування | доменні settings specs | API schema, defaults, UI metadata |
| Залежності | `backend/dependency-profiles.json` та `.in/.txt` profiles | hashed lock-файли |
| GPU ownership | `GpuArbiter` state machine | scheduler, LLM, image, video, Voice |
| Процеси | PID metadata + runtime environment policy | Windows/POSIX launchers |
| Мережа | network policy | bind validation, downloads, assets |
| JSON persistence | `AtomicJSONStore` | settings, secrets, presets |
| Frontend navigation | workspace registry + lazy loaders | sidebar, commands, routing |
| API data state | query cache + event reconciliation | workspaces і reconnect |

## 5. Release gates

### Локально закриті

- [x] Повний backend suite.
- [x] Повторний і shuffled backend suite.
- [x] Критичне branch coverage вище 85%.
- [x] Frontend unit, coverage, browser E2E та axe.
- [x] OpenAPI generation/freshness, TypeScript, ESLint і production build.
- [x] Ruff, Vulture, Knip і `git diff --check`.
- [x] Dependency locks, audits, secret scan і launcher syntax.
- [x] Cleanup відтворюваних test/build/cache артефактів.

### Потребують зовнішнього середовища

- [ ] На чистій Windows-машині пройти повний setup → update → запуск →
  backup/restore audit.
- [ ] Повторити реальну NVIDIA-матрицю image/video/LLM/Voice після змін lifecycle.
- [ ] Провести реальну smoke/VRAM/quality валідацію профілів ROCm та Apple MPS.

Ці три пункти не замінюються mock/stub-тестами й не позначаються завершеними без
відповідного обладнання або чистого хоста.

## 6. Контрольовані винятки та подальший моніторинг

- `transformers`: тимчасові advisory exceptions до **2026-10-31**; перехід на
  major version 5 потребує повторної GPU-матриці через зміну CLIP internals.
- `setuptools`: тимчасовий exception до **2026-09-15** через обмеження поточного
  PyTorch-профілю; переглянути разом із наступним валідованим PyTorch/Nunchaku
  оновленням.
- Generated `frontend/src/types.generated.ts` виключений лише з dead-code scan,
  оскільки його публічна поверхня задається OpenAPI.
- Реальні hardware adapters виключені з локальної coverage-метрики; їхнім release
  gate є окрема апаратна матриця.
- Загальне frontend coverage зафіксоване як нова базова лінія. Критичні
  користувацькі сценарії додатково захищені browser E2E; новий код не повинен
  знижувати цю базу.

Після проходження трьох зовнішніх release gates цей roadmap можна закрити повністю
та перенести підсумок до release notes.
