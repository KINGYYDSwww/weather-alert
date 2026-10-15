#!/usr/bin/env python3
"""公共工具：网络请求、日志、常量、时间处理。仅使用 Python 标准库。"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError

# ---- 常量 ----
BASE_URL = "https://www.nmc.cn"
CN_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://www.nmc.cn/",
}

# 预警级别由低到高（数值越大越严重）
LEVEL_ORDER = {"蓝色": 1, "黄色": 2, "橙色": 3, "红色": 4}
LEVEL_EMOJI = {"蓝色": "🔵", "黄色": "🟡", "橙色": "🟠", "红色": "🔴"}

# 常见预警类型（用于默认配置与展示；用户可在 config.json 自行增删）
DEFAULT_TYPES = [
    "台风", "暴雨", "暴雪", "寒潮", "大风", "雷电", "冰雹",
    "强对流", "雷雨大风", "大雾", "道路结冰", "高温",
    "沙尘暴", "霜冻", "海上大风", "海上雷雨大风",
    "地质灾害", "山洪", "渍涝", "中小河流洪水",
]

# 证书校验失败时的回退上下文（某些企业/代理环境会做 TLS 拦截，导致默认校验失败）
_UNVERIFIED_CTX = ssl._create_unverified_context()
_SSL_WARNED = False


def project_dir() -> Path:
    """返回项目根目录（本文件所在目录）。"""
    return Path(__file__).resolve().parent


def _open_url(req: urllib.request.Request, timeout: int):
    """打开 URL；默认校验证书，校验失败时（如代理拦截环境）回退为不校验。

    说明：本项目只读取公开的天气预警数据（不涉及登录、不涉及敏感信息），
    因此在自建/企业代理导致证书链校验失败的场景下回退到不校验以保证可用，
    并仅在日志中记录一次提示。
    """
    global _SSL_WARNED
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as exc:
        # urlopen 会把证书校验失败包装成 URLError，其 reason 才是 SSLCertVerificationError
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            if not _SSL_WARNED:
                logging.getLogger("waalert").warning(
                    "HTTPS 证书校验失败（本机可能存在 TLS 拦截代理）。"
                    "已回退为不校验证书方式读取公开气象数据。"
                )
                _SSL_WARNED = True
            return urllib.request.urlopen(req, timeout=timeout, context=_UNVERIFIED_CTX)
        raise


def http_get_json(path_or_url: str, timeout: int = 25):
    """GET 并解析 JSON，带 3 次重试。path_or_url 为相对路径时拼到中央气象台域名。"""
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with _open_url(req, timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                return json.loads(text)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last_err}")


def http_get_text(path_or_url: str, timeout: int = 25) -> str:
    """GET 并返回文本，带 3 次重试。"""
    url = path_or_url if path_or_url.startswith("http") else BASE_URL + path_or_url
    last_err: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with _open_url(req, timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last_err}")


def http_post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    """POST JSON 并解析响应（用于推送接口）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={**HEADERS, "Content-Type": "application/json;charset=utf-8"},
        method="POST",
    )
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with _open_url(req, timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"raw": text}
        except urllib.error.HTTPError as exc:
            # 尝试读取服务端返回的错误详情（如"device key 无效"）
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            last_err = RuntimeError(f"HTTP {exc.code}: {detail[:300]}" if detail else f"HTTP {exc.code}")
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        except (URLError, TimeoutError) as exc:
            last_err = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"推送请求失败 {url}: {last_err}")


def now_cn() -> datetime:
    return datetime.now(timezone.utc).astimezone(CN_TZ)


def now_str() -> str:
    return now_cn().strftime("%Y-%m-%d %H:%M:%S")


def parse_issue_time(value: str | None) -> datetime | None:
    """解析中央气象台 issuetime，如 '2026/10/15 22:11'。"""
    if not value:
        return None
    v = str(value).strip()
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=CN_TZ)
        except ValueError:
            continue
    return None


def setup_logging(log_dir: str, level: str = "INFO") -> logging.Logger:
    """初始化日志：控制台 + 文件（滚动）。返回 'waalert' logger。"""
    logger = logging.getLogger("waalert")
    if logger.handlers:  # 避免重复初始化
        return logger

    # 保证控制台输出中文不乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        d = Path(log_dir)
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            d / "alerts.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception as exc:  # 日志目录不可写时不影响运行
        print(f"[warn] 无法创建日志文件 {log_dir}: {exc}")

    return logger
