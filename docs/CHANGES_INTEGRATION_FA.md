# تغییرات T0 تا T4 در Kira (انگلیسی‌سازی، حافظه‌ی شواهدمحور، مغز چندمرحله‌ای، MCP/ایجنت، مصرف)

این فایل با هر تحویل (هر تسک) کامل‌تر می‌شود. قواعد: هیچ تستی ساخته یا اجرا نشده؛ برنامه اجرا نشده؛ فقط بررسی ایستای syntax انجام شده است.

## v7 — T0: انگلیسی‌سازی متن‌های چینی/ژاپنی

**چه چیزی پیدا شد:** در کل پروژه فقط ۱۳ خط در ۷ فایل `.py` حاوی کاراکتر چینی/ژاپنی بود. همه *کاراکتر عملکردی* بودند، نه متن توضیحی.

**چه کاری شد:** کاراکترها با escape یونیکد (`\uXXXX`) جایگزین شدند و بالای هر مورد کامنت انگلیسی آمد. مقدار نهایی رشته‌ها و ساختار regexها بایت‌به‌بایت (از نظر معنایی) یکسان است؛ این موضوع با مقایسه‌ی AST و parse کردن regexهای قبل و بعد بررسی شد.

| فایل | چه بود | الان |
|---|---|---|
| `kira/cloud_voice.py` | پایان‌دهنده‌های جمله `。！？` | `。！？` + کامنت |
| `kira/emotion/parser.py` | کلیدواژه‌ی «احساس» به چینی و `：` | escape + کامنت |
| `kira/leak_guard.py` | `：` تمام‌عرض (۳ جا) | `：` + کامنت |
| `kira/persona_memory.py` | `？` تمام‌عرض (۴ جا) | `？` + کامنت |
| `kira/speech_split.py` | `TERMS` و توضیح docstring | escape + توضیح انگلیسی |
| `kira/strings.py` | جمله‌ی نمونه‌ی ژاپنی TTS | escape + ترجمه‌ی انگلیسی در کامنت |
| `kira/tools/tasks.py` | `：` در جداکننده‌ی «مرحله اضافه کن» | `：` + کامنت |

**عمداً دست نخورد:** متن فارسی (پیام‌های کاربر، regexهای فارسی، مستندات `_FA.md`). این‌ها زبان خود محصول‌اند و ترجمه‌شان رفتار را تغییر می‌دهد.

**قانون از این به بعد:** همه‌ی کد، کامنت و پرامپت‌های جدید انگلیسی نوشته می‌شوند؛ فقط متنی که به کاربر نشان داده می‌شود فارسی است.

---

## v8 — T1: حافظه‌ی مبتنی بر شواهد

مستندات کامل: `docs/MEMORY_EVIDENCE_FA.md`.

**فایل‌های جدید**
- `kira/evidence_memory.py` — ذخیره‌ی واقعیت + شاهد، تناقض/عدم‌قطعیت، BM25، Embedding اختیاری، RRF، قرنطینه، پر کردن از تاریخچه.
- `docs/MEMORY_EVIDENCE_FA.md`

**فایل‌های تغییرکرده**
- `kira/persona_memory.py` — `extract_facts_detailed` (همان قواعد قبلی + نقل‌قول)، `extract_facts` همان خروجی قبلی؛ `observe` به لایه‌ی شواهد هم می‌نویسد؛ حذف/ویرایش/فراموشی هر دو لایه را هماهنگ می‌کند؛ `build_block(query, budget)` با fallback کامل به رفتار قبلی.
- `kira/memory.py` — فقط‌خواندنی: `rows_with_ids`، `max_message_id`.
- `kira/main.py` — سه خط: `configure` در شروع و بعد از ذخیره‌ی تنظیمات، و ارسال پیام فعلی و بودجه به `build_block`.
- `kira/config.py` — پنج کلید پیش‌فرض.
- `kira/storage.py` — پشتیبان‌گیری از `kira_evidence.sqlite3`.

**چه چیزی عمداً دست نخورد:** Active Mode، شخصیت، Relationship Memory (لحظه‌ها، عادت‌ها، خلاصه‌ها)، پنجره‌ی حافظه، Web Research، Taskها.
**عمداً پیاده نشد:** فراخوانی خودکار مدل برای استخراج واقعیت (مصرف API)؛ UI برای تنظیمات Embedding (خارج از محدوده).

**نیاز به اعتبارسنجی روی Windows**
1. اولین اجرا با دیتابیس قدیمی: ساخته شدن `kira_evidence.sqlite3` و نبود خطا.
2. پنجره‌ی حافظه: افزودن، ویرایش، حذف و «فراموش‌کردن همه».
3. جمله‌ی «اسمم X است» و بعد «نه، اسمم Y است»: فقط Y در prompt بیاید.
4. با `embedding_backend=ollama` و مدل واقعی: سرعت اولین پیام و رفتار هنگام خاموش بودن Ollama.
5. اندازه‌ی واقعی بلوک حافظه روی Qwen 3.5 4B با `num_ctx=4096`.

---

## v9 — T2: مغز چندمرحله‌ای

مستندات: `docs/BRAIN_FA.md`.

**فایل‌های جدید:** `kira/brain.py`، `docs/BRAIN_FA.md`

**فایل‌های تغییرکرده**
- `kira/hybrid_ai.py` — `role_scope(role, route_id)`؛ route ترجیحی اول می‌آید و بقیه‌ی ترتیب/failover/cooldown دست‌نخورده است؛ فیلد `role` در metrics.
- `kira/evidence_memory.py` — `current_value`، `writer_cursor`، `set_writer_cursor`.
- `kira/main.py` — `StreamWorker(role, route_id)`؛ `start_worker` مرحله را تعیین و پرامپت را (فقط در صورت نیاز) گسترش می‌دهد؛ `on_stream_done` → `brain.after_turn`؛ `clear_chat` → `brain.reset_state`.
- `kira/config.py` — چهار کلید پیش‌فرض.

**عمداً پیاده نشد:** بازنویسی پاسخ پس از نمایش؛ تماس مدل خودکار در حالت پیش‌فرض؛ UI برای `role_routes`.

**نیاز به اعتبارسنجی روی Windows**
1. پیام ساده: پرامپت و رفتار دقیقاً مثل قبل.
2. پیام بلند/تحلیلی: deep انتخاب شود و پاسخ عادی بیاید؛ روی Qwen 4B (`num_ctx=4096`) بلوک اضافه نشود.
3. `role_routes.deep` روی یک route دیگر: همان route اول امتحان شود و در خطا به ترتیب عادی برگردد.
4. ادعای «انجام دادم» بدون ابزار موفق: نوبت بعد فقط یک یادداشت کوتاه اعمال شود.
5. `brain_reflection="model"` و `brain_memory_writer="idle"`: فریز نشدن UI و رعایت سقف‌ها.

---

## v10 — T3: MCP و ایجنت‌های مستقل

مستندات: `docs/MCP_AGENTS_FA.md`، نمونه: `docs/kira_mcp.example.json`.

**فایل‌های جدید:** `kira/mcp/{__init__,config,client,hub,agents}.py`، دو فایل docs بالا.

**فایل‌های تغییرکرده**
- `kira/tools/registry.py` — قفل و `unregister_where` (ثبت ابزار از thread پس‌زمینه).
- `kira/tools/protocol.py` — دسته‌های `mcp` و `agents`، `set_gate_words`، `MCP_RULES` (فقط وقتی مربوط باشد).
- `kira/tools/agent.py` — `install` در `ToolAgent.__init__` (در try)، برچسب ابزارها، قواعد MCP.
- `kira/config.py` — `mcp_mode`.

**عمداً پیاده نشد:** ثبت سرور توسط مدل؛ UI؛ OAuth؛ اعلان خودکار پایان کار.

**نیاز به اعتبارسنجی روی Windows:** فهرست در `docs/MCP_AGENTS_FA.md`.

---

## v11 — T4: ردیابی مصرف و هزینه

مستندات: `docs/USAGE_FA.md`.

**فایل جدید:** `kira/usage.py`، `docs/USAGE_FA.md`

**فایل‌های تغییرکرده**
- `kira/hybrid_ai.py` — `last_usage` و `_note_usage` در provider؛ `stream_options.include_usage` برای Groq/OpenRouter؛ `_ledger` در `_finish` و مسیر شکست کامل؛ اعمال محدودیت‌ها در `_candidates`.
- `kira/main.py` — `usage.install` (شروع و بعد از ذخیره‌ی تنظیمات)، دستور `/usage`.
- `kira/config.py` — `model_prices`، `usage_limits`.
- قلاب‌های T1/T2 (`evidence_memory.usage_hook`، `brain.budget_check`) حالا وصل‌اند.

**عمداً پیاده نشد:** UI مصرف، تخمین توکن از طول متن، قطع گفتگو به‌خاطر محدودیت.

**نیاز به اعتبارسنجی روی Windows:** `docs/USAGE_FA.md`.

---

## v12 — یکپارچه‌سازی T0 تا T4

**ممیزی (بدون اجرای تست تا قبل از مرحله ۱۰):** گراف importها بررسی شد؛ چرخه‌ی واقعی در زمان import وجود ندارد (`kira.mcp` فقط به‌صورت lazy از `ToolAgent` بارگذاری می‌شود). داده‌های جدید همه در `DATA_DIR` (`%LOCALAPPDATA%\Kira`) هستند و با به‌روزرسانی برنامه از بین نمی‌روند: `kira_evidence.sqlite3`، `kira_brain_state.json`، `kira_jobs.json`، `kira_usage.sqlite3` و `kira_mcp.json`.

**اصلاح‌ها**
1. پلنر خودکار (`autonomy._cats_for`): بدون دسته‌ی تشخیص‌داده‌شده، کاتالوگ MCP و ایجنت به پرامپت نمی‌رود (فقط وقتی نام‌شان آمده باشد).
2. `brain.check_reply`: «نیازمند تأیید» دیگر «پنهان‌کردن خطا» حساب نمی‌شود (فقط error/denied/bad_args/unknown).
3. `brain._small_context`: پیش‌نمایش route داخل نقش درست انجام می‌شود (تشخیص مدل کوچک محلی روی route نقش deep).
4. embedding محلی (Ollama) در دفتر مصرف «محلی» ثبت می‌شود، نه Unknown.
5. `agent_ask`: ایجنت ناشناخته قبل از بررسی نقل‌قول گزارش می‌شود.
6. کلید قیمت `model_prices` می‌تواند فقط نام provider باشد.
7. pipeهای زیرپروسه‌ی MCP هنگام بستن آزاد می‌شوند.
8. حذف ارجاع‌های پروژه‌ی مرجع از کد و docs؛ فایل تغییرات به `CHANGES_INTEGRATION_FA.md` تغییر نام داد؛ README فهرست مستندات جدید را دارد.

**تست‌ها (مرحله ۱۰)**
- فایل جدید `tests/test_integration_t0_t4.py` — ۲۷ تست: حافظه (supersede، رد نقل‌قول نامعتبر)، مغز (مرحله، hint تک‌بار، ماندگاری state)، route نقش و failover، دفتر مصرف (توکن گزارش‌شده، Unknown، هزینه، شکست، محدودیت provider و نقش)، MCP با سرور واقعی stdio (سطح پیش‌فرض، نادیده‌گرفتن annotation، env بدون کلید، allow/deny، سرور خراب)، ایجنت‌ها با سرور HTTP محلی (نقل‌قول، تأیید، idempotency، پاسخ کاربر، سلامت، ری‌استارت، توقف) و سیم‌کشی `ToolAgent`.
- مجموعه‌ی تست‌های قبلی: همه سبز به‌جز موارد زیر که **در v6 هم دقیقاً همین‌طور بودند** (تغییر ما نیستند): `test_image_search` (نیاز به PySide6 در محیط تست)، `test_release::requirements` (تست قدیمی `psutil` را نمی‌شناسد)، و سه تست `test_streaming` (تست‌ها انتظار chunkهای جدا دارند ولی `LeakGuard` چند حرف اول را جمع می‌کند؛ یک مورد آن واقعاً نشان می‌دهد قطع ارتباط بعد از متن خیلی کوتاه می‌تواند به failover برسد).
- تست‌های GUI (PySide6) در این محیط اجرا نشدند (skipped).

**هنوز نیاز به اعتبارسنجی روی Windows 11:** فهرست‌های هر بخش در `MEMORY_EVIDENCE_FA`، `BRAIN_FA`، `MCP_AGENTS_FA` و `USAGE_FA`، به‌علاوه‌ی اجرای کامل برنامه با GUI و `run_tests.bat`.

---

## v13 — T5-A: عامل فایل

مستندات: `docs/FILE_AGENT_FA.md`.

**فایل جدید:** `kira/tools/fileagent.py`، `tests/test_file_agent.py` (۱۰ تست)، `docs/FILE_AGENT_FA.md`
**تغییرها:** `kira/tools/builtin.py` (ثبت)، `kira/tools/protocol.py` (کلمات دروازه‌ی دسته‌ی files: کپی، تغییر نام، مرتب کن، undo ...)، `kira/tools/agent.py` (برچسب‌ها).
**عمداً پیاده نشد:** Word/PDF، کنترل UI (T5-B به بعد)، حذف دائمی (همه‌ی حذف‌ها به سطل بازیافت می‌روند).

---

## v14 — T5-B: تعامل با دسکتاپ

مستندات: `docs/DESKTOP_FA.md`.

**فایل جدید:** `kira/tools/desktop.py`، `tests/test_desktop.py` (۱۴ تست با Backend جعلی)، `docs/DESKTOP_FA.md`
**تغییرها:** `wincontrol.py` (دامنه‌ی desktop)، `builtin.py` (ثبت ماژول)، `protocol.py` (دسته‌ی desktop و `DESKTOP_RULES`)، `agent.py` (برچسب‌ها و قواعد).
**عمداً پیاده نشد:** Word/Office (T5-C)، روشنایی/Wi-Fi (T5-D)، اسکرین‌شات و بینایی، کلید Windows و میانبرهای سیستمی.
**هشدار صادقانه:** منطق سیاست‌ها تست شده؛ خود فراخوانی‌های Win32 و اسکریپت UI Automation فقط روی Windows قابل اجرا هستند و اینجا اجرا نشده‌اند.
