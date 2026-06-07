---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

# GitHub Trending 采集技能

## 使用场景

- 每日定时采集 GitHub Trending 上的热门开源项目
- 筛选与 AI/LLM/Agent 领域相关的高质量仓库
- 生成结构化知识条目，供后续分析和分发

## 执行步骤

1. **搜索热门仓库** — 通过 GitHub API (`https://api.github.com/search/repositories`) 或 GitHub Trending 页面 (`https://github.com/trending`) 获取当日热门项目，限定时间范围为「今日」或「本周」。
2. **提取信息** — 从每个项目中提取：仓库名、URL、描述、⭐ Star 数、主要编程语言、标签（topics）。
3. **过滤** — 仅纳入与 **AI / LLM / Agent** 相关的项目（关键词：`ai`、`llm`、`agent`、`gpt`、`rag`、`embedding`、`langchain` 等）；排除各类 **Awesome** 列表（如 `awesome-*`、`awesome-list`）。
4. **去重** — 对比已有 `knowledge/articles/` 和 `knowledge/raw/` 中最近 7 天的记录，跳过已采集过的项目（按 `name` + `url` 判重）。
5. **撰写中文摘要** — 为每个项目撰写 80–150 字中文摘要，公式为：「**项目名** + **做什么** + **为什么值得关注**」。摘要需客观、信息密集，不包含主观评价。
6. **排序取 Top 15** — 按 Star 数降序排列，取前 15 个项目。
7. **输出 JSON** — 将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`，格式见下方。

## 注意事项

- ⭐ 优先使用 GitHub API，API 不可用时回退到 WebFetch 抓取 Trending 页面（此时需手动解析 HTML）。
- 🔑 GitHub API 需通过环境变量 `GITHUB_TOKEN` 提供认证，避免请求频率限制（未设置时允许匿名请求，速率较低）。
- 📄 输出文件路径中的日期使用 UTC 时区的 `YYYY-MM-DD` 格式。
- 🧹 过滤和去重步骤不可跳过，确保知识库质量。
- 📊 不足 15 个时按实际数量输出，不强制补足。

## 输出格式

```json
{
  "source": "github_trending",
  "skill": "github-trending",
  "collected_at": "2026-06-05T12:00:00Z",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "LangChain 是一个用于构建 LLM 应用的开发框架，提供链式调用、记忆管理、工具集成等能力，因灵活的抽象设计和活跃的社区生态而备受关注。",
      "stars": 123456,
      "language": "Python",
      "topics": ["llm", "langchain", "ai", "framework"]
    }
  ]
}
```
