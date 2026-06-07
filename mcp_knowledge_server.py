#!/usr/bin/env python3
"""MCP Server — 本地知识库搜索服务（JSON-RPC 2.0 over stdio）。

Usage:
    python mcp_knowledge_server.py
"""

import json
import sys
import glob
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcp-knowledge-server", "version": "1.0.0"}


# ── Data Layer ──


def _load_all_articles() -> list[dict]:
    articles = []
    for fp in sorted(glob.glob(str(ARTICLES_DIR / "*.json"))):
        with open(fp, encoding="utf-8") as f:
            articles.append(json.load(f))
    return articles


def search_articles(keyword: str, limit: int = 5) -> list[dict]:
    kw = keyword.lower()
    results = []
    for art in _load_all_articles():
        if kw in art.get("title", "").lower() or kw in art.get("summary", "").lower():
            results.append(art)
            if len(results) >= limit:
                break
    return results


def get_article(article_id: str) -> dict | None:
    for art in _load_all_articles():
        if art.get("id") == article_id:
            return art
    return None


def knowledge_stats() -> dict:
    articles = _load_all_articles()
    total = len(articles)
    source_dist: dict[str, int] = {}
    tag_count: dict[str, int] = {}

    for art in articles:
        st = art.get("source_type", "unknown")
        source_dist[st] = source_dist.get(st, 0) + 1

        for tag in art.get("tags", []):
            tag_count[tag] = tag_count.get(tag, 0) + 1

    top_tags = sorted(tag_count.items(), key=lambda x: -x[1])[:20]
    return {
        "total_articles": total,
        "source_distribution": source_dist,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
    }


# ── MCP Protocol ──


def _result(id: Any, data: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "result": data}, ensure_ascii=False)


def _error(id: Any, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


TOOLS = [
    {
        "name": "search_articles",
        "description": "按关键词搜索本地知识库中的文章标题和摘要",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "limit": {"type": "integer", "description": "返回结果上限", "default": 5},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "按文章 ID 获取完整内容",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "文章 ID"},
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "获取本地知识库的统计信息（文章总数、来源分布、热门标签）",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_request(req: dict) -> str:
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    if method == "initialize":
        return _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })

    if method == "tools/list":
        return _result(rid, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name", "")
        args = params.get("arguments", {})

        if name == "search_articles":
            keyword = args.get("keyword", "")
            limit = int(args.get("limit", 5))
            data = search_articles(keyword, limit)
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return _result(rid, {"content": [{"type": "text", "text": text}]})

        if name == "get_article":
            article_id = args.get("article_id", "")
            data = get_article(article_id)
            if data is None:
                return _error(rid, -1, f"文章不存在: {article_id}")
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return _result(rid, {"content": [{"type": "text", "text": text}]})

        if name == "knowledge_stats":
            data = knowledge_stats()
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return _result(rid, {"content": [{"type": "text", "text": text}]})

        return _error(rid, -32601, f"未知工具: {name}")

    if method == "notifications/initialized":
        return ""

    return _error(rid, -32601, f"未知方法: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        resp = handle_request(req)
        if resp:
            sys.stdout.write(resp + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
