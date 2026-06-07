"""GitHub API 工具模块，提供仓库信息查询功能。"""

import os
from dataclasses import dataclass
from typing import Optional

import requests
from loguru import logger


@dataclass
class RepoInfo:
    """GitHub 仓库基本信息。"""

    stars: int
    forks: int
    description: Optional[str]
    full_name: str
    language: Optional[str]


def fetch_repo_info(repo_full_name: str, token: Optional[str] = None) -> RepoInfo:
    """从 GitHub API 获取指定仓库的基本信息。

    Args:
        repo_full_name: 仓库全名，格式为 "owner/repo"，
            例如 "tensorflow/tensorflow"。
        token: GitHub Personal Access Token，可选。
            提供后可提高 API 速率限制（从 60 次/小时到 5000 次/小时）。

    Returns:
        RepoInfo: 包含仓库基本信息的 dataclass。

    Raises:
        requests.HTTPError: API 请求失败时抛出。
        ValueError: repo_full_name 格式不正确时抛出。
    """
    if "/" not in repo_full_name or repo_full_name.count("/") != 1:
        raise ValueError(f"仓库全名格式必须为 'owner/repo'，收到: {repo_full_name}")

    url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {"Accept": "application/vnd.github+json"}

    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif github_token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {github_token}"

    logger.info(f"正在请求仓库信息: {repo_full_name}")
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    repo_info = RepoInfo(
        stars=data["stargazers_count"],
        forks=data["forks_count"],
        description=data.get("description"),
        full_name=data["full_name"],
        language=data.get("language"),
    )

    logger.info(
        f"获取成功: {repo_info.full_name} — "
        f"⭐ {repo_info.stars} / 🍴 {repo_info.forks}"
    )
    return repo_info
