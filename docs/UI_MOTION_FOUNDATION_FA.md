# زیرساخت موشن رابط کاربری Kira

## محدوده

MotionManager زیرساخت عمومی انیمیشن Qt است. به تم، رنگ، Glow، طراحی پنل‌ها، آواتار، چت یا Voice وابستگی ندارد و ظاهر رابط را تغییر نمی‌دهد.

## مالکیت و چرخهٔ عمر

- برای هر پنجره یک MotionManager ساخته می‌شود و parent آن همان پنجره است.
- انیمیشن‌ها با QPropertyAnimation و گروه‌های بومی Qt اجرا می‌شوند؛ حلقهٔ تایمر یا محاسبات per-frame در Python اضافه نشده است.
- انیمیشن‌های دارای کلید، با شروع انیمیشن جدید روی همان کلید، قبلی را متوقف می‌کنند.
- انیمیشن‌ها پس از پایان یا توقف از Registry حذف و با deleteLater آزاد می‌شوند.
- تمام فراخوانی‌ها باید از همان Qt thread انجام شوند که Manager در آن ساخته شده است.
- در مسیر خروج پذیرفته‌شدهٔ برنامه، shutdown تمام انیمیشن‌ها را متوقف می‌کند؛ تلاش ناموفق برای خروج Manager را خاموش نمی‌کند.

## API

- animate: انیمیشن یک خاصیت قابل‌نوشتن QObject.
- animate_group: اجرای چند Property Track به‌صورت موازی یا ترتیبی.
- stop و stop_all: لغو انیمیشن‌ها؛ با finish=True مقدار نهایی اعمال می‌شود.
- pause، resume، pause_all و resume_all: کنترل موقت انیمیشن‌ها.
- active_count و active_keys: وضعیت Registry.

## نمونه

    from kira.ui.motion_manager import MotionManager, MotionTrack

    motion = MotionManager(main_window)
    motion.animate(
        panel,
        "maximumHeight",
        260,
        start_value=0,
        duration_ms=240,
        key="settings.panel",
    )
    motion.animate_group(
        (
            MotionTrack(panel, "minimumWidth", 360, start_value=320),
            MotionTrack(panel, "maximumWidth", 360, start_value=480),
        ),
        parallel=True,
        key="settings.panel.enter",
    )

خاصیتی که انیمیت می‌شود باید در meta-object تعریف شده و قابل‌نوشتن باشد یا به‌عنوان dynamic property روی QObject وجود داشته باشد.

## خارج از محدودهٔ این تسک

اتصال موشن به تب‌ها، پنل‌ها، رفتارهای شخصیت، پالت رنگ، Glass/Neon و افکت‌های بصری در تسک‌های بعدی انجام می‌شود؛ تم فعلی عمداً بدون تغییر می‌ماند.
