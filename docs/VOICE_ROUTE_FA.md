# مسیرهای مکالمه صوتی و ارتباط آن‌ها با Route

Ai1 دو مسیر صوتی دارد که باید از مسیر مدل چت تفکیک شوند. مقدار پیش‌فرض voice_engine در kira/config.py برابر gemini_live است.

## ۱) Gemini Live — مسیر پیش‌فرض

- GeminiLiveWorker یک نشست صوتی دوطرفه با Google Gemini Live ایجاد می‌کند.
- صدای میکروفن به‌صورت PCM تک‌کاناله 16kHz از طریق WebSocket ارسال می‌شود؛ صدای خروجی PCM تک‌کاناله 24kHz دریافت و پخش می‌شود.
- در این مسیر، Listener/شنوا و Piper برای مکالمه اجرا نمی‌شوند؛ تشخیص و تولید گفتار در نشست Live انجام می‌شود.
- Provider گوگل و API Key از بخش Connections خوانده می‌شوند. Voice کلید جداگانه‌ای ذخیره نمی‌کند.
- مدل و صدای پیش‌ساخته Gemini از تنظیمات Voice قابل انتخاب‌اند؛ مدل پیش‌فرض در تنظیمات gemini-3.8-live و صدا Zephyr است.
- در صورت فعال‌بودن transcription نشست، متن ورودی و پاسخ به تاریخچه گفتگو افزوده می‌شود.

**حریم خصوصی:** در این حالت صدای میکروفن به سرویس Google ارسال می‌شود. استفاده از Gemini Live را نباید «پردازش کاملاً محلی» توصیف کرد.

## ۲) حالت محلی — انتخاب دستی یا fallback

زنجیره محلی real-time فعلی:

    Microphone → Shenava (sherpa-onnx) → Chat Route → Piper / KittenTTS

- STT با مدل فارسی Shenava روی CPU و به‌صورت محلی انجام می‌شود.
- پاسخ متنی از Route چت انتخاب‌شده دریافت می‌شود. اگر Route ابری باشد، متن تشخیص‌داده‌شده به همان Provider ارسال می‌شود؛ صدای خام میکروفن به آن Provider ارسال نمی‌شود.
- TTS فارسی با Piper انجام می‌شود. KittenTTS 2 فقط برای جمله‌های انگلیسی قابل استفاده است.
- realtime_asr_enabled باید روشن باشد تا Listener محلی زنده شروع شود. تست فایل WAV مستقل از این گزینه است.

## ۳) انتقال خودکار از Gemini به مسیر محلی

- voice_local_fallback به‌طور پیش‌فرض روشن است.
- اگر اتصال، نشست یا worker مربوط به Gemini Live شکست بخورد، ابتدا worker و streamهای Live متوقف/آزاد می‌شوند؛ سپس Listener محلی، در صورت فعال‌بودن fallback و Real-time ASR، شروع می‌شود.
- اگر fallback خاموش باشد یا Real-time ASR محلی غیرفعال باشد، مکالمه متوقف می‌شود و خطا به کاربر گزارش می‌شود؛ مسیر جایگزین پنهانی انتخاب نمی‌شود.

## ۴) تنظیمات و تفکیک مسئولیت‌ها

| تنظیم | مسئولیت |
|---|---|
| voice_engine | انتخاب gemini_live یا local |
| gemini_live_provider | شناسه Provider گوگل از Connections |
| gemini_live_model | مدل نشست Gemini Live |
| gemini_voice | صدای ازپیش‌آماده Gemini |
| voice_local_fallback | اجازه انتقال از Live به مسیر محلی |
| realtime_asr_enabled | فعال‌بودن Listener محلی real-time |
| local_voice_asr_model | مدل Shenava انتخاب‌شده |
| tts_engine | piper یا kitten؛ Kitten فقط انگلیسی |
| voice_volume, mic_gain, mic_device, output_device | سطح صدا و انتخاب دستگاه‌ها |

Route Manager همچنان مدل پاسخ متنی را انتخاب می‌کند؛ انتخاب Route چت به‌خودی‌خود موتور صوتی را تغییر نمی‌دهد. جزئیات موتورهای محلی: docs/LOCAL_VOICE_FA.md. جزئیات نشست زنده: docs/GEMINI_LIVE_FA.md.
