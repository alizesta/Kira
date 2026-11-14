# Kira Android

کلاینت Native اندروید Kira است. این برنامه جداگانه نصب و اجرا می‌شود، اما از مغز، حساب، تنظیمات، Route، تاریخچه و حافظه‌ی مشترک Kira استفاده خواهد کرد؛ درست مثل کلاینت ویندوز.

## ساختار
- app/: رابط Native با Kotlin و Jetpack Compose
- MainActivity.kt: پوسته و ناوبری
- assistant/AiAssistantOverlayService.kt: دسترسی شناور Android
- core/KiraCoreClient.kt: اتصال API مشترک، نشست و ذخیره‌ی امن Token با Android Keystore
- ../shared/contracts/: قرارداد هم‌ارزی قابلیت‌ها و API مشترک
- ../docs/ANDROID_PORT_ROADMAP_FA.md: معماری و مراحل توسعه

## ابزار ساخت
- Android Gradle Plugin 9.5.x
- Gradle Wrapper همراه پروژه
- JDK 17
- Android SDK API 37
- Kotlin Built-in از مسیر AGP 9
- Jetpack Compose BOM 2026.09.00

برای ساخت APK دیباگ:
```bash
./gradlew --no-daemon :app:assembleDebug
```

خروجی:
app/build/outputs/apk/debug/app-debug.apk

## هسته و همگام‌سازی

Android قرار نیست موتور گفتگو، Providerها یا حافظه‌ی جداگانه‌ای داشته باشد. پس از آماده‌شدن Kira Core:
- همان حسابی که در ویندوز استفاده می‌شود روی گوشی هم قابل ورود است.
- چت‌ها، شخصیت‌ها، تنظیمات مشترک، Routeهای Cloud و حافظه از همان سرور بازیابی می‌شوند.
- کلیدهای Provider در سرور رمزنگاری می‌شوند و کلاینت برای هر درخواست مستقیم به Provider وصل نمی‌شود.
- مدل محلی گوشی و تنظیمات مخصوص دستگاه مستقل می‌مانند.
- Google Sign-In بعداً به همان حساب داخلی متصل خواهد شد.

قرارداد API در shared/contracts/kira-core-api-v1.yaml تعریف شده است. Adapter ارتباطی و ذخیره‌ی امن نشست هم اضافه شده، اما صفحه ورود و اتصال جریان اصلی چت هنوز به آن وصل نشده‌اند. تا زمان استقرار Core Server، قابلیت Sync ابری فعال نیست.

## AI Assistant

معادل اندرویدی Game Mode ویندوز با نام AI Assistant ساخته می‌شود:
- حباب شناور برای دسترسی سریع
- بررسی محتوای صفحه فقط با رضایت کاربر در هر نشست
- فرمان صوتی و پاسخ گفتاری
- ارسال زمینه‌ی تأییدشده به همان Kira Core و مکالمه‌ی مشترک

هیچ ضبط یا ارسال دائمی و پنهانی از صفحه یا میکروفون در نظر گرفته نشده است.

## وضعیت فعلی

در این مرحله، پوسته‌ی Compose، حباب شناور و Adapter اولیه‌ی Kira Core موجودند. اتصال صفحه‌های چت/Route/حافظه، ورود حساب، Voice و فایل‌ها به سرویس هنوز کامل نشده است. APK این مرحله برای آزمایش پوسته‌ی موبایل است، نه نسخه‌ی نهایی همگام‌شده.
