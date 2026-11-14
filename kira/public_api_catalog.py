"""Discovery and explicit registration of APIs listed by public-apis/public-apis.

The upstream repository is a catalogue, not a gateway. Registered entries remain
reference-only until Kira has an explicit, reviewed connector for that API. This
module never calls third-party APIs and never stores API keys.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests


README_URL = "https://raw.githubusercontent.com/public-apis/public-apis/master/README.md"
SOURCE_URL = "https://github.com/public-apis/public-apis"
CACHE_TTL_SECONDS = 12 * 60 * 60
MAX_README_BYTES = 2 * 1024 * 1024
_USER_AGENT = "Kira-Public-API-Catalog/1.0"


class ApiCatalogError(RuntimeError):
    """A safe, user-displayable catalogue error."""


def _clean_cell(value: str) -> str:
    value = str(value or "").replace("\\|", "|")
    value = re.sub(r"<[^>]+>", "", value)
    return value.strip().strip(chr(96)).strip()


def _parse_row(line: str, category: str) -> dict | None:
    cells = [x.strip() for x in line.strip().strip("|").split("|")]
    if len(cells) < 5:
        return None
    first = re.search(r"\[([^\]]+)\]\((https?://[^)]+)\)", cells[0])
    if not first:
        return None
    name, url = _clean_cell(first.group(1)), first.group(2).strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    stable = hashlib.sha256((name.casefold() + "|" + url.casefold()).encode("utf-8")).hexdigest()[:20]
    return {
        "id": stable,
        "name": name[:120],
        "category": category[:80],
        "description": _clean_cell(cells[1])[:500],
        "auth": (_clean_cell(cells[2]) or "Unknown")[:80],
        "https": (_clean_cell(cells[3]) or "Unknown")[:20],
        "cors": (_clean_cell(cells[4]) or "Unknown")[:20],
        "url": url[:1000],
        "source": SOURCE_URL,
        "integration_status": "catalog_only",
    }


def parse_public_apis_readme(markdown: str) -> list[dict]:
    """Parse category tables beneath README Index; skip promotional and MCP tables."""
    in_index = False
    category = ""
    in_table = False
    out: list[dict] = []
    seen: set[str] = set()
    for line in str(markdown or "").splitlines():
        heading = re.match(r"^(#{2,3})\s+(.+?)\s*$", line)
        if heading:
            level, title = len(heading.group(1)), heading.group(2).strip()
            if level == 2:
                in_index = title.casefold() == "index"
                category = ""
                in_table = False
                continue
            if in_index and level == 3:
                category = title
                in_table = False
                continue
        if not in_index or not category:
            continue
        if "|" not in line:
            if in_table and line.strip():
                in_table = False
            continue
        cells = [x.strip().casefold() for x in line.strip().strip("|").split("|")]
        if cells and cells[0] in ("api", "name") and "description" in cells:
            in_table = True
            continue
        if not in_table or line.lstrip().startswith("|:") or set(line.strip()) <= {"|", "-", ":", " "}:
            continue
        item = _parse_row(line, category)
        if item and item["id"] not in seen:
            seen.add(item["id"])
            out.append(item)
    return out


class PublicApiCatalog:
    def __init__(self, data_dir: str | Path):
        self.cache_path = Path(data_dir) / "public_api_catalog_cache.json"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict | None = None

    def _read_cache(self) -> dict:
        if self._cache is not None:
            return self._cache
        try:
            value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("items"), list):
                self._cache = value
                return value
        except (OSError, ValueError, TypeError):
            pass
        self._cache = {"fetched_at": 0, "etag": "", "items": []}
        return self._cache

    def refresh(self, force: bool = False) -> int:
        cached = self._read_cache()
        fetched_at = float(cached.get("fetched_at") or 0)
        if not force and cached["items"] and time.time() - fetched_at < CACHE_TTL_SECONDS:
            return len(cached["items"])
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/plain"}
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        try:
            response = requests.get(README_URL, headers=headers, timeout=(6, 20))
        except requests.RequestException as exc:
            if cached["items"]:
                return len(cached["items"])
            raise ApiCatalogError(f"دریافت فهرست Public APIs ناموفق بود: {exc}") from exc
        if response.status_code == 304 and cached["items"]:
            cached["fetched_at"] = int(time.time())
            self._save_cache(cached)
            return len(cached["items"])
        if not response.ok:
            if cached["items"]:
                return len(cached["items"])
            raise ApiCatalogError(f"منبع Public APIs پاسخ نامعتبر داد ({response.status_code}).")
        raw = response.content
        if len(raw) > MAX_README_BYTES:
            raise ApiCatalogError("فهرست دریافتی از حد اندازه‌ی مجاز بزرگ‌تر است.")
        try:
            markdown = raw.decode("utf-8-sig")
        except UnicodeError as exc:
            raise ApiCatalogError("فهرست Public APIs متن UTF-8 معتبر ندارد.") from exc
        items = parse_public_apis_readme(markdown)
        if not items:
            if cached["items"]:
                return len(cached["items"])
            raise ApiCatalogError("ساختار فهرست Public APIs تغییر کرده و قابل خواندن نیست.")
        self._cache = {
            "fetched_at": int(time.time()),
            "etag": response.headers.get("ETag", ""),
            "items": items,
        }
        self._save_cache(self._cache)
        return len(items)

    def _save_cache(self, data: dict) -> None:
        temp = self.cache_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.cache_path)

    def search(self, query: str, limit: int = 40, refresh: bool = False) -> list[dict]:
        query = " ".join(str(query or "").strip().casefold().split())
        if len(query) < 2:
            raise ApiCatalogError("برای جست‌وجو حداقل دو نویسه وارد کن.")
        self.refresh(force=refresh)
        terms = re.findall(r"[a-z0-9][a-z0-9+_.-]*|[^\W\d_]{2,}", query, flags=re.UNICODE)
        ranked = []
        for item in self._read_cache()["items"]:
            name = str(item.get("name") or "").casefold()
            category = str(item.get("category") or "").casefold()
            haystack = " ".join(str(item.get(key) or "") for key in ("name", "category", "description", "auth")).casefold()
            score = sum(4 if term == name else 2 if term in category else 1 for term in terms if term in haystack)
            if score:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]["category"].casefold(), pair[1]["name"].casefold()))
        return [dict(item) for _, item in ranked[:max(1, min(int(limit), 100))]]

    def get(self, api_id: str) -> dict | None:
        self.refresh()
        for item in self._read_cache()["items"]:
            if item.get("id") == str(api_id):
                return dict(item)
        return None


class PublicApiRegistry:
    """Local user-data registry for APIs explicitly attached to Kira, Ren, or Mika."""

    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "public_api_registry.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("items"), list):
                return value
        except (OSError, ValueError, TypeError):
            pass
        return {"schema": 1, "items": []}

    def _save(self, data: dict) -> None:
        temp = self.path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def register(self, entry: dict, scope: str = "character", character_id: str = "kira") -> dict:
        if not isinstance(entry, dict) or any(not str(entry.get(key) or "").strip() for key in ("id", "name", "url")):
            raise ApiCatalogError("اطلاعات API برای ثبت کامل نیست.")
        parsed = urlparse(str(entry["url"]))
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ApiCatalogError("آدرس API معتبر نیست.")
        data = self._load()
        current = next((x for x in data["items"] if x.get("id") == entry["id"]), None)
        normalized_scope = "global" if scope == "global" else "character"
        cid = str(character_id or "kira")[:80]
        if current is None:
            current = {
                "id": str(entry["id"]),
                "name": str(entry["name"])[:120],
                "category": str(entry.get("category") or "")[:80],
                "description": str(entry.get("description") or "")[:500],
                "auth": str(entry.get("auth") or "Unknown")[:80],
                "https": str(entry.get("https") or "Unknown")[:20],
                "cors": str(entry.get("cors") or "Unknown")[:20],
                "url": str(entry["url"])[:1000],
                "source": SOURCE_URL,
                "scope": normalized_scope,
                "characters": [],
                "enabled": False,
                "integration_status": "catalog_only",
                "connector_id": "",
                "registered_at": int(time.time()),
            }
            data["items"].append(current)
        if normalized_scope == "global":
            current["scope"] = "global"
            current["characters"] = []
        elif current.get("scope") != "global":
            current.setdefault("characters", [])
            if cid not in current["characters"]:
                current["characters"].append(cid)
        self._save(data)
        return dict(current)

    def list_for_character(self, character_id: str) -> list[dict]:
        cid = str(character_id or "kira")[:80]
        items = [
            dict(item) for item in self._load()["items"]
            if item.get("scope") == "global" or cid in item.get("characters", [])
        ]
        return sorted(items, key=lambda x: (x.get("category", "").casefold(), x.get("name", "").casefold()))

    def remove(self, api_id: str, character_id: str | None = None) -> bool:
        data = self._load()
        before = len(data["items"])
        changed = False
        if character_id:
            cid = str(character_id)[:80]
            for item in data["items"]:
                if item.get("id") == str(api_id) and item.get("scope") != "global":
                    remaining = [x for x in item.get("characters", []) if x != cid]
                    if remaining != item.get("characters", []):
                        item["characters"] = remaining
                        changed = True
            filtered = [x for x in data["items"] if x.get("scope") == "global" or x.get("characters")]
            if len(filtered) != len(data["items"]):
                changed = True
            data["items"] = filtered
        else:
            filtered = [x for x in data["items"] if x.get("id") != str(api_id)]
            changed = len(filtered) != before
            data["items"] = filtered
        if changed:
            self._save(data)
        return changed

    def set_connector(self, api_id: str, connector_id: str) -> dict:
        """Mark an existing reviewed application connector as available; never creates or runs code."""
        data = self._load()
        item = next((x for x in data["items"] if x.get("id") == str(api_id)), None)
        if item is None:
            raise ApiCatalogError("API ثبت‌شده پیدا نشد.")
        connector = str(connector_id or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,79}", connector):
            raise ApiCatalogError("شناسه‌ی Connector معتبر نیست.")
        item["connector_id"] = connector
        item["integration_status"] = "connector_available"
        self._save(data)
        return dict(item)
