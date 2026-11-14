# Version Metadata و Developer Attribution (قانون اجباری)

این سند قانون ثبت‌شده در `PROJECT_CONTEXT.md` (بخش «Version metadata and developer attribution») را توضیح می‌دهد. رعایت آن برای همه‌ی توسعه‌دهندگان و Agentها (Codex، OpenCode، Claude Code، ChatGPT) الزامی است.

## چه چیزی و کجا نمایش داده می‌شود
در **تنظیمات → عمومی** یک گروه «درباره» اضافه شده است با چهار ردیف:

| ردیف | مقدار | فرمت |
| --- | --- | --- |
| Version | `VERSION` از `kira/config.py` | یک خط، شروع با رقم (مثلاً `1 stable`) |
| Build Date | تاریخ ساخت به میلادی | `YYYY-MM-DD` |
| Build Time | ساعت ساخت، ۲۴ ساعته (Asia/Tehran) | `HH:MM` |
| Developer | ابزار توسعه‌دهنده‌ی تشخیص‌داده‌شده | دقیقاً یکی از چهار نام مجاز |

هیچ‌کدام دستی تایپ نمی‌شود: نسخه از `kira/config.py` و سه مقدار دیگر از `kira/build_info.py` (فایل تولیدشده) خوانده می‌شوند. `kira/about.py` این چهار ردیف را برای رابط کاربری آماده می‌کند و اگر `build_info.py` وجود نداشته باشد، به‌جای خطا مقدار `unknown` نشان می‌دهد.

## منبع واحد هر مقدار
- **نسخه:** فقط `VERSION` در `kira/config.py`. جای دیگری نسخه دستی نگه داشته نمی‌شود.
- **Build Date / Build Time / Developer:** فقط `kira/build_info.py`. این فایل را `scripts/build_metadata.py` در هر Build و Release بازنویسی می‌کند؛ **دستکاری دستی آن ممنوع است**.
- **تغییرات:** `CHANGELOG.md`. هر تغییر علاوه بر Changelog / Release Notes باید نسخه و فراداده‌ی سازنده را هم به‌روز نگه دارد.

## تشخیص خودکار توسعه‌دهنده
`scripts/build_metadata.py` نام ابزار را به این ترتیب تعیین می‌کند و اولین مقدار معتبر برنده است:

1. متغیر صریح `KIRA_DEVELOPER` (مثلاً `KIRA_DEVELOPER=Codex`). مقدار ناشناخته خطاست.
2. نشانه‌های میزبان Build/Release: `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT` → Claude Code، `CODEX_SANDBOX` / `CODEX_HOME` → Codex، `OPENCODE` / `OPENCODE_SESSION_ID` → OpenCode، و `AI_AGENT` / `AGENT` (مقدار نرمال‌سازی می‌شود).
3. مقدار ثبت‌شده‌ی قبلی در `kira/build_info.py`.
4. نام نویسنده/کامیت‌کننده‌ی Git.
5. اگر هیچ‌کدام نتیجه ندهد: خطا (`MetadataError`). مقدار پیش‌فرض یا حدسی وجود ندارد.

نام‌های پذیرفته‌شده فقط `Codex`، `OpenCode`، `Claude Code` و `ChatGPT` هستند (با نرمال‌سازی املاهای رایج مثل `opencode`، `open-code`، `claude`، `chatgpt`). هر نام دیگری Release را متوقف می‌کند.

## اعتبارسنجی در Build و Release
- **CI:** قدم «Validate version and build metadata» دستور `python scripts/build_metadata.py --check` را اجرا می‌کند. این دستور چیزی را بازنویسی نمی‌کند و فقط نسخه، تاریخ، ساعت، سازنده و اشاره‌ی `CHANGELOG.md` به نسخه‌ی جاری را بررسی می‌کند.
- **اسکریپت Release:** `scripts/build_release.py` در ابتدای `main()` تابع `ensure_release_metadata()` را صدا می‌زند: اول `kira/build_info.py` را با زمان فعلی تهران و سازنده‌ی تشخیص‌داده‌شده بازتولید می‌کند، بعد همان اعتبارسنجی را انجام می‌دهد. اگر مشکلی باشد، با پیام `Release stopped: …` و کد خروج غیرصفر متوقف می‌شود و ZIP ساخته نمی‌شود.
- خروجی هر دو مسیر JSON کامل فراداده را چاپ می‌کند تا در لاگ Build/Release قابل استناد باشد.

## کارهایی که هر توسعه‌دهنده باید انجام دهد
1. اگر Release نسخه‌ی جدید است، `VERSION` را در `kira/config.py` به‌روز کن.
2. یک بخش جدید در بالای `CHANGELOG.md` اضافه کن که رشته‌ی همان `VERSION` را داشته باشد (شرط اعتبارسنجی).
3. در محیط Build/Release مطمئن شو نشانه‌ی ابزار یا `KIRA_DEVELOPER` درست تنظیم شده است تا سازنده اشتباه ثبت نشود.
4. قبل از Commit/Release این را اجرا کن:
   ```bash
   python scripts/build_metadata.py --check
   ```
   سپس در صورت نیاز یک‌بار بدون `--check` اجرا کن تا `kira/build_info.py` مُهر بخورد.
5. برای رفتار جدید تست رگرسیون اضافه کن؛ تست‌های این قانون در `tests/test_build_metadata.py` هستند و یک بررسی رابط کاربری هم در `tests/test_chat_code_gui.py` قرار دارد.

## نکته‌ی نگهداری
`scripts/build_stage3_release.py` یک مسیر یک‌بارمصرف و قدیمی برای بازسازی آرشیو Stage 3 است و بخشی از جریان Build/Release فعلی نیست؛ دروازه‌ی فراداده روی `scripts/build_release.py` و CI اعمال می‌شود.
