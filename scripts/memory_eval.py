"""记忆检索基线评测。

不调用模型，只测“给定一条查询，目标记忆能否进入 top-k”。

用法：
    uv run python scripts/memory_eval.py

当前检索是关键词 + 重要度 + 时间，所以：
- 查询里有原词（香菜、末影龙、钓鱼）→ 应该命中
- 换个说法（忌口、住哪个城市、外号）→ 大概率漏
这些漏掉的 case 就是后面上语义检索的依据。
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from luo.config import Settings
from luo.memory import MemoryManager
from luo.store import Store


class NoopLLM:
    def complete(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        return ""


MEMORIES: list[tuple[str, str, int, str]] = [
    ("fact", "用户的名字叫小林", 4, "closed"),
    ("preference", "用户不吃香菜", 4, "closed"),
    ("fact", "用户住在杭州", 3, "closed"),
    ("shared_experience", "一起在成都吃过火锅", 3, "closed"),
    ("promise", "明天一起打末影龙", 4, "open"),
    ("promise", "周末一起钓鱼", 3, "closed"),
    ("inside_joke", "用户把香菜叫肥皂", 2, "closed"),
    # 干扰项：让 top-k 不是“全都要”
    ("fact", "用户提到过游戏《星露谷物语》", 3, "closed"),
    ("fact", "用户最近在学 Rust", 3, "closed"),
    ("fact", "用户喜欢听城市流行", 3, "closed"),
    ("fact", "用户用 VS Code 写代码", 3, "closed"),
    ("fact", "用户养了一只猫", 3, "closed"),
    ("fact", "用户不喜欢下雨天", 3, "closed"),
    ("fact", "用户喜欢喝冰美式", 3, "closed"),
    ("fact", "用户周末常去图书馆", 3, "closed"),
    ("shared_experience", "一起看过一部科幻电影", 3, "closed"),
    ("fact", "用户提过想学吉他", 3, "closed"),
    ("fact", "用户讨厌排队", 3, "closed"),
    ("fact", "用户喜欢靠窗的位置", 3, "closed"),
    ("fact", "用户在用 Windows 11", 3, "closed"),
    ("fact", "用户提到过想去日本", 3, "closed"),
    ("fact", "用户喜欢像素风游戏", 3, "closed"),
    ("fact", "用户晚上容易失眠", 3, "closed"),
]

CASES: list[dict[str, str]] = [
    {"query": "我叫什么名字", "expect": "用户的名字叫小林"},
    {"query": "我住在哪", "expect": "用户住在杭州"},
    {"query": "我吃什么", "expect": "用户不吃香菜"},
    {"query": "香菜", "expect": "用户不吃香菜"},
    {"query": "末影龙还打吗", "expect": "明天一起打末影龙"},
    {"query": "周末钓鱼", "expect": "周末一起钓鱼"},
    {"query": "上次吃火锅", "expect": "一起在成都吃过火锅"},
    {"query": "肥皂", "expect": "用户把香菜叫肥皂"},
    {"query": "我有什么没做完的事", "expect": "明天一起打末影龙"},
    {"query": "我忌口什么", "expect": "用户不吃香菜"},
    {"query": "我住哪个城市", "expect": "用户住在杭州"},
    {"query": "我的外号", "expect": "用户把香菜叫肥皂"},
]


def build_store(db_path: Path) -> Store:
    store = Store(db_path)
    for kind, content, importance, status in MEMORIES:
        store.add_memory("eval", kind, content, importance, status=status)
    return store


def evaluate(store: Store, settings: Settings) -> dict[str, Any]:
    manager = MemoryManager(store, NoopLLM(), settings, "eval")
    rows: list[dict[str, Any]] = []
    for case in CASES:
        picked = manager.retrieve(case["query"])
        contents = [str(item["content"]) for item in picked]
        rank = next(
            (
                index + 1
                for index, content in enumerate(contents)
                if case["expect"] in content
            ),
            0,
        )
        rows.append(
            {
                "query": case["query"],
                "expect": case["expect"],
                "rank": rank,
                "hit": rank > 0,
                "picked": contents,
            }
        )
    hits = sum(1 for row in rows if row["hit"])
    ranks = [row["rank"] for row in rows if row["hit"]]
    return {
        "rows": rows,
        "hits": hits,
        "total": len(rows),
        "hit_rate": hits / len(rows) if rows else 0.0,
        "mrr": sum(1 / rank for rank in ranks) / len(ranks) if ranks else 0.0,
        "top_k": settings.memory_top_k,
    }


def main() -> None:
    settings = Settings(_env_file=None, memory_top_k=5)
    with tempfile.TemporaryDirectory() as tmp:
        store = build_store(Path(tmp) / "eval.db")
        result = evaluate(store, settings)
        print(f"{'query':<20} {'hit':<5} {'rank':<5} expected")
        print("-" * 70)
        for row in result["rows"]:
            print(
                f"{row['query']:<20} {str(row['hit']):<5} "
                f"{row['rank'] or '-':<5} {row['expect']}"
            )
        print("-" * 70)
        print(
            f"hit@{result['top_k']}: {result['hits']}/{result['total']} "
            f"= {result['hit_rate']:.1%}"
        )
        print(f"MRR: {result['mrr']:.3f}")
        store.close()


if __name__ == "__main__":
    main()
