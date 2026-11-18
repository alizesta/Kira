"""Application policy for one-shot Web and image search from Chat.

Search engines and transport remain in :mod:`kira.websearch`; this service owns
provider credential selection, follow-up query rewriting, search request options,
and normalization of search evidence for the Chat application boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .. import websearch


@dataclass(frozen=True)
class WebSearchOptions:
    query: str
    api_key: str
    depth: str
    fallback: bool
    gemini: tuple[str, str] | None
    user_text: str
    rewrite: Callable[[], str] | None = None
    images: tuple[Mapping[str, Any], ...] = ()
    describe: Callable[[], Any] | None = None

    @property
    def available(self) -> bool:
        return bool(self.api_key or self.fallback)


class WebSearchApplicationService:
    """Own provider selection and query policy; contains no Qt dependencies."""

    IMAGE_QUERY_ASK = "این تصویر چیست؟ فقط عبارت جست‌وجو را بنویس."
    SEARCH_QUERY_PROMPT = (
        "You write ONE web search query for a search engine. Use the conversation to resolve references such as "
        "'this song', 'him', 'search better'. Keep titles and names exactly as the user wrote them (Persian stays "
        "Persian). No quotes, no explanation, at most 12 words. Output only the query."
    )
    WEB_TEST_QUERY = "آهنگ تو که معنای عشقی"
    MISSING_KEY_MESSAGE = (
        "🌐 برای جست‌وجوی وب کلید Tavily لازم است (تب عمومی ← «کلید جست‌وجوی وب»؛ "
        "رایگان از tavily.com). بدون وب ادامه می‌دهم."
    )

    @staticmethod
    def can_search(settings: Mapping[str, Any]) -> bool:
        return bool(str(settings.get("tavily_api_key", "")).strip() or settings.get("web_fallback", True))

    @staticmethod
    def gemini_credentials(settings: Mapping[str, Any]) -> tuple[str, str] | None:
        """Resolve an already-configured Gemini provider for grounded search."""
        for provider_id, config in (settings.get("providers") or {}).items():
            if (
                "generativelanguage" in str(config.get("base_url") or "")
                and str(config.get("api_key") or "").strip()
            ):
                model = next(
                    (
                        route["model"]
                        for route in settings.get("routes", [])
                        if route.get("provider") == provider_id and route.get("model")
                    ),
                    "",
                )
                return (
                    str(config["api_key"]).strip(),
                    str(model).removeprefix("models/") or "gemini-flash-latest",
                )
        return None

    @classmethod
    def make_image_query(cls, images: Sequence[Mapping[str, Any]], hint: str, client: Any) -> Any:
        """Ask the active vision-capable chat client for a short search phrase."""
        message = {
            "role": "user",
            "content": hint or cls.IMAGE_QUERY_ASK,
            "images": list(images or []),
        }
        return client.chat([message], websearch.IMAGE_QUERY_PROMPT, 0.1)

    @classmethod
    def make_search_query(cls, history: Sequence[Mapping[str, Any]], fallback: str, client: Any) -> str:
        """Resolve a short follow-up against recent context; retain literal user text on weak output."""
        output = client.chat(list(history or [])[-6:], cls.SEARCH_QUERY_PROMPT, 0.1)
        line = next((item.strip() for item in str(output or "").splitlines() if item.strip()), "")
        line = line.removeprefix("Query:").removeprefix("query:").strip()
        line = line.strip(chr(34) + chr(39) + "«»`").strip()
        return line if 2 <= len(line) <= 160 else fallback

    def plan_request(
        self,
        text: str,
        settings: Mapping[str, Any],
        tool_plan: Any | None = None,
        *,
        force_web: bool = False,
    ) -> tuple[str | None, bool]:
        """Choose whether a Chat turn should use one-shot Web Search.

        Keep command parsing and automatic-search suppression out of the UI
        mixin. A strong local/tool plan or a dedicated web-tool plan takes
        precedence over automatic search; an explicit /web request always
        wins and preserves the user's literal query.
        """
        user_text = str(text or "")
        enabled = bool(
            settings.get("web_search", True)
            or user_text.lstrip().startswith("/")
            or force_web
        )
        if not enabled:
            return None, False
        if force_web:
            return user_text.strip()[:300], True

        query, forced = websearch.plan(user_text)

        if query and not forced and tool_plan is not None:
            if getattr(tool_plan, "strong", False) or getattr(tool_plan, "web", False):
                return None, False
        return query, forced

    def web_search_options(
        self,
        settings: Mapping[str, Any],
        query: str,
        history: Sequence[Mapping[str, Any]],
        client: Any,
    ) -> WebSearchOptions:
        key = str(settings.get("tavily_api_key", "")).strip()
        fallback = bool(settings.get("web_fallback", True))
        gemini = self.gemini_credentials(settings)
        rewrite = None
        if websearch.is_followup(query):
            recent = list(history or [])[-6:]
            rewrite = lambda c=client, h=recent, q=query: self.make_search_query(h, q, c)
        return WebSearchOptions(
            query=query,
            api_key=key,
            depth=str(settings.get("web_depth", "basic")),
            fallback=fallback,
            gemini=gemini,
            user_text=query,
            rewrite=rewrite,
        )

    def image_search_options(
        self,
        settings: Mapping[str, Any],
        hint: str,
        images: Sequence[Mapping[str, Any]],
        client: Any,
    ) -> WebSearchOptions:
        key = str(settings.get("tavily_api_key", "")).strip()
        fallback = bool(settings.get("web_fallback", True))
        gemini = self.gemini_credentials(settings)
        image_list = tuple(images or ())
        describe = lambda c=client, items=image_list, text=hint: self.make_image_query(items, text, c)
        return WebSearchOptions(
            query=hint or "تصویر",
            api_key=key,
            depth=str(settings.get("web_depth", "basic")),
            fallback=fallback,
            gemini=gemini,
            user_text=hint,
            images=image_list,
            describe=describe,
        )

    @staticmethod
    def merge_search_content(base_content, images, addition, *, image_search: bool = False):
        """Attach search evidence without dropping prepared files, text or image payloads."""
        if isinstance(base_content, dict) and "files" in base_content and "text" in base_content:
            updated = dict(base_content)
            current_text = str(updated.get("text") or "").strip()
            if not current_text:
                if images and image_search:
                    current_text = "این تصویر چیست؟ با کمک نتایج جست‌وجوی وب بگو."
                elif images:
                    current_text = "این تصویر را ببین و نظرت را بگو."
                elif updated.get("files"):
                    current_text = "این فایل را بخوان و درباره‌اش نظر بده."
            updated["text"] = (current_text + "\n\n" if current_text else "") + str(addition or "")
            updated["images"] = list(images or [])
            updated["search"] = bool(image_search)
            return updated
        return {
            "model": str(base_content or "") + "\n\n" + str(addition or ""),
            "images": list(images or []),
        }

    @staticmethod
    def assessment_text(assessment: Mapping[str, Any] | None) -> str:
        if not assessment or not assessment.get("phrase"):
            return ""
        if assessment.get("matched"):
            sources = "، ".join(str(number) for number in assessment["matched"])
            return f"عبارت جست‌وجو در منبع {sources} عیناً دیده شد."
        return (
            f"⚠ عبارت جست‌وجو در هیچ‌کدام از {assessment.get('checked', 0)} "
            "منبع خوانده‌شده عیناً پیدا نشد."
        )
