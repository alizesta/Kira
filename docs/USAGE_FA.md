# ردیابی مصرف و هزینه

کد: `kira/usage.py`. دیتابیس: `kira_usage.sqlite3` در پوشه‌ی داده (بیرون از پوشه‌ی برنامه). فقط عدد و شناسه ذخیره می‌شود؛ هرگز پرامپت، پاسخ یا کلید.

## نمایش
- در چت: `/usage` (امروز) یا `/usage 7` (۷ روز اخیر) — بدون تماس با مدل.
- خارج از برنامه: `python -m kira.usage 7`.

## قواعد
- **توکن** فقط اگر سرویس گزارش کرده باشد؛ وگرنه `Unknown`. هیچ عددی از طول متن حدس زده نمی‌شود.
- **هزینه:** `reported` (سرویس خودش داده، مثل OpenRouter) جدا از `estimated` (توکن گزارش‌شده × قیمتی که خودت در `model_prices` نوشته‌ای)؛ وگرنه Unknown. مدل محلی: «محلی».
- منابع توکن: پاسخ غیراستریم همه‌ی سرویس‌ها؛ استریم برای Groq و OpenRouter با `stream_options.include_usage` (قابل خاموش کردن با `usage_stream_options=false` در تنظیمات همان provider)؛ Ollama از شمارنده‌های خودش؛ سرور سفارشی فقط اگر خودش در آخرین chunk بفرستد. Embedding هم ثبت می‌شود.
- هر ردیف: نقش (surface/deep/reflection/memory/embedding)، provider، مدل، route، وضعیت، تعداد و علت failover، زمان اتصال/اولین توکن/کل.

## تنظیمات (`settings.json`)
```json
"model_prices": {"groq:llama-3.3-70b": {"input_per_million": 0.59, "output_per_million": 0.79}},
"usage_limits": {
  "role:deep": {"requests_per_day": 40, "tokens_per_day": 200000, "action": "block"},
  "provider:openrouter": {"requests_per_day": 200, "action": "warn"}
}
```
(کلید می‌تواند `provider:model`، فقط `model` یا فقط `provider` باشد؛ قیمت‌ها نمونه‌اند؛ مقدار و واحد پول را خودت مشخص می‌کنی.)
- `warn`: فقط در `/usage` هشدار می‌دهد.
- `block` روی provider: route‌هایش از failover کنار می‌روند، ولی فقط تا وقتی route قابل‌استفاده‌ی دیگری هست؛ گفتگو هرگز قطع نمی‌شود.
- `block` روی نقش deep/reflection/memory: آن نقش به مسیر عادی برمی‌گردد یا کار پس‌زمینه انجام نمی‌شود. نقش surface فقط هشدار می‌گیرد.
- محدودیت توکن فقط توکن‌های گزارش‌شده را می‌شمارد.

## محدودیت‌ها
- UI تغییر نکرد. پشتیبان‌گیری خودکار از `kira_usage.sqlite3` اضافه نشد (داده‌ی قابل‌بازسازی و کم‌اهمیت است).
- درخواست‌های ابزار/تحقیق وب که خودشان مدل صدا نمی‌زنند ثبت نمی‌شوند.

## نیاز به اعتبارسنجی روی Windows
1. `/usage` بعد از چند پیام روی هر provider: ردیف‌ها و Unknown درست.
2. Groq / OpenRouter استریم: ارسال `stream_options` خطا ندهد و توکن ثبت شود.
3. Ollama: توکن‌ها از شمارنده‌ی خودش.
4. `block` روی یک provider با route جایگزین؛ و وقتی جایگزین نیست.
