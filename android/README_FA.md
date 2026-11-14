# Kira Android

کلاینت Native اندروید Kira است. این برنامه جداگانه نصب و اجرا می‌شود، اما از مغز، حساب، تنظیمات، Route، تاریخچه و حافظه‌ی مشترک Kira استفاده خواهد کرد؛ درست مثل کلاینت ویندوز.

## ساختار
- app/: رابط Native با Kotlin و Jetpack Compose
- MainActivity.kt: پوسته و ناوبری
- assistant/AiAssistantOverlayService.kt: دسترسی شناور Android
- core/KiraCoreClient.kt: اتصال API مشترک، نشست و ذخیره‌ی امن Token با Android Keystore
- KiraChatScreen.kt: چت و بازیابی تاریخچه از حساب مشترک
- KiraRouteScreen.kt: مشاهده‌ی Routeهای Cloud و ذخیره‌ی رمزنگاری‌شده‌ی کلید Provider
- KiraMemoryScreen.kt: مشاهده و ویرایش حافظه‌ی بلندمدت مشترک
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

قرارداد API در shared/contracts/kira-core-api-v1.yaml تعریف شده است. صفحه‌ی حساب Kira در تنظیمات، ثبت‌نام/ورود ایمیلی، بازیابی نشست ذخیره‌شده و خروج را دارد. صفحه‌های چت، Route و حافظه نیز به API مشترک وصل شده‌اند. کلیدهای Provider از صفحه‌ی Route به‌صورت رمزنگاری‌شده در Core ذخیره می‌شوند. تا زمان استقرار Core Server روی هاست واقعی با HTTPS، ورود و Sync ابری قابل استفاده نیستند. همچنین چت ویندوز هنوز به Core منتقل نشده و از Router محلی استفاده می‌کند.

## AI Assistant

معادل اندرویدی Game Mode ویندوز با نام AI Assistant ساخته می‌شود:
- حباب شناور برای دسترسی سریع
- بررسی محتوای صفحه فقط با رضایت کاربر در هر نشست
- فرمان صوتی و پاسخ گفتاری
- ارسال زمینه‌ی تأییدشده به همان Kira Core و مکالمه‌ی مشترک

هیچ ضبط یا ارسال دائمی و پنهانی از صفحه یا میکروفون در نظر گرفته نشده است.

## وضعیت فعلی

در این مرحله، پوسته‌ی Compose، حباب شناور، ورود حساب، چت، Route، حافظه و Adapterهای Core پیاده‌سازی شده‌اند. Voice، فایل‌ها، Screen Context، استقرار سرور و اتصال جریان اصلی چت ویندوز هنوز کامل نیستند. APK فعلی برای آزمایش UI و مسیرهای متصل به Core آماده می‌شود؛ همگام‌سازی واقعی پس از استقرار سرور فعال خواهد شد.
