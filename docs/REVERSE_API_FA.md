# Reverse API — هستهٔ اتصال (Task 1)

Reverse API یک Provider استاندارد Kira است؛ مغز یا مسیر پیام جداگانه ندارد.

## معماری

```
Chat/Brain → HybridRouter → ReverseApiProvider (ChatProvider) → ReverseTransport (ثبت‌شده در TRANSPORTS)
```

- `kira/core/interfaces/reverse_transport.py`: قرارداد Transport (`status`, `stream`, `abort`) و نوع‌های خطا/وضعیت. فقط stdlib.
- `kira/reverse_api/provider.py`: `ReverseApiProvider(BaseProvider)`. پیام‌ها، System Prompt، حافظه و History همان‌طور که Router به همهٔ Providerها می‌دهد می‌آیند؛ این ماژول فقط آن‌ها را به یک پرامپت واحد تبدیل می‌کند (`prompt.py`).
- `kira/reverse_api/registry.py`: `TRANSPORTS` — Task 3 از آن برای ثبت Transport واقعی استفاده می‌کند. Factory به ازای هر درخواست صدا زده می‌شود (Router هر بار Provider تازه می‌سازد)؛ Transportهایی که Session دارند باید یک نمونهٔ مشترک برگردانند.
- `ProviderRegistry` اکنون آداپترهای Lazy دارد؛ `reverse_api` هنگام اولین resolve import می‌شود.
- `routes.add_reverse_api_provider(settings, transport)` Provider را (کلید `providers["reverse_api"]`) با پیش‌فرض **خاموش** و بدون هیچ اطلاعات محرمانه ثبت می‌کند. `requires_key` برای این نوع False است.

## رفتارها

- Streaming/Cancellation: `stream()` و `abort()` استاندارد؛ `cancel_event` روتر هم رعایت می‌شود.
- Tools/Function Calling: Provider عمداً `chat_with_tools` ندارد؛ Router آن را برای Native Tools رد می‌کند و ابزارها از مسیر مشترک Kira می‌روند.
- خطاها: Transport کاملاً نصب‌نشده → `missing`؛ Session برقرار نیست → `auth`؛ در حال اتصال/خطای موقت → `network` (قابل تکرار). همهٔ پیام‌ها از مقادیر حساس پاک می‌شوند (کلیدهای `key/token/cookie/session/secret/password/authorization`).
- تصویر: فقط وقتی Transport `supports_images=True` اعلام کند.
- `probe()` فقط وضعیت Session را می‌خواند و درخواست تولید نمی‌فرستد.

## ورود DeepSeek و نشست (Task 2)

- دکمهٔ «ورود به حساب DeepSeek» در صفحهٔ Providerها اضافه شده است.
- ورود ابتدا با Chrome نصب‌شده باز می‌شود؛ اگر Chrome یا Playwright قابل اجرا نباشد، پنجرهٔ ورود داخلی Kira با Qt WebEngine باز می‌شود.
- بعد از شناسایی محیط چت، Cookieها و Local Storage جمع‌آوری و با Windows DPAPI برای همان حساب ویندوز رمزگذاری می‌شوند؛ فایل نشست در پوشهٔ دادهٔ Kira و با نوشتن اتمیک ذخیره می‌شود.
- محتوای Cookie/Token به UI یا لاگ برگردانده نمی‌شود. پاک‌کردن نشست از طریق `DeepSeekSessionStore.clear()` انجام می‌شود.
- Playwright به‌عنوان وابستگی برای Transport Headless تسک ۳ اضافه شده است؛ ورود اولیهٔ Chrome از همان بسته استفاده می‌کند.

## محدودیت‌های فعلی

- Transport چت DeepSeek هنوز پیاده‌سازی نشده است؛ Task 3 باید نشست ذخیره‌شده را در مرورگر Headless بارگذاری کند و چرخهٔ ارسال/دریافت پیام را بسازد. تا آن موقع Reverse API برای تولید پاسخ آماده نیست.
- دکمهٔ «تست اتصال Route» (`probe_provider`) از `provider.probe()` استفاده می‌کند و فقط وضعیت نشست را می‌خواند؛ هیچ درخواست تولید آزمایشی ارسال نمی‌شود.
- فقط یک اتصال `reverse_api` در یک زمان (انتخاب Transport با فیلد `transport`).
