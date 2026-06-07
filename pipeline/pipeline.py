"""四步知识库自动化流水线：采集 → 分析 → 整理 → 保存。

Usage:
    python pipeline/pipeline.py --sources github,rss --limit 20
    python pipeline/pipeline.py --sources github --limit 5
    python pipeline/pipeline.py --sources rss --limit 10
    python pipeline/pipeline.py --sources github --limit 5 --dry-run
    python pipeline/pipeline.py --verbose
"""

import os
import re
import json
import argparse
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

from model_client import create_provider, chat_with_retry


# ──────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "knowledge" / "raw"
ARTICLES_DIR = BASE_DIR / "knowledge" / "articles"

GITHUB_API_URL = "https://api.github.com/search/repositories"
HN_RSS_URL = "https://hnrss.org/newest"

GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
GITHUB_SEARCH_QUERY = "ai OR llm OR agent OR 'large language model'"

REQUIRED_ARTICLE_FIELDS = {"id", "title", "source_url", "source_type", "summary", "tags", "status", "lang", "collected_at"}

DEFAULT_LIMIT = 20
TIMEOUT_SECONDS = 30


# ──────────────────────────────────────────────
#  Step 1: 采集
# ──────────────────────────────────────────────


def collect_github(limit: int) -> list[dict]:
    """从 GitHub Search API 采集 AI 相关开源项目。

    Args:
        limit: 采集数量上限。

    Returns:
        原始项目数据列表。
    """
    results: list[dict] = []
    token = os.environ.get(GITHUB_TOKEN_ENV, "")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": GITHUB_SEARCH_QUERY,
        "sort": "stars",
        "order": "desc",
        "per_page": min(limit, 100),
    }

    logger.info("采集 GitHub 项目，上限 {} 个", limit)

    with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
        resp = client.get(GITHUB_API_URL, headers=headers, params=params)
        if resp.status_code >= 400:
            logger.warning("GitHub API 返回 {}，跳过 GitHub 采集", resp.status_code)
            return []
        data = resp.json()

        for item in data.get("items", [])[:limit]:
            results.append({
                "title": item["full_name"],
                "url": item["html_url"],
                "source": "github_trending",
                "description": item.get("description") or "",
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language"),
                "topics": item.get("topics", []),
            })

    logger.info("GitHub 采集完成，获得 {} 条", len(results))
    return results


def collect_rss(limit: int) -> list[dict]:
    """从 Hacker News RSS 采集 AI 相关内容。

    使用 httpx + 正则解析 XML，不引入第三方 RSS 库。

    Args:
        limit: 采集数量上限。

    Returns:
        原始条目数据列表。
    """
    params = {
        "q": "ai OR llm OR agent OR artificial intelligence",
        "limit": limit,
    }

    logger.info("采集 Hacker News RSS，上限 {} 条", limit)

    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True) as client:
        resp = client.get(HN_RSS_URL, params=params)
        if resp.status_code >= 400:
            logger.warning("RSS 源返回 {}，跳过 RSS 采集", resp.status_code)
            return []
        text = resp.text

    items: list[dict] = []

    # 简易正则解析 RSS <item>
    item_pattern = re.compile(r"<item>(.*?)</item>", re.DOTALL)
    title_pattern = re.compile(r"<title>(.*?)</title>", re.DOTALL)
    link_pattern = re.compile(r"<link>(.*?)</link>", re.DOTALL)
    desc_pattern = re.compile(r"<description>(.*?)</description>", re.DOTALL)
    pubdate_pattern = re.compile(r"<pubDate>(.*?)</pubDate>", re.DOTALL)

    for match in item_pattern.finditer(text):
        xml = match.group(1)
        title = _unescape_xml(_extract_one(title_pattern, xml)) or "Untitled"
        link = _extract_one(link_pattern, xml) or ""
        desc = _unescape_xml(_extract_one(desc_pattern, xml)) or ""
        pubdate_str = _extract_one(pubdate_pattern, xml) or ""

        if not link:
            continue

        items.append({
            "title": title,
            "url": link,
            "source": "hacker_news",
            "description": desc,
            "published": pubdate_str,
        })

        if len(items) >= limit:
            break

    logger.info("RSS 采集完成，获得 {} 条", len(items))
    return items


def _extract_one(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _unescape_xml(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = text.replace("&quot;", '"')
    text = text.replace("&apos;", "'")
    text = re.sub(r"<[^>]+>", "", text)
    return text


def save_raw(data: list[dict], source: str) -> Path:
    """将原始采集数据保存到 knowledge/raw/。

    Args:
        data: 原始数据列表。
        source: 数据来源标识。

    Returns:
        保存的文件路径。
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"raw-{source}-{timestamp}.json"
    path = RAW_DIR / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info("原始数据已保存: {}", path)
    return path


# ──────────────────────────────────────────────
#  Step 2: 分析
# ──────────────────────────────────────────────

ANALYSIS_PROMPT = """你是一个 AI 技术内容分析师。请对以下技术条目进行分析，返回 JSON 格式的分析结果。

条目标题：{title}
条目描述：{description}
来源：{source}

请分析并返回如下 JSON（不要包含 markdown 代码块标记）：
{{
    "summary": "中文摘要（100-200 字）",
    "tags": ["标签1", "标签2", "标签3"],
    "score": 整数评分（1-10）
}}

要求：
- 摘要简洁准确，突出技术亮点和价值
- 标签使用英文，2-5 个，优先使用：AI, LLM, Agent, Multi-Agent, RAG, Fine-tuning, Deployment, Security, Open Source, Tool, Framework, MCP
- 评分基于技术新颖度、实用价值和社区关注度
"""


def analyze_item(item: dict, provider) -> dict:
    """对单条原始数据调用 LLM 进行分析。

    Args:
        item: 原始数据条目。
        provider: LLMProvider 实例。

    Returns:
        添加了分析字段的条目。
    """
    title = item.get("title", "Untitled")
    description = item.get("description") or item.get("summary") or ""
    source = item.get("source", "unknown")

    prompt = ANALYSIS_PROMPT.format(title=title, description=description, source=source)

    try:
        resp = chat_with_retry(
            provider,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
            temperature=0.3,
        )
        result = _parse_analysis(resp.content)
        item["summary_zh"] = result.get("summary", description[:100])
        item["tags"] = result.get("tags", ["AI"])
        item["score"] = result.get("score", 5)
        logger.debug("分析完成: {} | 评分 {}", title, item["score"])
    except Exception as e:
        logger.warning("分析失败 ({}): {}，使用默认值", title, e)
        item["summary_zh"] = description[:100] if description else title
        item["tags"] = ["AI"]
        item["score"] = 5

    return item


def _parse_analysis(text: str) -> dict:
    """从 LLM 回复中提取 JSON 分析结果。

    Args:
        text: LLM 回复文本。

    Returns:
        解析后的分析结果字典。
    """
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    logger.warning("无法解析 LLM 分析结果，使用兜底值")
    return {"summary": text[:100], "tags": ["AI"], "score": 5}


# ──────────────────────────────────────────────
#  Step 3: 整理
# ──────────────────────────────────────────────


def organize_articles(items: list[dict]) -> list[dict]:
    """去重、格式标准化、校验。

    Args:
        items: 已分析的条目列表。

    Returns:
        整理后的文章列表。
    """
    seen_urls: set[str] = set()
    articles: list[dict] = []

    for item in items:
        url = item.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        article = _item_to_article(item)
        if _validate_article(article):
            articles.append(article)

    logger.info("整理完成: {} 条 → {} 条（去重+校验后）", len(items), len(articles))
    return articles


def _item_to_article(item: dict) -> dict:
    """将原始条目转换为标准文章格式。

    Args:
        item: 原始/已分析条目。

    Returns:
        符合知识条目 JSON 格式的字典。
    """
    now = datetime.now(timezone.utc)
    source_type = item.get("source", "github_trending")
    title = item.get("title", "Untitled")
    url = item.get("url", "")

    raw_id = hashlib.sha256(url.encode()).hexdigest()[:12]
    article_id = f"{source_type}-{now.strftime('%Y%m%d')}-{raw_id}"

    summary = item.get("summary_zh") or item.get("summary") or item.get("description", "")
    if len(summary) > 500:
        summary = summary[:500]

    tags = item.get("tags", ["AI"])
    if isinstance(tags, str):
        tags = [tags]

    published_raw = item.get("published") or item.get("published_at")
    published = None
    if published_raw:
        try:
            dt = _parse_rss_date(published_raw)
            published = dt.isoformat()
        except Exception:
            published = None

    return {
        "id": article_id,
        "title": title,
        "source_url": url,
        "source_type": source_type,
        "summary": summary,
        "tags": tags[:10],
        "status": "draft",
        "lang": "zh",
        "collected_at": now.isoformat(),
        "published_at": published,
        "score": item.get("score"),
    }


def _parse_rss_date(date_str: str) -> datetime:
    """解析 RSS 日期字符串。

    Args:
        date_str: RSS 日期字符串（如 RFC 822）。

    Returns:
        解析后的 datetime 对象。
    """
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(date_str)


def _validate_article(article: dict) -> bool:
    """校验文章是否包含所有必填字段。

    Args:
        article: 文章字典。

    Returns:
        是否有效。
    """
    missing = REQUIRED_ARTICLE_FIELDS - set(article.keys())
    if missing:
        logger.warning("文章缺少字段 {}: {}", missing, article.get("title", ""))
        return False
    if not article.get("source_url"):
        logger.warning("文章缺少 URL，跳过: {}", article.get("title", ""))
        return False
    return True


# ──────────────────────────────────────────────
#  Step 4: 保存
# ──────────────────────────────────────────────


def save_articles(articles: list[dict], dry_run: bool = False) -> list[Path]:
    """将文章保存为独立 JSON 文件到 knowledge/articles/。

    Args:
        articles: 文章列表。
        dry_run: 是否干跑（仅打印不写入）。

    Returns:
        保存的文件路径列表。
    """
    saved: list[Path] = []
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    for article in articles:
        filename = f"{article['id']}.json"
        path = ARTICLES_DIR / filename

        if dry_run:
            logger.info("[干跑] 将写入: {} ({} 条标签)", filename, len(article.get("tags", [])))
            saved.append(path)
            continue

        with open(path, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)

        logger.debug("文章已保存: {}", filename)
        saved.append(path)

    action = "干跑" if dry_run else "保存"
    logger.info("{} 完成: {} 篇文章", action, len(saved))
    return saved


# ──────────────────────────────────────────────
#  流水线编排
# ──────────────────────────────────────────────


def run_pipeline(
    sources: list[str],
    limit: int = DEFAULT_LIMIT,
    dry_run: bool = False,
) -> int:
    """执行完整流水线：采集 → 分析 → 整理 → 保存。

    Args:
        sources: 数据来源列表，可选 "github"、"rss"。
        limit: 每源采集上限。
        dry_run: 是否干跑。

    Returns:
        处理并保存的文章数量。
    """
    all_raw: list[dict] = []
    source_names: list[str] = []

    # ── Step 1: 采集 ──
    logger.info("━" * 40)
    logger.info("Step 1: 采集")

    if "github" in sources:
        items = collect_github(limit)
        if items:
            save_raw(items, "github")
            all_raw.extend(items)
            source_names.append("github")
        else:
            logger.warning("GitHub 未采集到数据")

    if "rss" in sources:
        items = collect_rss(limit)
        if items:
            save_raw(items, "rss")
            all_raw.extend(items)
            source_names.append("rss")
        else:
            logger.warning("RSS 未采集到数据")

    if not all_raw:
        logger.warning("所有来源均未采集到数据，流水线中止")
        return 0

    # ── Step 2: 分析 ──
    logger.info("━" * 40)
    logger.info("Step 2: 分析（调用 LLM）")

    provider = None
    analyzed: list[dict] = []
    if dry_run:
        logger.info("[干跑] 跳过 LLM 分析")
        for item in all_raw:
            item["summary_zh"] = item.get("description", item.get("title", ""))
            item["tags"] = ["AI"]
            item["score"] = 5
            analyzed.append(item)
    else:
        provider = create_provider()
        for i, item in enumerate(all_raw, 1):
            logger.info("分析 ({}/{}) …", i, len(all_raw))
            analyzed.append(analyze_item(item, provider))

    # ── Step 3: 整理 ──
    logger.info("━" * 40)
    logger.info("Step 3: 整理")

    articles = organize_articles(analyzed)

    # ── Step 4: 保存 ──
    logger.info("━" * 40)
    logger.info("Step 4: 保存")

    save_articles(articles, dry_run=dry_run)

    logger.info("━" * 40)
    count = len(articles)
    action = "干跑" if dry_run else "写入"
    logger.info("流水线完成: 采集 {} 条 → 整理 {} 篇 → {} {} 个文件", len(all_raw), count, action, count)

    if provider:
        provider.close()

    return count


# ──────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数。

    Args:
        argv: 命令行参数列表（默认使用 sys.argv）。

    Returns:
        解析后的命名空间。
    """
    parser = argparse.ArgumentParser(
        description="AI 知识库自动化流水线：采集 → 分析 → 整理 → 保存",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="数据来源，逗号分隔 (github, rss)，默认 github,rss",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"每源采集上限（默认 {DEFAULT_LIMIT}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式：不调用 LLM，不写入文件",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="详细日志输出（DEBUG 级别）",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> None:
    """CLI 入口。

    Args:
        argv: 命令行参数列表。
    """
    args = parse_args(argv)

    log_level = "DEBUG" if args.verbose else "INFO"
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=""),
        format="<level>{level:<7}</level> | {message}" if args.verbose else "{message}",
        level=log_level,
        colorize=False,
    )

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    run_pipeline(sources=sources, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
