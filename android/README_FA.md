# Kira Android

کلاینت Native اندروید Kira است و مستقل از نسخه ویندوز اجرا می‌شود. هسته‌ی موبایل روی خود گوشی است و برای استفاده از مدل‌های ابری فقط به API Key مستقیم Provider نیاز دارد؛ سرور Kira و حساب ابری اجباری نیستند.

## معماری محلی
- core/LocalKiraCore.kt: موتور محلی اندروید، Routeها، درخواست مستقیم مدل و مدیریت داده‌ها
- SQLite خصوصی برنامه: تاریخچه چت، حافظه بلندمدت، تنظیمات Provider و فهرست مهارت‌ها
- Android Keystore + AES/GCM: رمزنگاری API Keyها در همان دستگاه
- files/kira/library: کتابخانه محلی Skillها؛ هنگام اولین اجرا خودکار ساخته می‌شود
- KiraChatScreen.kt: چت محلی Kira/Ren/Mika
- KiraRouteScreen.kt: افزودن API Key، Model ID، Base URL و اولویت Failover
- KiraMemoryScreen.kt: حافظه محلی شخصیت‌ها
- assistant/AiAssistantOverlayService.kt: حباب شناور دستیار

Providerهای آماده: OpenRouter، Groq، Mistral، DeepSeek و Gemini. آدرس‌های سفارشی HTTPS نیز برای APIهای سازگار با OpenAI قابل ثبت هستند. درخواست‌ها مستقیماً از گوشی به سرویس‌دهنده ارسال می‌شوند و از سرور واسط Kira عبور نمی‌کنند.

## محل داده‌ها
داده‌ها در فضای خصوصی اپلیکیشن اندروید قرار دارند:
- پایگاه داده: kira_local_core.db
- کلیدهای رمزنگاری‌شده: دیتابیس خصوصی، با کلید اصلی نگهداری‌شده در Android Keystore
- کتابخانه: files/kira/library

حذف اپلیکیشن ممکن است داده‌های خصوصی آن را نیز حذف کند؛ پیش از حذف برنامه باید از داده‌ها نسخه پشتیبان تهیه شود. همگام‌سازی اختیاری بین ویندوز و اندروید هنوز پیاده‌سازی نشده است.

## ابزار ساخت
- Android Gradle Plugin 9.5.x
- Gradle Wrapper همراه پروژه
- JDK 17
- Android SDK API 37
- Kotlin Built-in از مسیر AGP 9
- Jetpack Compose BOM 2026.09.00

ساخت APK با دستور ./gradlew --no-daemon :app:assembleDebug انجام می‌شود.
خروجی: app/build/outputs/apk/debug/app-debug.apk

## دریافت APK
با هر Push به شاخه‌ی feature/android-ai-assistant، Workflow با نام Android APK فایل Debug را می‌سازد. از آخرین اجرای موفق GitHub Actions، Artifact با نام Kira-Android-debug-APK را دانلود و ZIP را استخراج کن.

این APK نسخه Debug است، نه نسخه امضاشده برای انتشار عمومی.

## وضعیت قابلیت‌ها
- چت و تاریخچه محلی: فعال
- Route و API Key رمزنگاری‌شده: فعال
- اولویت و Failover بین Providerها: فعال
- حافظه محلی Kira/Ren/Mika: فعال
- ساخت خودکار پوشه Library: فعال
- همگام‌سازی اختیاری بین دستگاه‌ها: در برنامه توسعه
- اجرای مدل GGUF/Ollama مستقیماً روی اندروید: هنوز پیاده‌سازی نشده
- AI Assistant، Screen Context و Voice: در حال توسعه و وابسته به مجوز صریح کاربر
