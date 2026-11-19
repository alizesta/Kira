# Kira Android

کلاینت Native اندروید Kira مستقل از نسخه ویندوز اجرا می‌شود. هسته موبایل روی دستگاه است و برای مدل‌های ابری فقط به API Key مستقیم Provider نیاز دارد؛ سرور Kira و حساب ابری اجباری نیستند.

## معماری و ماژول‌ها
- `:app`: نقطه ورود، چرخه عمر برنامه و اتصال featureها
- `:core:designsystem`: تم Material 3، توکن‌های رنگ/تایپوگرافی/شکل و کامپوننت‌های مشترک Compose
- SQLite خصوصی برنامه: تاریخچه چت، حافظه بلندمدت، تنظیمات Provider و فهرست مهارت‌ها
- Android Keystore + AES/GCM: رمزنگاری API Keyها در همان دستگاه
- `files/kira/library`: کتابخانه محلی Skillها

## Design System
در UI جدید از `MaterialTheme.colorScheme`، `MaterialTheme.typography` و `MaterialTheme.shapes` استفاده کن. کنترل‌های مشترک در پکیج `ai.kira.mobile.ui.components` قرار دارند. الگوهای ناوبری و تعامل باید با عادت‌های استاندارد اندروید سازگار بمانند.

## ساخت APK
- Android Gradle Plugin 9.5.x، JDK 17، Android SDK API 37، Jetpack Compose BOM 2026.09.00
- دستور ساخت: `./gradlew --no-daemon :app:assembleDebug`
- خروجی: `app/build/outputs/apk/debug/app-debug.apk`
- Workflow شاخه `feature/android-ai-assistant` فایل Debug را با Artifact نام `Kira-Android-debug-APK` می‌سازد. این APK برای انتشار عمومی امضاشده نیست.
