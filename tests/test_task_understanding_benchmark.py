"""200-case regression benchmark for task-intent routing.

This is an offline detector/routing benchmark, not a live-model accuracy claim.
Each positive case pins at least one required tool family; extra categories are
allowed where a request genuinely spans multiple capabilities.
"""
import unittest

from kira.tools import protocol
from kira.tools.access import PathPolicy
from kira.tools.agent import ToolAgent
from kira.tools.builtin import build_registry


CASES = {
    "time": [
        "ساعت الان چنده؟",
        "تاریخ امروز رو بگو",
        "امروز چندمه؟",
        "امروز چه روزی از هفته است؟",
        "منطقه زمانی سیستم من چیه؟",
        "ساعت جهانی الان چنده؟",
        "What time is it right now?",
        "Tell me today's date.",
        "What day of the week is it?",
        "Check my computer timezone.",
        "Show the current time in my timezone.",
        "Is it 3 o'clock yet?",
        "زمان محلی من رو اعلام کن",
        "تاریخ میلادی امروز رو بخون",
        "روز هفته رو از سیستم دربیار",
        "What's the date on this PC?",
        "Find the current time zone setting.",
        "Tell me the current local time.",
        "الان ساعت سیستم چند است؟",
        "تاریخ و ساعت فعلی ویندوز رو بخون",
    ],
    "system": [
        "مشخصات کامل سیستمم رو گزارش کن",
        "مقدار RAM مصرف‌شده رو بررسی کن",
        "مصرف CPU الان چقدره؟",
        "دمای پردازنده رو بررسی کن",
        "کارت گرافیک نصب‌شده چیه؟",
        "فضای خالی درایو C چقدره؟",
        "وضعیت باتری لپ‌تاپ رو بخون",
        "اتصال Wi-Fi قطع شده یا وصله؟",
        "آدرس IP کامپیوترم رو پیدا کن",
        "عملکرد سیستم چرا کند شده؟",
        "Show my PC hardware specs.",
        "Check current memory usage.",
        "How much CPU is being used?",
        "Report the GPU model.",
        "Check free space on drive D.",
        "What is the current battery level?",
        "Diagnose my Wi-Fi connection status.",
        "Show this computer's IP address.",
        "Check system performance and resource usage.",
        "Is battery saver enabled?",
    ],
    "apps": [
        "برنامه ماشین حساب رو باز کن",
        "دیسکورد رو اجرا کن",
        "استیم رو بالا بیار",
        "کروم رو باز کن",
        "برنامه‌ای که الان در حال اجراست رو پیدا کن",
        "ببین چه برنامه‌هایی باز هستند",
        "نوت‌پد رو اجرا کن",
        "Wallpaper Engine رو باز کن",
        "تنظیمات ویندوز رو باز کن",
        "برنامه تلگرام رو اجرا کن",
        "Open Calculator.",
        "Launch Discord.",
        "Start Steam.",
        "Open Chrome browser.",
        "Show which applications are running.",
        "Launch Notepad.",
        "Open Wallpaper Engine.",
        "Open Windows Settings.",
        "Start the Excel application.",
        "Find the installer application and launch it.",
    ],
    "bluetooth": [
        "بلوتوث رو روشن کن",
        "وضعیت بلوتوث رو بررسی کن",
        "دستگاه‌های بلوتوث اطراف رو پیدا کن",
        "هدفون بلوتوثم وصله؟",
        "دستگاه‌های جفت‌شده رو فهرست کن",
        "اتصال بلوتوث رو قطع کن",
        "بلوتوث لپ‌تاپ رو خاموش کن",
        "اسم دستگاه‌های Bluetooth متصل رو بگو",
        "هدفونم رو از طریق بلوتوث وصل کن",
        "دستگاه جدید رو Pair کن",
        "Turn Bluetooth on.",
        "Check whether Bluetooth is enabled.",
        "Scan for nearby Bluetooth devices.",
        "Is my Bluetooth headset connected?",
        "List paired Bluetooth devices.",
        "Disconnect the Bluetooth speaker.",
        "Turn Bluetooth off on this laptop.",
        "Show connected Bluetooth device names.",
        "Pair the new keyboard over Bluetooth.",
        "Reconnect my Bluetooth headphones.",
    ],
    "audio": [
        "صدا رو کم کن",
        "ولوم رو روی ۳۰ درصد بذار",
        "میکروفون پیش‌فرض رو عوض کن",
        "صدای خروجی رو روی هدفون بذار",
        "اسپیکر رو بی‌صدا کن",
        "میکروفون رو فعال کن",
        "وضعیت صدای سیستم رو بررسی کن",
        "هدفون رو به عنوان خروجی صدا انتخاب کن",
        "صدای برنامه رو زیاد کن",
        "میکروفن فعلی کدومه؟",
        "Lower the system volume.",
        "Set volume to 30 percent.",
        "Change the default microphone.",
        "Switch audio output to headphones.",
        "Mute the speakers.",
        "Unmute the microphone.",
        "Check the current audio device.",
        "Select the headset as the output device.",
        "Increase the application volume.",
        "Which microphone is currently selected?",
    ],
    "files": [
        "فایل‌های دسکتاپ رو فهرست کن",
        "پوشه دانلودها رو باز کن",
        "فایل‌های PDF رو پیدا کن",
        "فایل‌های بزرگ رو مرتب کن",
        "از پوشه تصاویر بکاپ بگیر",
        "فایل‌های تکراری رو پیدا کن",
        "فایل config رو بخون",
        "فایل‌های قدیمی رو به Archive منتقل کن",
        "اسم فایل گزارش رو تغییر بده",
        "یک نسخه از سند رو کپی کن",
        "List the files on my Desktop.",
        "Open the Downloads folder.",
        "Find all PDF files.",
        "Sort the largest files by size.",
        "Back up the Pictures folder.",
        "Find duplicate files.",
        "Read the configuration file.",
        "Move old documents into the Archive folder.",
        "Rename the report file.",
        "Copy the spreadsheet to Documents.",
    ],
    "desktop": [
        "داخل پنجره فعال عبارت تست رو تایپ کن",
        "روی دکمه ذخیره کلیک کن",
        "پنجره فعلی رو کوچک کن",
        "پنجره برنامه رو ببند",
        "با میانبر صفحه‌کلید پنجره رو عوض کن",
        "محتوای کلیپ‌بورد رو جای‌گذاری کن",
        "منوی فایل رو باز کن",
        "چک‌باکس تنظیمات رو فعال کن",
        "در Notepad متن سلام رو بنویس",
        "پنجره رو به سمت راست منتقل کن",
        "Type the word test into the active window.",
        "Click the Save button.",
        "Minimize the current window.",
        "Close the application window.",
        "Use the keyboard shortcut to switch windows.",
        "Paste the clipboard contents.",
        "Open the File menu.",
        "Select the settings checkbox.",
        "Write a note in Notepad.",
        "Navigate to the Bluetooth page in Settings.",
    ],
    "web": [
        "قیمت یورو رو پیدا کن",
        "نرخ دلار امروز چنده؟",
        "آخرین نسخه پایتون رو از اینترنت پیدا کن",
        "سه منبع معتبر درباره موضوع بررسی کن",
        "این مقاله رو از روی لینک بخون و خلاصه کن",
        "قیمت پنج لپ‌تاپ رو از اینترنت مقایسه کن",
        "سایت رسمی سازنده رو از اینترنت پیدا کن",
        "ادعاهای این صفحه رو از اینترنت راستی‌آزمایی کن",
        "یک والپیپر 4K پورشه از اینترنت پیدا کن",
        "لینک دانلود رسمی برنامه رو از اینترنت پیدا کن",
        "Search the web for the latest Python release.",
        "Compare prices from three online retailers.",
        "Read the article at the link I provide.",
        "Verify the claims against official sources.",
        "Find the official download page.",
        "Look up today's EUR to USD rate.",
        "Research this topic using multiple sources.",
        "Find a 4K Porsche wallpaper online.",
        "Compare current laptop prices online.",
        "Find the manufacturer's official website.",
    ],
    "mcp": [
        "فهرست ابزارهای MCP رو نشون بده",
        "وضعیت اتصال MCP رو بررسی کن",
        "از سرور MCP برای این کار استفاده کن",
        "MCP server list رو بخون",
        "کدوم MCP فعال است؟",
        "تنظیمات MCP رو بررسی کن",
        "MCP رو برای این درخواست اجرا کن",
        "اتصال ام سی پی رو تست کن",
        "ابزارهای mcp موجود رو گزارش کن",
        "سرور MCP مورد استفاده رو مشخص کن",
        "Show the available MCP tools.",
        "Check the MCP server connection.",
        "Use the MCP server for this request.",
        "List configured MCP servers.",
        "Which MCP tools are enabled?",
        "Inspect the MCP configuration.",
        "Run this through MCP.",
        "Test the MCP connection.",
        "Report the active MCP endpoints.",
        "Show the MCP integration status.",
    ],
    "agents": [
        "این کار رو به یک ایجنت مستقل بسپار",
        "وضعیت کار ایجنت رو بررسی کن",
        "یک عامل خارجی برای این تسک اجرا کن",
        "شناسه job رو از ایجنت بگیر",
        "کار رو به agents واگذار کن",
        "وضعیت agent رو گزارش کن",
        "یک ایجنت جداگانه برای بررسی بساز",
        "نتیجه کار عامل مستقل رو بگیر",
        "کار رو به ایجنت دیگه بسپار",
        "وضعیت اجرای job رو از agent بپرس",
        "Delegate this task to an agent.",
        "Check the agent job status.",
        "Start an independent agent for this task.",
        "Ask the external agent to investigate.",
        "Get the job ID from the agent.",
        "Show the agents currently running.",
        "Assign this work to another agent.",
        "Retrieve the agent's result.",
        "Check the status of the delegated job.",
        "Run this task with an independent agent.",
    ],
}

CHAT_ONLY = [
    "سلام، امروز حالت چطوره؟",
    "به نظرت چه فیلمی ارزش دیدن داره؟",
    "فرق استعاره و تشبیه چیه؟",
    "یک داستان کوتاه درباره باران تعریف کن",
    "برای یادگیری بهتر چه روشی پیشنهاد می‌کنی؟",
    "امروز خیلی خسته‌ام و حوصله ندارم",
    "چرا آسمون آبی به نظر می‌رسه؟",
    "یک متن دوستانه برای تولد بنویس",
    "این جمله از نظر دستوری درسته؟",
    "بهترین راه تمرین مکالمه انگلیسی چیه؟",
    "What makes a good science-fiction story?",
    "Explain the difference between a metaphor and a simile.",
    "Tell me a joke about programmers.",
    "Write a short poem about autumn.",
    "I feel nervous about my presentation.",
    "Why do leaves change color?",
    "Summarize the concept of opportunity cost.",
    "Help me brainstorm names for a fictional city.",
    "What are some ways to stay motivated?",
    "Explain how source code is compiled.",
]


def _make_agent():
    agent = ToolAgent.__new__(ToolAgent)
    agent.settings = {"tools_mode": "auto", "agent_planning": "off"}
    agent.registry = build_registry(PathPolicy({}))
    agent._competitive_safe_mode = False
    agent._pending_by_session = {}
    agent._pending_new_sessions = set()
    agent._init_session_turn_states()
    return agent


class TaskUnderstandingBenchmarkTests(unittest.TestCase):
    def test_benchmark_contains_200_actionable_cases_and_20_chat_controls(self):
        self.assertEqual(sum(len(items) for items in CASES.values()), 200)
        self.assertEqual(len(CHAT_ONLY), 20)
        self.assertEqual(len({p for items in CASES.values() for p in items}), 200)

    def test_all_actionable_cases_reach_the_expected_tool_family(self):
        agent = _make_agent()
        for category, prompts in CASES.items():
            for index, prompt in enumerate(prompts):
                with self.subTest(category=category, index=index, prompt=prompt):
                    detected = protocol.detect_categories(prompt)
                    self.assertIn(category, detected)
                    plan = agent.plan(prompt, session_id=f"bench-{category}-{index}")
                    self.assertIsNotNone(plan)
                    self.assertFalse(plan.index_only)

    def test_chat_controls_remain_on_the_cheap_triage_path(self):
        agent = _make_agent()
        for index, prompt in enumerate(CHAT_ONLY):
            with self.subTest(index=index, prompt=prompt):
                self.assertEqual(protocol.detect_categories(prompt), set())
                plan = agent.plan(prompt, session_id=f"chat-{index}")
                self.assertIsNotNone(plan)
                self.assertTrue(plan.index_only)


if __name__ == "__main__":
    unittest.main()
