[English](DEPENDENCY_LOCKS.md) — [راهنمای نصب](USER_GUIDE.md)

# قفل تکرارپذیر وابستگی‌ها

هدف Kira ویندوز ۱۱ با معماری x86-64 و Python نسخه‌های ۳.۱۱ و ۳.۱۲ است. فایل‌های اصلی requirements بازه‌های سازگاری را نگه می‌دارند؛ فایل‌های Lock تولیدشده، نتیجهٔ کامل حل وابستگی‌های مستقیم و غیرمستقیم را همراه با هش SHA-256 برای هر گروه نصب و هر نسخهٔ Python ثبت می‌کنند.

## تولید یا به‌روزرسانی Lockها

این دستورها را در ریشهٔ مخزن و روی ویندوزی اجرا کنید که به یک مخزن بستهٔ Python دسترسی دارد:

\`\`\`powershell
py -3.12 -m pip install --upgrade uv
py -3.12 scripts/generate_dependency_locks.py
\`\`\`

ابزار، همهٔ گروه‌ها را برای هر دو نسخهٔ پشتیبانی‌شدهٔ Python و هدف \`x86_64-pc-windows-msvc\` حل می‌کند. خروجی در مسیرهای \`dependency-locks/windows-x86_64/python311/\` و \`dependency-locks/windows-x86_64/python312/\` ذخیره می‌شود.

اگر مخزن پیش‌فرض PyPI در دسترس نبود ولی یک آینهٔ معتبر در دسترس بود، نشانی PEP 503 آن را بدهید:

\`\`\`powershell
py -3.12 scripts/generate_dependency_locks.py --index-url https://<approved-mirror>/simple
\`\`\`

می‌توان همین نشانی را در متغیر محیطی \`KIRA_PYPI_INDEX\` قرار داد. اطلاعات ورود نباید داخل فایل‌های Commitشده یا خروجی دستورها ثبت شوند. ابزار نشانی را از طریق متغیر محیطی به uv می‌دهد و سربرگ تولیدشده را به نام خود اسکریپت محدود می‌کند.

هر فایل تولیدشده شامل نسخهٔ دقیق بسته‌ها و هش آن‌هاست. ابتدا همهٔ گروه‌ها در پوشهٔ موقت حل می‌شوند و فقط پس از موفقیت همهٔ آن‌ها، پوشهٔ Lock جایگزین می‌شود. در صورت شکست Resolve، Lockهای قبلی دست‌نخورده می‌مانند. گروه موتور Kitten عمداً با \`--no-deps\` حل می‌شود تا وابستگی‌های اختیاری PyTorch آن، مطابق تصمیم فعلی Kira، وارد نصب نشوند.

## گروه‌ها

| نام Lock | فایل نیازمندی منبع |
|---|---|
| \`core\` | \`requirements.txt\` |
| \`system-optional\` | \`requirements-system-optional.txt\` |
| \`ocr\` | \`requirements-ocr.txt\` |
| \`audio\` | \`requirements-audio.txt\` |
| \`dev\` | \`requirements-dev.txt\` |
| \`voice-local\` | \`requirements-voice-local.txt\` |
| \`voice-kitten\` | \`requirements-voice-kitten.txt\` |
| \`voice-kitten-engine\` | \`requirements-voice-kitten-engine.txt\` |

پس از تولید موفق، پوشهٔ \`dependency-locks/\` را بررسی و Commit کنید. نسخه‌ها و هش‌های تولیدشده را دستی تغییر ندهید؛ تغییر را در فایل‌های requirements یا constraints اعمال و Lock را دوباره تولید کنید.

پس از Commit فایل‌های تولیدشده، `install_deps.py` به‌صورت خودکار Lock متناسب با Windows x64 و نسخهٔ Python فعال را انتخاب می‌کند و با `--require-hashes` اعتبار همهٔ Hashها را به pip می‌سپارد. تا زمانی که Lock متناظر وجود نداشته باشد، نصب‌کننده همچنان از فایل‌های requirements و constraints فعلی استفاده می‌کند.

این Lockها مختص محیط هدف هستند. برای سیستم‌عامل، معماری پردازنده یا نسخهٔ Python متفاوت، باید هدف Resolver و مجموعهٔ Lock جداگانه‌ای تعریف شود.
