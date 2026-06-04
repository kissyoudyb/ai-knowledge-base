# AI Knowledge Base — Agent 指南

## 项目概述

自动从 **GitHub Trending** 和 **Hacker News** 采集 AI/LLM/Agent 领域的技术动态，经 AI 分析、结构化处理后存储为 JSON 格式的知识条目，并通过 **Telegram / 飞书** 等多渠道分发给目标用户。整个流程由 OpenCode Agent 驱动，实现「采集 → 分析 → 分发」的全自动化。

## 技术栈

| 类别       | 技术                              |
| ---------- | --------------------------------- |
| 运行时     | Python 3.12                       |
| 编排框架   | OpenCode + 国产大模型（DeepSeek） |
| 工作流引擎 | LangGraph                         |
| 爬虫框架   | OpenClaw                          |

## 编码规范

- **PEP 8** — 遵循 Python 官方编码风格
- **命名风格** — 变量/函数/方法使用 `snake_case`，类名使用 `PascalCase`，常量使用 `UPPER_SNAKE_CASE`
- **文档字符串** — 所有公开模块、类、函数必须编写 Google 风格 docstring
- **日志** — 禁止裸 `print()`，一律使用 `logging` 模块（通过 `loguru` 封装）
- **类型注解** — 所有函数参数和返回值必须标注类型
- **导入顺序** — 标准库 → 第三方库 → 本地模块，每组之间空一行

## 项目结构

```
ai-knowledge-base/
├── .opencode/
│   ├── agents/          # Agent 定义文件（角色配置）
│   └── skills/          # Skill 定义文件（可复用的工具模块）
├── knowledge/
│   ├── raw/             # 原始抓取数据（未经 AI 处理）
│   └── articles/        # 结构化知识条目（AI 分析后的 JSON 输出）
└── AGENTS.md            # 本文件
```

## 知识条目 JSON 格式

```json
{
  "id": "uuid-v7",
  "title": "文章标题",
  "source_url": "https://github.com/...",
  "source_type": "github_trending | hacker_news",
  "summary": "AI 自动生成的 100-200 字中文摘要",
  "tags": ["AI", "LLM", "Multi-Agent"],
  "status": "pending | published | archived",
  "lang": "zh",
  "collected_at": "2026-06-04T12:00:00Z",
  "published_at": "2026-06-03T08:00:00Z"
}
```

## Agent 角色概览

| 角色     | 职责                                                          | 输入              | 输出                     |
| -------- | ------------------------------------------------------------- | ----------------- | ------------------------ |
| 采集     | 定时抓取 GitHub Trending / Hacker News，提取原始内容          | 固定 URL 列表     | 原始文本 → `raw/`        |
| 分析     | 调用 LLM 对原始内容进行摘要、打标签、翻译为中文、结构化输出   | `raw/` 中的文件   | 结构化 JSON → `articles/` |
| 整理     | 检查文章质量、去重、管理状态生命周期、触发多渠道分发           | `articles/` 中的 JSON | 确认/丢弃/分发动作    |

## 红线（绝对禁止）

- ❌ 禁止将 API Key、Token 等敏感信息硬编码在代码中，必须通过环境变量或 `.env` 注入
- ❌ 禁止在提交前使用裸 `print()` 调试，必须使用 `loguru.logger`
- ❌ 禁止对 `articles/` 下的已发布条目直接修改元数据，必须通过 Agent 状态机流转
- ❌ 禁止在爬虫中使用未设置 `User-Agent` 和 `Robots.txt` 遵守的请求
- ❌ 禁止在代码库中提交超过 1MB 的二进制文件或日志文件
