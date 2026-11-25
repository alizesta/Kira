# مستندات کیرا

این پوشه شامل مستندات فنی و راهبری Project Kira است.

## سیاست زبان مستندات

زبان اصلی مستندات **انگلیسی** است. هر مستند جدید ابتدا به انگلیسی نوشته می‌شود و سپس ترجمهٔ فارسی آن در فایلی با همان نام پایه و پسوند `_FA` قرار می‌گیرد. برای README ریشهٔ مخزن از `README.md` و `README.fa.md` استفاده می‌شود.

بخشی از فایل‌های این مخزن پیش از این سیاست نوشته شده‌اند. آن‌ها با نام فعلی حفظ شده‌اند و زبان موجودشان در فهرست پایین مشخص است. وجود یک مستند فارسی قدیمی به معنی وجود نسخهٔ انگلیسی متناظر نیست. هیچ فایل قدیمی صرفاً به‌دلیل نداشتن ترجمه نباید حذف شود.

## از اینجا شروع کنید

- [راهنمای کاربر](USER_GUIDE_FA.md) — نصب، اجرای نخست، تنظیمات و کارهای روزمره.
- [تنظیمات زبان رابط](LANGUAGE_SETTINGS_FA.md) — پیش‌فرض انگلیسی، انتخاب فارسی، ذخیره‌سازی و راست‌به‌چپ.
- [مدخل معماری](../ARCHITECTURE.md) — پیوند به مراجع اصلی معماری.
- [معماری جامع](ARCHITECTURE_MASTER.md) — مرزبندی زیرسامانه‌ها و ترکیب فعلی برنامه.
- [مالکیت ماژول‌ها](MODULE_OWNERSHIP.md) — قرارداد مالکیت و وابستگی‌ها.
- [نقشهٔ راه معماری](ARCHITECTURE_ROADMAP.md) — بدهی فنی تأییدشده و ترتیب کارهای مهندسی.

## مستندات فنی انگلیسی

### معماری و مهندسی
- [چرخهٔ عمر قابلیت‌های برنامه](APPLICATION_FEATURE_LIFECYCLE.md)
- [گزارش تحویل پیاده‌سازی معماری](ARCHITECTURE_IMPLEMENTATION_HANDOFF_2026-11-18.md)
- [معماری جامع](ARCHITECTURE_MASTER.md)
- [نقشهٔ راه معماری](ARCHITECTURE_ROADMAP.md)
- [مرزهای دامنه و لایهٔ برنامه](DOMAIN_APPLICATION_BOUNDARIES.md)
- [مالکیت ماژول‌ها](MODULE_OWNERSHIP.md)
- [مهارت‌های مشترک](SHARED_SKILLS.md)

### چت و ذخیره‌سازی
- [سرویس برنامهٔ چت](CHAT_APPLICATION_SERVICE.md)
- [پیوست‌های چت](CHAT_ATTACHMENTS.md)
- [دستورهای چت](CHAT_COMMANDS.md)
- [چرخهٔ عمر مکالمه](CHAT_CONVERSATION_LIFECYCLE.md)
- [رویدادهای چت](CHAT_EVENTS.md)
- [سازمان‌دهی گفتگوها](CHAT_ORGANIZATION.md)
- [جست‌وجو و بازیابی گفتگو](CHAT_SEARCH_RETRIEVAL.md)
- [انتقال گفتگو](CHAT_TRANSFER.md)
- [آداپتور فایل انتقال گفتگو](CHAT_TRANSFER_FILE_ADAPTER.md)

### اجرا، کارایی و کیفیت
- [کارایی در زمان بی‌کاری](IDLE_PERFORMANCE.md)
- [کارایی راه‌اندازی](STARTUP_PERFORMANCE.md)
- [گزارش رگرسیون QA — وظایف ۰۰۱ تا ۰۱۵](QA_TASKS_001_015_REGRESSION_REPORT.md)

## مستندات فنی فارسی

فایل‌های زیر در حال حاضر فارسی هستند و بدون تغییر حفظ شده‌اند. برای تکمیل جفت زبانی، نسخهٔ انگلیسی آن‌ها باید پیش از بازنویسی یا کنارگذاشتن نسخهٔ اصلی اضافه شود.

### برنامه و ایجنت
- [حالت فعال](ACTIVE_MODE_FA.md)
- [ایجنت](AGENT_FA.md)
- [ایجنت فایل](FILE_AGENT_FA.md)
- [ایجنت‌های MCP](MCP_AGENTS_FA.md)

### هوش مصنوعی، مدل و مسیریابی
- [افزودن Provider و مدل](ADD_PROVIDER_AND_MODEL_FA.md)
- [مدیر API](API_MANAGER_FA.md)
- [مغز](BRAIN_FA.md)
- [Gemini Live](GEMINI_LIVE_FA.md)
- [ذخیره‌سازی Ollama](OLLAMA_STORAGE_FA.md)
- [راهنمای Route Manager](ROUTE_MANAGER_GUIDE_FA.md)

### شخصیت، احساس و حافظه
- [شخصیت](CHARACTER_FA.md)
- [موتور تصمیم‌گیری شخصیت](CHARACTER_DECISION_ENGINE_FA.md)
- [پروفایل شخصیت‌ها](CHARACTER_PROFILES_FA.md)
- [اجرای عاطفی](EMOTIONAL_RUNTIME_FA.md)
- [وضعیت عاطفی](EMOTIONAL_STATE_FA.md)
- [تبدیل متن به گفتار مبتنی بر احساس](EMOTION_DRIVEN_TTS_FA.md)
- [موتور ابتکار عمل](INITIATIVE_ENGINE_FA.md)
- [حافظهٔ شواهدمحور](MEMORY_EVIDENCE_FA.md)

### دسکتاپ، بینایی، صدا و ابزارها
- [دسکتاپ](DESKTOP_FA.md)
- [بینایی زندهٔ دسکتاپ](LIVE_DESKTOP_VISION_FA.md)
- [صدای محلی](LOCAL_VOICE_FA.md)
- [گفتار جمله‌به‌جمله](SENTENCE_SPEECH_FA.md)
- [دسترسی به سیستم](SYSTEM_ACCESS_FA.md)
- [ابزارها](TOOLS_FA.md)
- [بینایی](VISION_FA.md)
- [مسیریابی صدا](VOICE_ROUTE_FA.md)
- [تحقیق وب](WEB_RESEARCH_FA.md)
- [کنترل ویندوز](WINDOWS_CONTROL_FA.md)

### انتشار، مهاجرت و رابط کاربری
- [اجرای برنامه](APP_LAUNCH_FA.md)
- [مدیر صوت](AUDIO_MANAGER_FA.md)
- [حرکت آواتار — وظیفهٔ ۲](AVATAR_MOTION_TASK_2_FA.md)
- [تغییرات و ادغام](CHANGES_INTEGRATION_FA.md)
- [پایهٔ حرکت رابط](UI_MOTION_FOUNDATION_FA.md)
- [مصرف و هزینه](USAGE_FA.md)
- [فرادادهٔ نسخه](VERSION_METADATA_FA.md)
- [چک‌لیست Windows 11](WINDOWS11_CHECKLIST_FA.md)

## فایل‌های مرجع دیگر

- [نمونهٔ پیکربندی Kira MCP](kira_mcp.example.json)

## قواعد نگهداری مستندات

۱. ابتدا متن کامل مستند انگلیسی نوشته شود.
۲. پس از تثبیت نسخهٔ انگلیسی، ترجمهٔ فارسی آن در فایل متناظر با پسوند `_FA.md` ثبت شود.
۳. عنوان‌ها، ترتیب بخش‌ها، پیوندها، شناسه‌های فنی، مسیر فایل‌ها، دستورها، محدودیت‌ها و هشدارها در هر دو زبان هم‌راستا بمانند.
۴. شناسه‌های کد، کلیدهای تنظیمات، نام دستورها، نام APIها و مسیرهای لفظی فایل ترجمه نشوند.
۵. با تغییر پیاده‌سازی، نسخهٔ انگلیسی و ترجمهٔ فارسی آن در یک مجموعه‌تغییر به‌روز شوند.
۶. قابلیتی فقط زمانی پیاده‌سازی‌شده اعلام شود که کد یا تست آن را تأیید کند.
۷. گزارش‌های تاریخی به‌عنوان snapshot تاریخی باقی بمانند؛ نتایج قدیمی تست نباید به‌عنوان تأیید فعلی معرفی شوند.
