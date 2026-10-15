#!/usr/bin/env python3
"""配置加载与校验。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from util import DEFAULT_TYPES


def _default_config() -> dict:
    return {
        "poll": {
            "interval_minutes": 10,
            "alert_page_size": 500,
            "fetch_detail": True,       # 是否抓取详情页正文（预警内容/防御指南）
            "notify_cancel": True,      # 预警从生效列表消失时，推送"解除/到期"
            "notify_renewal": False,    # 同地区同类型同级别再次发布（续报）是否推送
        },
        "regions": [
            {
                "name": "北京",          # 关注地区名，尽量写全（省/市/区县均可）
                "province": "北京",      # 可选：用于重名消歧（如"朝阳"需区分北京朝阳区/辽宁朝阳市）
                "types": DEFAULT_TYPES,  # 关注的预警类型；[] 或省略 = 全部
                "levels": ["橙色", "红色"],  # 关注的级别；[] 或省略 = 全部（蓝/黄/橙/红）
            }
        ],
        "push": {
            "bark": {                    # 主渠道：iPhone 锁屏推送（免费 App：Bark）
                "enabled": False,
                "server": "https://api.day.app",
                "key": "",               # Bark App 里显示的 key，形如 xxxxxxxx
            },
            "serverchan": {              # 备用渠道：微信推送（Server酱）
                "enabled": False,
                "sendkey": "",           # https://sct.ftqq.com 的 SendKey（SCT...）
            },
            "email": {                   # 备用渠道：邮件
                "enabled": False,
                "smtp_host": "smtp.qq.com",
                "smtp_port": 465,
                "use_ssl": True,
                "username": "",
                "password": "",          # QQ 邮箱用"授权码"，不是登录密码
                "to": [],                # 收件人列表，如 ["me@qq.com"]
            },
        },
        "log": {
            "dir": "logs",
            "level": "INFO",
        },
    }


def load_config(path: str | None = None) -> dict:
    """加载配置；文件不存在时生成默认配置并返回。"""
    p = Path(path) if path else (Path(__file__).resolve().parent / "config.json")
    if not p.exists():
        cfg = _default_config()
        p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg
    cfg = json.loads(p.read_text(encoding="utf-8"))

    # 填充缺省字段
    base = _default_config()
    cfg = _deep_merge(base, cfg)

    # 规范化 regions
    cfg["regions"] = [normalize_region(r) for r in cfg.get("regions", []) if r.get("name")]

    # 用环境变量覆盖敏感配置（便于云端/CI 通过 Secret 注入，密钥无需写入代码库）
    apply_env_overrides(cfg)
    return cfg


def apply_env_overrides(cfg: dict) -> dict:
    """从环境变量覆盖推送密钥等敏感项。

    支持：WA_BARK_KEY / WA_BARK_SERVER / WA_SERVERCHAN_SENDKEY /
          WA_EMAIL_USERNAME / WA_EMAIL_PASSWORD / WA_EMAIL_TO
    """
    push = cfg.setdefault("push", {})

    bark = push.setdefault("bark", {})
    if os.environ.get("WA_BARK_KEY"):
        bark["key"] = os.environ["WA_BARK_KEY"].strip()
        bark["enabled"] = True
    if os.environ.get("WA_BARK_SERVER"):
        bark["server"] = os.environ["WA_BARK_SERVER"].strip()

    sc = push.setdefault("serverchan", {})
    if os.environ.get("WA_SERVERCHAN_SENDKEY"):
        sc["sendkey"] = os.environ["WA_SERVERCHAN_SENDKEY"].strip()
        sc["enabled"] = True

    em = push.setdefault("email", {})
    if os.environ.get("WA_EMAIL_USERNAME"):
        em["username"] = os.environ["WA_EMAIL_USERNAME"].strip()
    if os.environ.get("WA_EMAIL_PASSWORD"):
        em["password"] = os.environ["WA_EMAIL_PASSWORD"].strip()
        em["enabled"] = True
    if os.environ.get("WA_EMAIL_TO"):
        em["to"] = [x.strip() for x in os.environ["WA_EMAIL_TO"].split(",") if x.strip()]

    return cfg


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def normalize_region(r: dict) -> dict:
    return {
        "name": str(r.get("name", "")).strip(),
        "province": str(r.get("province", "") or "").strip(),
        "types": [str(t).strip() for t in (r.get("types") or []) if str(t).strip()],
        "levels": [str(l).strip() for l in (r.get("levels") or []) if str(l).strip()],
    }


def validate_config(cfg: dict) -> list[str]:
    """返回问题列表（空表示配置可用）。"""
    problems = []
    if not cfg.get("regions"):
        problems.append("regions 为空：请在 config.json 中至少添加一个关注地区。")

    enabled = []
    for ch in ("bark", "serverchan", "email"):
        ch_cfg = cfg.get("push", {}).get(ch, {})
        if ch_cfg.get("enabled"):
            enabled.append(ch)
    if not enabled:
        problems.append(
            "所有推送渠道均未启用（push.bark.enabled / serverchan.enabled / email.enabled）。"
            "系统仍会正常监测并记录，但不会推送；请至少启用一个渠道并填入密钥。"
        )
    if cfg.get("push", {}).get("bark", {}).get("enabled") and not cfg.get("push", {}).get("bark", {}).get("key"):
        problems.append("Bark 已启用但未填 key。")
    if cfg.get("push", {}).get("serverchan", {}).get("enabled") and not cfg.get("push", {}).get("serverchan", {}).get("sendkey"):
        problems.append("Server酱 已启用但未填 sendkey。")
    if cfg.get("push", {}).get("email", {}).get("enabled"):
        e = cfg["push"]["email"]
        if not e.get("username") or not e.get("password") or not e.get("to"):
            problems.append("邮件推送已启用但 username/password/to 不完整。")
    return problems
