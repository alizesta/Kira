# Kira Android

کلاینت Native اندروید Kira مستقل از نسخه ویندوز اجرا می‌شود. هسته موبایل روی دستگاه است و برای مدل‌های ابری فقط به API Key مستقیم Provider نیاز دارد؛ سرور Kira و حساب ابری اجباری نیستند.

## معماری و ماژول‌ها
- `:app`: نقطه ورود و نمایش UI
- `MainActivity`: فقط چرخه‌عمر Activity، Intentهای ورودی و راه‌اندازی Compose؛ ساخت سرویس‌ها در آن انجام نمی‌شود
- `KiraMobileApplication`: مالک Composition Root در سطح Process
- `KiraContainer`: ساخت و تزریق سرویس‌های Application و آداپتورهای Data
- `domain/`: مدل‌ها، قرارداد Repositoryها و سیاست خالص انتخاب Route و مدل
- `application/`: Use Caseهای Provider و Internet Search، بدون وابستگی به Android یا Compose
- `data/`: آداپتورهای SQLite، Android Keystore و ارتباط HTTP
- `:core:designsystem`: تم Material 3، توکن‌ها و کامپوننت‌های مشترک Compose

## Provider و مسیریابی مدل
- افزودن Provider با تشخیص کلید و دریافت فهرست مدل‌ها
- انتخاب هوشمند و دستی مدل از میان مدل‌های رایگان تأییدشده
- فعال/غیرفعال‌کردن Routeها و تعیین ترتیب Failover
- کلیدهای Provider در مخزن محلی رمزنگاری‌شده نگهداری می‌شوند
- مدل OpenRouter فقط پس از بررسی قیمت صفر ورودی و خروجی وارد فهرست رایگان می‌شود

## Internet Search
- جستجو با Tavily و دریافت محتوای خام Markdown منابع
- محدودیت اندازه پاسخ، Timeout و پالایش URLهای منابع به HTTPS
- نمایش خلاصه اولیه، محتوا، لینک منبع و ارجاع شماره‌دار
- انتقال شواهد به Chat با نشانه‌گذاری داده خارجیِ غیرقابل اعتماد و ارجاع‌های `[1]` و `[2]`
- کلید Tavily با AES/GCM و Android Keystore رمزنگاری می‌شود

## داده‌های محلی
- SQLite خصوصی برنامه: تاریخچه چت، حافظه بلندمدت، تنظیمات Provider و مهارت‌ها
- Android Keystore + AES/GCM: رمزنگاری کلیدها در همان دستگاه
- `files/kira/library`: کتابخانه محلی Skillها

## ساخت APK
- Android Gradle Plugin 9.5.x، JDK 17، Android SDK API 37، Jetpack Compose BOM 2026.09.00
- دستور ساخت: `./gradlew --no-daemon :app:assembleDebug`
- خروجی: `app/build/outputs/apk/debug/app-debug.apk`
- APK Debug برای انتشار عمومی امضاشده نیست.
