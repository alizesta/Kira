# موتورهای صوتی محلی

Kira از دو موتور مستقل و صرفاً صوتی استفاده می‌کند؛ هیچ‌کدام مدل چت نیستند:

- STT: Qwen3-ASR 0.6B، اجرای CPU و پشتیبانی از فارسی.
- TTS: Mana Persian Piper از بستهٔ `persian-speech`، خروجی WAV فارسی و اجرای CPU.

## نصب اختیاری
در محیط مجازی Kira اجرا کنید:

```powershell
pip install -r requirements-voice-local.txt
```

وزن‌های Qwen و مدل صدای Piper در اولین استفاده دریافت/آماده می‌شوند. بعد از آماده‌شدن مدل‌ها، تبدیل صدا به متن و متن به صدا محلی است و صدایی به Cloud Voice ارسال نمی‌شود.

## اولویت و fallback مستقل
- STT: Qwen3-ASR محلی ← Cloud Voice ← موتورهای قدیمی Whisper/Google (در صورت نصب).
- TTS: Persian Piper محلی ← Cloud Voice ← Edge TTS ← صدای Windows SAPI.

شکست STT فقط مسیر STT را به مرحلهٔ بعد می‌برد؛ شکست TTS نیز فقط روی TTS اثر دارد. Voice Engine فعلی، ضبط میکروفون، VAD، پخش، توقف، lip-sync و Cloud Voice حفظ می‌شوند.

این بسته‌ها اختیاری‌اند تا نصب اصلی Kira به وابستگی‌های سنگین PyTorch/Transformers گره نخورد. برای نصب روی ویندوز، محیط Python 3.12 توصیه می‌شود؛ سازگاری نسخه‌های دیگر باید جداگانه بررسی شود.
