# افزودن Provider و Model

## افزودن مدل جدید به Provider موجود
تب Route ← **افزودن Route** ← Provider را انتخاب کن ← Model ID را دقیق وارد کن (مثلاً openai/gpt-oss-20b) ← تأیید.
همان کلید Provider استفاده می‌شود. اگر همان مدل قبلاً برای آن Provider ثبت شده باشد، پیام خطا می‌گیری.

## افزودن Provider جدید
تب Route ← پایین صفحه **افزودن Provider جدید** ← این موارد را وارد کن:
- **نام:** هر اسمی که در نشانگر نمایش داده می‌شود.
- **Base URL تا /v1:** مثلاً https://api.together.xyz/v1، https://api.deepinfra.com/v1/openai یا http://localhost:1234/v1 برای LM Studio.
- **API Key:** برای سرویس ابری لازم است؛ برای سرور محلی خالی بگذار و گزینه «سرور محلی» را فعال کن.
- **اولین Model ID:** اختیاری است و بعداً هم می‌توان افزود.
سپس «تست اتصال Provider» را بزن. حذف Provider سفارشی، Routeهای همان Provider را هم حذف می‌کند؛ Providerهای پیش‌فرض فقط غیرفعال می‌شوند.

## Cloudflare
علاوه بر کلید، **Account ID** لازم است. نمونه Model ID: @cf/meta/llama-3.1-8b-instruct.

## Ollama و مدل محلی Kira

نکته: install.bat در نسخه فعلی Ollama یا مدل چت را نصب نمی‌کند. موتورهای صوتی محلی جداگانه آماده می‌شوند.

برای نصب Ollama و مدل پین‌شده Kira (Qwen3.5-9B Abliterated Q4_K_M)، پس از اجرای install.bat این فرمان را در پوشه پروژه اجرا کن:

    .venv\Scripts\python.exe scripts\setup_local_chat_model.py

این اسکریپت در صورت نیاز نصب/به‌روزرسانی Ollama را امتحان می‌کند، وزن GGUF را با SHA-256 ثابت بررسی می‌کند، مدل kira-qwen3.5-9b-abliterated:q4_k_m را می‌سازد و یک smoke test می‌گیرد.

برای استفاده از مدل دیگر:
1. Ollama را نصب و اجرا کن.
2. در ترمینال اجرا کن: ollama pull MODEL_ID
3. در تب Route گزینه «یافتن مدل‌های Ollama» را بزن تا Route مدل‌های نصب‌شده ساخته شود (در ابتدا غیرفعال).
4. Route موردنظر را فعال و ترتیب failover را تنظیم کن.

هر مدل محلی فعال ممکن است RAM/VRAM مصرف کند؛ فقط مدل لازم را فعال نگه دار و Keep-alive را متناسب با دستگاه تنظیم کن.

## کلید جدید یا عوض‌کردن کلید

در کادر API Key کلید جدید را بنویس و از کادر خارج شو (Enter/Tab)؛ کلید به‌صورت خودکار رمزگذاری و ذخیره می‌شود.
