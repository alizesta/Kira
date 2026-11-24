# Reverse API — هستهٔ اتصال (Task 1)

Reverse API یک Provider استاندارد Kira است؛ مغز یا مسیر پیام جداگانه ندارد.

## معماری

```
Chat/Brain → HybridRouter → ReverseApiProvider (ChatProvider) → ReverseTransport (ثبت‌شده در TRANSPORTS)
```

- `kira/core/interfaces/reverse_transport.py`: قرارداد Transport (`status`, `stream`, `abort`) و نوع‌های خطا/وضعیت. فقط stdlib.
- `kira/reverse_api/provider.py`: `ReverseApiProvider(BaseProvider)`. پیام‌ها، System Prompt، حافظه و History همان‌طور که Router به همهٔ Providerها می‌دهد می‌آیند؛ این ماژول فقط آن‌ها را به یک پرامپت واحد تبدیل می‌کند (`prompt.py`).
- `kira/reverse_api/registry.py`: `TRANSPORTS` — Transport داخلی `deepseek` به‌صورت خودکار ثبت می‌شود. Factory به ازای هر درخواست صدا زده می‌شود (Router هر بار Provider تازه می‌سازد)؛ Transport نشست‌دار یک نمونهٔ مشترک دارد.
- `ProviderRegistry` اکنون آداپترهای Lazy دارد؛ `reverse_api` هنگام اولین resolve import می‌شود.
- `routes.add_reverse_api_provider(settings, transport)` Provider را (کلید `providers["reverse_api"]`) با پیش‌فرض **خاموش** و بدون هیچ اطلاعات محرمانه ثبت می‌کند. `requires_key` برای این نوع False است.

## رفتارها

- Streaming/Cancellation: `stream()` و `abort()` استاندارد؛ `cancel_event` روتر هم رعایت می‌شود.
- Tools/Function Calling: Provider عمداً `chat_with_tools` ندارد؛ Router آن را برای Native Tools رد می‌کند و ابزارها از مسیر مشترک Kira می‌روند.
- خطاها: Transport کاملاً نصب‌نشده → `missing`؛ Session برقرار نیست → `auth`؛ در حال اتصال/خطای موقت → `network` (قابل تکرار). همهٔ پیام‌ها از مقادیر حساس پاک می‌شوند (کلیدهای `key/token/cookie/session/secret/password/authorization`).
- تصویر: فقط وقتی Transport `supports_images=True` اعلام کند.
- `probe()` فقط وضعیت Session را می‌خواند و درخواست تولید نمی‌فرستد.

## فعال‌سازی در Route Manager (Task 4)

- بعد از ورود موفق، دکمهٔ «انتخاب DeepSeek برای چت» یک Provider از نوع `reverse_api` و یک Route با شناسهٔ مدل نمایشی `deepseek-web` می‌سازد یا Route موجود را دوباره فعال می‌کند.
- Route بدون API Key کار می‌کند؛ احراز هویت فقط از نشست رمزگذاری‌شدهٔ DeepSeek استفاده می‌کند.
- با فعال‌سازی، Route در حالت انتخاب دستی چت قرار می‌گیرد. برای برگشت به مسیرهای اولویت‌بندی‌شده، گزینهٔ «خودکار» در Route Manager را انتخاب کن.
- تست اتصال Route فقط وضعیت نشست را می‌خواند و پیام تولیدی ارسال نمی‌کند.

## ورود DeepSeek و نشست (Task 2)

- دکمهٔ «ورود به حساب DeepSeek» در صفحهٔ Providerها اضافه شده است.
- ورود ابتدا با Chrome نصب‌شده باز می‌شود؛ اگر Chrome یا Playwright قابل اجرا نباشد، پنجرهٔ ورود داخلی Kira با Qt WebEngine باز می‌شود.
- بعد از شناسایی محیط چت، Cookieها، Local Storage و Session Storage جمع‌آوری و با Windows DPAPI برای همان حساب ویندوز رمزگذاری می‌شوند؛ فایل نشست در پوشهٔ دادهٔ Kira و با نوشتن اتمیک ذخیره می‌شود.
- محتوای Cookie/Token به UI یا لاگ برگردانده نمی‌شود. پاک‌کردن نشست از طریق `DeepSeekSessionStore.clear()` انجام می‌شود.
- Playwright به‌عنوان وابستگی برای Transport Headless تسک ۳ اضافه شده است؛ ورود اولیهٔ Chrome از همان بسته استفاده می‌کند.

## محدودیت‌های فعلی

- `kira/reverse_api/deepseek_transport.py` نشست رمزگذاری‌شده را در Chromium Headless بارگذاری می‌کند، Session Storage را پیش از بارگذاری صفحه تزریق می‌کند، پیام را در چت می‌فرستد و متن پاسخ را به‌شکل chunk برمی‌گرداند. Transport با شناسهٔ `deepseek` به‌صورت خودکار ثبت شده است.
- درخواست‌ها در هر نشست مرورگر به‌صورت ترتیبی اجرا می‌شوند؛ لغو از طریق cancel event بررسی می‌شود و مرورگر پس از هر درخواست بسته می‌شود.
- تشخیص کادر پیام و پاسخ به selectorهای رابط فعلی DeepSeek وابسته است؛ اگر ساختار DOM تغییر کند، خطای مشخص `response/auth` گزارش می‌شود و باید selectorها به‌روزرسانی شوند.
- دکمهٔ «تست اتصال Route» (`probe_provider`) از `provider.probe()` استفاده می‌کند و فقط وضعیت نشست را می‌خواند؛ هیچ درخواست تولید آزمایشی ارسال نمی‌شود.
- فقط یک اتصال `reverse_api` در یک زمان (انتخاب Transport با فیلد `transport`).
