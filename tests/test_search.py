from luo.config import Settings
from luo.search import (
    SearchClient,
    _loads_tolerant,
    SearchResponse,
    SearchResult,
    parse_bing_images,
    parse_bing_rss,
    parse_deepseek_response,
    parse_sogou_images,
    sanitize_query,
)


def test_sanitize_query():
    assert sanitize_query("[CQ:at,qq=1] 杭州\t天气 ") == "杭州 天气"
    assert len(sanitize_query("x" * 200)) == 120


def test_parse_deepseek_response():
    payload = {
        "content": [
            {
                "type": "text",
                "citations": [
                    {"url": "https://example.com/a", "cited_text": "摘要A"}
                ],
            },
            {
                "type": "web_search_tool_result",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "标题A",
                        "url": "https://example.com/a",
                    },
                    {
                        "type": "web_search_result",
                        "title": "标题B",
                        "url": "https://example.com/b",
                    },
                ],
            },
        ]
    }
    results = parse_deepseek_response(payload, 5)
    assert results[0] == SearchResult(
        "标题A", "https://example.com/a", "摘要A"
    )
    assert results[1].title == "标题B"


def test_parse_bing_rss():
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>T1</title><link>https://a.com</link><description>D1</description></item>
    </channel></rss>"""
    assert parse_bing_rss(xml) == [SearchResult("T1", "https://a.com", "D1")]


def test_loads_tolerant_baidu_escape():
    data = _loads_tolerant(r'{"a":"x\y"}')
    assert data["a"] == "x\\y"


def test_parse_bing_images():
    html = (
        '<a m="{&quot;murl&quot;:&quot;https://example.com/a.jpg&quot;}"></a>'
        '<a m="{&quot;murl&quot;:&quot;https://example.com/b.png&quot;}"></a>'
    )
    results = parse_bing_images(html, 5)
    assert [item.url for item in results] == [
        "https://example.com/a.jpg",
        "https://example.com/b.png",
    ]


def test_parse_sogou_images():
    html = (
        r'{"picUrl":"https://example.com/a.jpg"}'
        r'{"picUrl":"https://example.com/b.gif"}'
    )
    results = parse_sogou_images(html, 5)
    assert [item.url for item in results] == [
        "https://example.com/a.jpg",
        "https://example.com/b.gif",
    ]


def test_format_results():
    client = SearchClient(Settings(_env_file=None))
    text = client.format_results(
        SearchResponse(
            results=[SearchResult("T", "https://a.com", "D")],
            answer="摘要内容",
        )
    )
    assert "摘要内容" in text
    assert "T" in text
    assert "https://a.com" in text
    assert "D" in text
