#!/usr/bin/env python3
"""5-dimension quality scoring for knowledge entry JSON files."""

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# ── Standard tag whitelist ──────────────────────────────────────────────

STANDARD_TAGS = {
    "AI", "LLM", "Agent", "Multi-Agent", "RAG", "Fine-tuning",
    "NLP", "CV", "Multi-Modal", "Multi-Model", "ML", "Deep Learning",
    "Open Source", "CLI", "API", "SDK", "Framework",
    "Security", "Privacy", "Safety", "Alignment",
    "Python", "Rust", "JavaScript", "TypeScript", "Swift",
    "Agentic", "Tool Use", "MCP", "Function Calling",
    "Vector DB", "Embedding", "Search",
    "DevTools", "Developer Experience", "Productivity",
    "Tutorial", "Best Practice", "Research", "Paper",
    "Quant", "Finance", "Crypto", "Blockchain",
    "macOS", "iOS", "Android", "Cross-Platform",
    "Edge Computing", "On-Device", "Local",
    "Automation", "Workflow", "Orchestration",
    "Testing", "Evaluation", "Benchmark",
    "Claude", "OpenAI", "DeepSeek", "Ollama",
    "Penetration Testing", "Autocomplete",
    "Coding", "Coding Standards", "Rules",
    "Memory", "Learning", "Runtime",
    "Apple Silicon", "Ollama",
    "Frontend", "Quantitative Finance",
}

# ── Buzzword blacklist ──────────────────────────────────────────────────

BUZZWORDS_ZH = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
]

BUZZWORDS_EN = [
    "groundbreaking", "revolutionary", "game-changing",
    "cutting-edge", "disruptive", "paradigm shift",
    "next-generation", "state-of-the-art",
]

BUZZWORD_PATTERNS: list[re.Pattern] = [
    re.compile(re.escape(w)) for w in BUZZWORDS_ZH + BUZZWORDS_EN
]

# ── Technical keywords for summary bonus ────────────────────────────────

TECH_KEYWORDS = [
    "AI", "LLM", "Agent", "ML", "NLP", "RAG",
    "neural network", "deep learning", "transformer",
    "fine-tun", "embedding", "vector",
    "multi-agent", "multi-modal", "multimodal",
]

TECH_KEYWORD_PATTERNS: list[re.Pattern] = [
    re.compile(re.escape(w), re.IGNORECASE) for w in TECH_KEYWORDS
]


# ── Dataclasses ─────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: float
    detail: str = ""

    @property
    def ratio(self) -> float:
        return self.score / self.max_score if self.max_score else 0.0


@dataclass
class QualityReport:
    filepath: Path
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def total(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def max_total(self) -> float:
        return sum(d.max_score for d in self.dimensions)

    @property
    def grade(self) -> str:
        t = self.total
        if t >= 80:
            return "A"
        if t >= 60:
            return "B"
        return "C"


# ── Dimension scorers ───────────────────────────────────────────────────

def _text_contains_tech_keywords(text: str) -> int:
    count = 0
    for pat in TECH_KEYWORD_PATTERNS:
        if pat.search(text):
            count += 1
    return count


def score_summary(data: dict) -> DimensionScore:
    summary = data.get("summary", "")
    length = len(summary)

    if length >= 50:
        base = 20
    elif length >= 20:
        base = 10
    else:
        base = 0

    bonus = min(_text_contains_tech_keywords(summary), 5)
    score = min(base + bonus, 25)
    detail = f"{length} chars, {bonus} tech keyword bonus"
    return DimensionScore("Summary Quality", score, 25, detail)


def score_technical_depth(data: dict) -> DimensionScore:
    raw = data.get("score")
    if not isinstance(raw, (int, float)):
        return DimensionScore("Technical Depth", 0, 25, "no score field")

    raw = float(raw)
    if raw < 1 or raw > 10:
        return DimensionScore("Technical Depth", 0, 25, f"score={raw} out of range")

    mapped = round(raw * 2.5, 1)
    detail = f"score={raw} → {mapped}/25"
    return DimensionScore("Technical Depth", mapped, 25, detail)


def score_format_compliance(data: dict) -> DimensionScore:
    points = 0
    reasons: list[str] = []

    # id
    id_val = data.get("id", "")
    if isinstance(id_val, str) and re.match(r"^[a-z_]+-\d{8}-[a-f0-9]{12}$", id_val):
        points += 4
    else:
        reasons.append("id format invalid")

    # title
    title = data.get("title", "")
    if isinstance(title, str) and title.strip():
        points += 4
    else:
        reasons.append("title missing/empty")

    # source_url
    url = data.get("source_url", "")
    if isinstance(url, str) and re.match(r"^https?://", url):
        points += 4
    else:
        reasons.append("source_url invalid")

    # status
    status = data.get("status", "")
    if status in {"draft", "review", "published", "archived"}:
        points += 4
    else:
        reasons.append(f"status={status!r} invalid")

    # timestamps
    ts_ok = 0
    for key in ("collected_at", "published_at"):
        val = data.get(key)
        if val is not None and isinstance(val, str):
            try:
                datetime.fromisoformat(val.replace("Z", "+00:00"))
                ts_ok += 2
            except ValueError:
                pass
    points += ts_ok
    if ts_ok < 4:
        reasons.append("timestamp missing/invalid")

    detail = "; ".join(reasons) if reasons else "all ok"
    return DimensionScore("Format Compliance", points, 20, detail)


def score_tag_precision(data: dict) -> DimensionScore:
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        return DimensionScore("Tag Precision", 0, 15, "tags not a list")

    if len(tags) == 0:
        return DimensionScore("Tag Precision", 0, 15, "no tags")

    valid_count = sum(1 for t in tags if isinstance(t, str) and t in STANDARD_TAGS)
    invalid_count = len(tags) - valid_count

    if 1 <= len(tags) <= 3 and invalid_count == 0:
        score = 15
    elif invalid_count > 0:
        score = max(0, 10 - invalid_count * 3)
    else:
        score = 10

    detail = f"{valid_count} valid, {invalid_count} invalid among {len(tags)} tags"
    return DimensionScore("Tag Precision", score, 15, detail)


def score_buzzword_detection(data: dict) -> DimensionScore:
    haystack = f"{data.get('title', '')} {data.get('summary', '')}".lower()
    found: list[str] = []
    for pat in BUZZWORD_PATTERNS:
        if pat.search(haystack):
            found.append(pat.pattern)

    score = max(0, 15 - len(found) * 5)
    for i, word in enumerate(found):
        found[i] = word.replace("\\", "")
    detail = f"{len(found)} buzzwords found: {', '.join(found)}" if found else "clean"
    return DimensionScore("Buzzword Detection", score, 15, detail)


# ── Scorers registry ────────────────────────────────────────────────────

SCORERS = [
    score_summary,
    score_technical_depth,
    score_format_compliance,
    score_tag_precision,
    score_buzzword_detection,
]


# ── Progress bar ────────────────────────────────────────────────────────

def _progress_bar(current: int, total: int, width: int = 20) -> str:
    fraction = current / total if total else 0
    filled = int(fraction * width)
    bar = "█" * filled + "─" * (width - filled)
    return f"[{bar}] {current}/{total} ({fraction * 100:.0f}%)"


# ── File processing ─────────────────────────────────────────────────────

def expand_globs(args: list[str]) -> list[Path]:
    paths: list[Path] = []
    for arg in args:
        p = Path(arg)
        if "*" in arg or "?" in arg:
            paths.extend(sorted(p.parent.glob(p.name)))
        else:
            paths.append(p)
    return paths


def analyze_file(filepath: Path) -> QualityReport | None:
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    dims = [scorer(data) for scorer in SCORERS]
    return QualityReport(filepath=filepath, dimensions=dims)


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage: python hooks/check_quality.py <json_file> [json_file2 ...]")
        sys.exit(1)

    files = expand_globs(args)
    if not files:
        print("error: No files matched the given patterns")
        sys.exit(1)

    total = len(files)
    reports: list[QualityReport] = []
    has_c = False

    for idx, fp in enumerate(files):
        bar = _progress_bar(idx + 1, total)
        sys.stdout.write(f"\rProcessing... {bar}")
        sys.stdout.flush()

        rep = analyze_file(fp)
        if rep is not None:
            reports.append(rep)

    sys.stdout.write("\n")

    for rep in reports:
        print(f"\n{rep.filepath}")
        for d in rep.dimensions:
            pct = d.score / d.max_score * 100 if d.max_score else 0
            bar = "█" * int(pct / 5) + "─" * (20 - int(pct / 5))
            print(f"  {d.name:20s} {d.score:5.1f}/{d.max_score:<3.0f} "
                  f"{bar} {d.detail}")
        print(f"  {'─' * 50}")
        print(f"  {'TOTAL':20s} {rep.total:5.1f}/{rep.max_total:<3.0f}  "
              f"Grade: {rep.grade}")
        if rep.grade == "C":
            has_c = True

    print(f"\nChecked {len(reports)} file(s)")
    sys.exit(1 if has_c else 0)


if __name__ == "__main__":
    main()
