# افزودن Provider و Model

## افزودن مدل جدید به Provider موجود (مثلاً یک مدل دیگر روی Groq)
تب Route ← **افزودن Route** ← Provider را انتخاب کن ← Model ID را دقیق بنویس (مثل `openai/gpt-oss-20b`) ← تأیید.
همان کلید Provider استفاده می‌شود. اگر همان مدل قبلاً برای آن Provider ثبت شده باشد، پیام خطا می‌گیری.

## افزودن Provider جدید (هر سرویس سازگار با OpenAI Chat Completions)
تب Route ← پایین صفحه **افزودن Provider جدید** ← پر کن:
- **نام**: هر اسمی (در نشانگر نمایش داده می‌شود).
- **Base URL تا `/v1`**: مثلاً `https://api.together.xyz/v1` ، `https://api.deepinfra.com/v1/openai` ، `http://localhost:1234/v1` (LM Studio).
- **API Key**: برای سرویس ابری لازم است؛ برای سرور محلی خالی بگذار و «سرور محلی» را تیک بزن.
- **اولین Model ID** (اختیاری؛ بعداً هم می‌شود افزود).
سپس «تست اتصال Provider» را بزن. Kira به آدرس `Base URL/models` و `Base URL/chat/completions` درخواست می‌فرستد.
حذف: دکمه‌ی «حذف Provider» (Routeهایش هم حذف می‌شوند). Providerهای پیش‌فرض فقط غیرفعال می‌شوند.

## Cloudflare
علاوه بر کلید، **Account ID** لازم است. مدل مثل `@cf/meta/llama-3.1-8b-instruct`.

## Ollama
1. `ollama pull qwen3.5:4b` (یا `download_model.bat`).
2. تب Route ← «یافتن مدل‌های Ollama» تا Route همه‌ی مدل‌های نصب‌شده ساخته شود (غیرفعال).
3. Routeهای دلخواه را فعال و ترتیب بده. آدرس Ollama و Context/Keep-alive پیش‌فرض در تب «دستیار» است.
نکته‌ی بازی: هر مدل محلی فعال ممکن است رم/VRAM بگیرد؛ فقط مدل لازم را فعال نگه دار و Keep-alive را کوتاه بگذار.

## کلید جدید یا عوض کردن کلید
در کادر API Key کلید جدید را بنویس و از کادر خارج شو (Enter/Tab)؛ خودکار رمزگذاری و ذخیره می‌شود.
