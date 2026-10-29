"""联网搜索：DeepSeek 原生 web_search，Bing RSS 兜底。"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

from .config import Settings

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "搜索互联网，获取当前信息、新闻、天气、软件版本、网络用语、游戏资料等。"
            "只在不确定或需要最新信息时调用；能确定的事情不要搜。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
            },
            "required": ["query"],
        },
    },
}


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    answer: str = ""


@dataclass(frozen=True)
class ImageResult:
    url: str
    title: str = ""
    host: str = ""
    width: int = 0
    height: int = 0
    is_gif: bool = False


SEND_WEB_MEME_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_web_meme",
        "description": (
            "当用户想要梗图/表情包、本地库没有合适的，联网搜一张发出去，"
            "并自动存进梗图库。query 尽量用用户的原话/梗词，例如用户说"
            "“发个无语的表情包”就用“无语 表情包”，不要泛化。"
            "只在需要时偶尔使用，不要频繁搜图。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索词，例如 无语 表情包",
                },
                "tag": {
                    "type": "string",
                    "description": "存库标签，可选；默认用搜索词",
                },
            },
            "required": ["query"],
        },
    },
}


def sanitize_query(query: str) -> str:
    text = re.sub(r"\[CQ:[^\]]*\]", " ", str(query or ""))
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:120]


def _valid_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _loads_tolerant(text: str) -> Any:
    """Baidu acjson 偶尔带非法反斜杠转义，先补齐再解析。"""
    text = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)
    return json.loads(text, strict=False)


def parse_deepseek_response(
    payload: dict[str, Any], max_results: int = 5
) -> list[SearchResult]:
    blocks = payload.get("content") or []
    snippets: dict[str, str] = {}
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        for cite in block.get("citations") or []:
            if not isinstance(cite, dict):
                continue
            url = str(cite.get("url") or "").strip()
            text = str(cite.get("cited_text") or "").strip()
            if _valid_url(url) and text and url not in snippets:
                snippets[url] = text[:500]

    out: list[SearchResult] = []
    seen: set[str] = set()
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        for item in block.get("content") or []:
            if not isinstance(item, dict) or item.get("type") != "web_search_result":
                continue
            url = str(item.get("url") or "").strip()
            if not _valid_url(url) or url in seen:
                continue
            seen.add(url)
            out.append(
                SearchResult(
                    title=str(item.get("title") or "").strip()[:200],
                    url=url,
                    snippet=snippets.get(url, ""),
                )
            )
            if len(out) >= max_results:
                return out
    return out


def parse_bing_images(html_text: str, limit: int = 8) -> list[ImageResult]:
    text = html_lib.unescape(html_text)
    results: list[ImageResult] = []
    seen: set[str] = set()
    for match in re.finditer(r'"murl":"(https?://[^"]+)"', text):
        url = match.group(1).replace("\\/", "/").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        results.append(ImageResult(url=url))
        if len(results) >= limit:
            break
    return results


PREFERRED_IMAGE_DOMAINS = (
    "qiubiaoqing",
    "hdslb",
    "bilibili",
    "sinaimg",
    "weibo",
    "qpic",
    "douyinpic",
    "xiaohongshu",
    "tieba.baidu",
    "biaoqing",
    "qqtn",
    "doutula",
)
BLOCKED_IMAGE_DOMAINS = (
    "ibaotu",
    "duitang",
    "huaban",
    "tukuppt",
    "dtstatic",
    "qulishi",
    "3dmgame",
    "whb.cn",
    "nipic",
    "699pic",
    "ntimg",
    "nximg",
    "58pic",
    "16pic",
    "ooopic",
    "zcool",
    "51miz",
    "sucai",
    "pixabay",
    "gettyimages",
    "shutterstock",
)


def expand_image_query(query: str) -> str:
    text = query.strip()
    if not any(
        word in text.lower() for word in ("表情包", "梗图", "沙雕", "动图", "meme")
    ):
        text = f"{text} 表情包 沙雕 动图"
    return text


def image_result_score(item: ImageResult) -> int:
    host = (item.host or urllib.parse.urlparse(item.url).netloc).lower()
    score = 0
    if any(domain in host for domain in PREFERRED_IMAGE_DOMAINS):
        score += 5
    if any(domain in host for domain in BLOCKED_IMAGE_DOMAINS):
        score -= 10
    if item.is_gif or item.url.lower().split("?")[0].endswith(".gif"):
        score += 3
    if item.width >= 300 and item.height >= 300:
        score += 2
    return score


def image_url_score(url: str) -> int:
    return image_result_score(ImageResult(url=url))


def parse_baidu_images(
    payload: dict[str, Any], limit: int = 8
) -> list[ImageResult]:
    items = payload.get("data") or []
    results: list[ImageResult] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(
            item.get("middleURL")
            or item.get("hoverURL")
            or item.get("thumbURL")
            or ""
        ).strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        try:
            width = int(item.get("width") or 0)
        except (TypeError, ValueError):
            width = 0
        try:
            height = int(item.get("height") or 0)
        except (TypeError, ValueError):
            height = 0
        raw_gif = item.get("is_gif")
        is_gif = (
            raw_gif in (1, True, "1", "true", "True")
            or url.lower().split("?")[0].endswith(".gif")
        )
        results.append(
            ImageResult(
                url=url,
                host=str(item.get("fromURLHost") or ""),
                width=width,
                height=height,
                is_gif=is_gif,
            )
        )
        if len(results) >= limit:
            break
    return results


def parse_sogou_images(html_text: str, limit: int = 8) -> list[ImageResult]:
    text = html_lib.unescape(html_text)
    results: list[ImageResult] = []
    seen: set[str] = set()
    for pattern in (r'"picUrl":"([^"]+)"', r'"oriPicUrl":"([^"]+)"'):
        for match in re.finditer(pattern, text):
            url = (
                match.group(1)
                .replace("\\u002F", "/")
                .replace("\\/", "/")
                .strip()
            )
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            results.append(ImageResult(url=url))
            if len(results) >= limit:
                return results
    return results


def parse_bing_rss(xml_text: str, max_results: int = 5) -> list[SearchResult]:
    root = ET.fromstring(xml_text)
    out: list[SearchResult] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        if not _valid_url(link):
            continue
        out.append(SearchResult(title=title[:200], url=link, snippet=desc[:500]))
        if len(out) >= max_results:
            break
    return out


class SearchClient:
    def __init__(self, settings: Settings) -> None:
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.web_search_base_url.rstrip("/")
        self.model = settings.web_search_model
        self.max_results = settings.web_search_max_results
        provider = settings.web_search_provider
        self.provider = provider if provider in {"auto", "deepseek", "bing"} else "auto"
        self.timeout = 35
        self._cache: dict[str, tuple[float, SearchResponse]] = {}
        self._image_cache: dict[str, tuple[float, list[ImageResult]]] = {}
        self._ttl = 300.0

    def search(self, query: str) -> SearchResponse:
        clean = sanitize_query(query)
        if not clean:
            return SearchResponse([])
        now = time.monotonic()
        cached = self._cache.get(clean)
        if cached and now - cached[0] < self._ttl:
            return cached[1]

        response = SearchResponse([])
        if self.provider != "bing":
            try:
                response = self._deepseek(clean)
            except Exception:  # noqa: BLE001
                response = SearchResponse([])
        if not response.results and not response.answer and self.provider != "deepseek":
            try:
                response = self._bing(clean)
            except Exception:  # noqa: BLE001
                response = SearchResponse([])
        if response.results or response.answer:
            self._cache[clean] = (now, response)
        return response

    def _images_baidu(self, query: str, limit: int) -> list[ImageResult]:
        params = urllib.parse.urlencode(
            {
                "tn": "resultjson_com",
                "ipn": "rj",
                "word": query,
                "pn": 0,
                "rn": max(limit * 2, 20),
            }
        )
        req = urllib.request.Request(
            f"https://image.baidu.com/search/acjson?{params}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": "https://image.baidu.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        payload = _loads_tolerant(body)
        return parse_baidu_images(payload, limit)

    def _images_bing(self, query: str, limit: int) -> list[ImageResult]:
        params = urllib.parse.urlencode(
            {"q": query, "form": "HDRSC2", "first": 1, "adlt": "strict"}
        )
        req = urllib.request.Request(
            f"https://cn.bing.com/images/search?{params}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            html_text = resp.read(2_000_000).decode("utf-8", "replace")
        return parse_bing_images(html_text, limit)

    def _images_sogou(self, query: str, limit: int) -> list[ImageResult]:
        params = urllib.parse.urlencode({"query": query, "reqType": 0})
        req = urllib.request.Request(
            f"https://pic.sogou.com/pics?{params}",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            html_text = resp.read(1_500_000).decode("utf-8", "replace")
        return parse_sogou_images(html_text, limit)

    def search_images(
        self, query: str, limit: int | None = None
    ) -> list[ImageResult]:
        clean = sanitize_query(query)
        if not clean:
            return []
        limit = limit or self.max_results
        now = time.monotonic()
        cached = self._image_cache.get(clean)
        if cached and now - cached[0] < self._ttl:
            return cached[1][:limit]
        expanded = expand_image_query(clean)
        results: list[ImageResult] = []
        for source in (
            self._images_baidu,
            self._images_bing,
            self._images_sogou,
        ):
            try:
                candidates = source(expanded, max(limit * 3, 12))
            except Exception:  # noqa: BLE001
                candidates = []
            ranked = sorted(
                candidates, key=image_result_score, reverse=True
            )
            good = [
                item for item in ranked if image_result_score(item) > -5
            ]
            if good:
                results = good[:limit]
                break
        if results:
            self._image_cache[clean] = (now, results)
        return results

    def _deepseek(self, query: str) -> SearchResponse:
        if not self.api_key:
            raise RuntimeError("没有 DeepSeek API key")
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Perform a web search for the query: {query}",
                        }
                    ],
                }
            ],
            "tools": [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 5,
                }
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "authorization": f"Bearer {self.api_key}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.load(resp)

        answer_parts: list[str] = []
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    answer_parts.append(text)
        return SearchResponse(
            results=parse_deepseek_response(payload, self.max_results),
            answer="\n\n".join(answer_parts)[:2000],
        )

    def _bing(self, query: str) -> SearchResponse:
        params = urllib.parse.urlencode(
            {
                "q": query,
                "format": "rss",
                "count": str(min(20, self.max_results)),
                "setlang": "zh-hans",
                "cc": "CN",
            }
        )
        req = urllib.request.Request(
            f"https://cn.bing.com/search?{params}",
            headers={"user-agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            xml_text = resp.read(512000).decode("utf-8", "replace")
        return SearchResponse(parse_bing_rss(xml_text, self.max_results))

    def format_results(self, response: SearchResponse) -> str:
        if not response.results and not response.answer:
            return "没有找到结果。"
        parts: list[str] = []
        if response.answer:
            parts.append("摘要：\n" + response.answer)
        if response.results:
            lines = ["来源："]
            for index, item in enumerate(response.results, 1):
                lines.append(f"{index}. {item.title}\n   {item.url}")
                if item.snippet:
                    lines.append(f"   {item.snippet}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)
