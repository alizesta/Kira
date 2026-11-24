# Reverse API — هستهٔ اتصال (Task 1)

Reverse API یک Provider استاندارد Kira است؛ مغز یا مسیر پیام جداگانه ندارد.

## معماری

```
Chat/Brain → HybridRouter → ReverseApiProvider (ChatProvider) → ReverseTransport (ثبت‌شده در TRANSPORTS)
```

- `kira/core/interfaces/reverse_transport.py`: قرارداد Transport (`status`, `stream`, `abort`) و نوع‌های خطا/وضعیت. فقط stdlib.
- `kira/reverse_api/provider.py`: `ReverseApiProvider(BaseProvider)`. پیام‌ها، System Prompt، حافظه و History همان‌طور که Router به همهٔ Providerها می‌دهد می‌آیند؛ این ماژول فقط آن‌ها را به یک پرامپت واحد تبدیل می‌کند (`prompt.py`).
- `kira/reverse_api/registry.py`: `TRANSPORTS` — Task 2/3 برای ثبت Transport واقعی از آن استفاده می‌کنند. Factory به ازای هر درخواست صدا زده می‌شود (Router هر بار Provider تازه می‌سازد)؛ Transportهایی که Session دارند باید یک نمونهٔ مشترک برگردانند.
- `ProviderRegistry` اکنون آداپترهای Lazy دارد؛ `reverse_api` هنگام اولین resolve import می‌شود.
- `routes.add_reverse_api_provider(settings, transport)` Provider را (کلید `providers["reverse_api"]`) با پیش‌فرض **خاموش** و بدون هیچ اطلاعات محرمانه ثبت می‌کند. `requires_key` برای این نوع False است.

## رفتارها

- Streaming/Cancellation: `stream()` و `abort()` استاندارد؛ `cancel_event` روتر هم رعایت می‌شود.
- Tools/Function Calling: Provider عمداً `chat_with_tools` ندارد؛ Router آن را برای Native Tools رد می‌کند و ابزارها از مسیر مشترک Kira می‌روند.
- خطاها: Transport کاملاً نصب‌نشده → `missing`؛ Session برقرار نیست → `auth`؛ در حال اتصال/خطای موقت → `network` (قابل تکرار). همهٔ پیام‌ها از مقادیر حساس پاک می‌شوند (کلیدهای `key/token/cookie/session/secret/password/authorization`).
- تصویر: فقط وقتی Transport `supports_images=True` اعلام کند.
- `probe()` فقط وضعیت Session را می‌خواند و درخواست تولید نمی‌فرستد.

## محدودیت‌های فعلی (عمدی)

- هیچ Transport واقعی وجود ندارد (مرورگر/ورود/Session/Headless = Task 2 و 3). تا آن موقع Provider خاموش است و درخواست به خطای `missing` می‌خورد.
- دکمهٔ «تست اتصال Route» (`probe_provider`) از `provider.probe()` استفاده می‌کند و فقط وضعیت نشست را می‌خواند؛ هیچ درخواست تولید آزمایشی ارسال نمی‌شود.
- فقط یک اتصال `reverse_api` در یک زمان (انتخاب Transport با فیلد `transport`).
