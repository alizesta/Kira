# Kira | AI Desktop Companion

**An anime-inspired AI desktop companion for Windows, combining cloud and local AI models, conversational memory, voice interaction, web access, and controlled Windows automation.**

Kira is an experimental desktop assistant designed to make interaction with a computer more natural and personal. Its goal is to bring together an AI companion experience, persistent memory, voice capabilities, online information access, and a modular system of tools for supported Windows operations.

> **Project status:** Active development. Kira is experimental, and capabilities may change between versions. Some integrations and Windows-control features are still being developed or require validation on a real Windows system.

## Core features

- **Hybrid AI:** Connect cloud AI providers and local models through Ollama.
- **Model routing:** Configure providers and models, set priorities, and use fallback routes where supported.
- **Conversational memory:** Maintain conversation context and persistent user preferences.
- **Companion personality:** A customizable personality system with mood and relationship context.
- **Voice interaction:** Speech recognition, text-to-speech, microphone settings, and supported cloud voice services.
- **Web access:** Retrieve information from online sources and use it in responses.
- **Computer awareness:** Inspect selected Windows and system information, running applications, and supported files.
- **Controlled Windows tools:** A modular tool architecture for supported desktop operations, with access checks and confirmation for sensitive actions.
- **Attachments:** Support for selected image and document inputs, depending on the active model and file format.

## Design principles

- Provider-independent architecture
- Modular tools and clear separation of responsibilities
- User control and confirmation for sensitive operations
- Honest reporting of tool results and errors
- Local-first handling where practical, with awareness of what may be sent to cloud providers

## Technology

- **Platform:** Windows 11
- **Language:** Python
- **Desktop framework:** PySide6
- **AI runtimes:** Cloud APIs and Ollama
- **Local models:** Supported through Ollama

## Project vision

Kira is being developed toward a capable desktop companion that can understand natural-language requests, maintain a consistent personality, and safely assist with everyday computer tasks. The long-term focus is useful intelligence and reliable interaction, not simply adding more buttons or superficial features.

---

# کیرا | دستیار هوشمند دسکتاپ

**یک همراه دیجیتال با الهام از شخصیت‌های انیمه برای ویندوز؛ با پشتیبانی از مدل‌های هوش مصنوعی ابری و محلی، حافظه‌ی گفتگو، تعامل صوتی، دسترسی به وب و ابزارهای کنترل‌شده‌ی ویندوز.**

Kira یک دستیار دسکتاپ آزمایشی و در حال توسعه است که هدفش طبیعی‌تر و شخصی‌تر کردن تعامل با کامپیوتر است. این پروژه می‌خواهد تجربه‌ی یک همراه هوشمند را با حافظه‌ی پایدار، قابلیت‌های صوتی، دسترسی به اطلاعات آنلاین و مجموعه‌ای ماژولار از ابزارهای قابل‌کنترل ویندوز ترکیب کند.

> **وضعیت پروژه:** توسعه‌ی فعال. کیرا هنوز در مرحله‌ی آزمایشی است و قابلیت‌های آن ممکن است در نسخه‌های مختلف تغییر کنند. بعضی از اتصال‌ها و قابلیت‌های کنترل ویندوز همچنان در حال توسعه‌اند یا به بررسی روی یک سیستم واقعی ویندوز نیاز دارند.

## قابلیت‌های اصلی

- **هوش مصنوعی ترکیبی:** اتصال به سرویس‌های هوش مصنوعی ابری و مدل‌های محلی از طریق Ollama.
- **مسیریابی مدل‌ها:** تنظیم Providerها و مدل‌های مختلف، تعیین اولویت و استفاده از مسیر جایگزین در صورت پشتیبانی.
- **حافظه‌ی گفتگو:** حفظ زمینه‌ی مکالمه و ترجیحات پایدار کاربر.
- **شخصیت همراه:** سیستم شخصیت قابل‌تنظیم همراه با زمینه‌ی خلق‌وخو و رابطه‌ی گفتگو.
- **تعامل صوتی:** تشخیص گفتار، تبدیل متن به گفتار، تنظیمات میکروفون و سرویس‌های صوتی ابری پشتیبانی‌شده.
- **دسترسی به وب:** دریافت اطلاعات از منابع آنلاین و استفاده از آن‌ها در پاسخ‌ها.
- **شناخت کامپیوتر:** بررسی اطلاعات منتخب ویندوز و سیستم، برنامه‌های در حال اجرا و فایل‌های پشتیبانی‌شده.
- **ابزارهای کنترل‌شده‌ی ویندوز:** معماری ماژولار برای اجرای عملیات پشتیبانی‌شده‌ی دسکتاپ، همراه با بررسی دسترسی و تأیید عملیات حساس.
- **پیوست‌ها:** پشتیبانی از برخی تصاویر و اسناد، بسته به مدل فعال و قالب فایل.

## اصول طراحی

- معماری مستقل از Provider خاص
- ابزارهای ماژولار و تفکیک روشن مسئولیت‌ها
- حفظ کنترل کاربر و دریافت تأیید برای عملیات حساس
- گزارش صادقانه‌ی نتیجه‌ی ابزارها و خطاها
- اولویت‌دادن به پردازش محلی در موارد ممکن، همراه با توجه به اطلاعاتی که ممکن است برای سرویس‌های ابری ارسال شوند

## فناوری‌ها

- **سیستم‌عامل:** Windows 11
- **زبان برنامه‌نویسی:** Python
- **چارچوب دسکتاپ:** PySide6
- **اجرای هوش مصنوعی:** APIهای ابری و Ollama
- **مدل‌های محلی:** از طریق Ollama

## چشم‌انداز پروژه

هدف بلندمدت Kira تبدیل‌شدن به یک همراه هوشمند دسکتاپ است که درخواست‌های زبان طبیعی را درک کند، شخصیت باثباتی داشته باشد و بتواند با رعایت امنیت و کنترل کاربر، در کارهای روزمره‌ی کامپیوتر کمک کند.

تمرکز اصلی توسعه بر هوشمندی کاربردی و تعامل قابل‌اعتماد است، نه صرفاً اضافه‌کردن دکمه‌ها و قابلیت‌های ظاهری.
