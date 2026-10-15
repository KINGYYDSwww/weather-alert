#!/usr/bin/env python3
"""解析预警标题：提取发布地区、发布机构、动作、类型、级别。"""
from __future__ import annotations

import re

# 标题形如：
#   "海南省文昌市气象台发布雷电黄色预警信号"
#   "湖南省益阳市沅江市气象台发布暴雨黄色预警信号"
#   "辽宁省气象台发布其它气象灾害黄色预警"        <- 无"信号"后缀
#   "海南省气象台发布海上雷雨大风黄色预警信号"     <- 类型含"海上"
#   （解除/继续发布/升级等形态按动词捕获，兼容未来变化）
_TITLE_RE = re.compile(
    r"^(?P<region>.+?)气象台"
    r"(?P<verb>解除|继续发布|升级发布|降级发布|变更发布|发布)"
    r"(?P<type>.+?)"
    r"(?P<level>蓝色|黄色|橙色|红色)"
    r"预警(?:信号)?$"
)


def parse_title(title: str) -> dict | None:
    """解析预警标题，返回结构化字段；无法识别时返回 None。"""
    if not title:
        return None
    m = _TITLE_RE.match(str(title).strip())
    if not m:
        return None
    return {
        "region": m.group("region").strip(),      # 发布地区（完整路径，如"海南省文昌市"）
        "agency": (m.group("region").strip() + "气象台"),  # 发布机构
        "verb": m.group("verb"),                  # 发布/解除/继续发布/升级发布/…
        "type": m.group("type").strip(),          # 预警类型，如"暴雨"
        "level": m.group("level"),                # 蓝色/黄色/橙色/红色
    }


def parse_alert(alert: dict) -> dict:
    """把接口返回的原始 alert 记录解析为统一结构。"""
    title = alert.get("title", "")
    parsed = parse_title(title)
    return {
        "alertid": str(alert.get("alertid", "")),
        "title": title,
        "issuetime": alert.get("issuetime", ""),
        "url": alert.get("url", ""),
        "pic": alert.get("pic", ""),
        "region": (parsed or {}).get("region", ""),
        "agency": (parsed or {}).get("agency", ""),
        "verb": (parsed or {}).get("verb", "发布"),
        "type": (parsed or {}).get("type", ""),
        "level": (parsed or {}).get("level", ""),
        "parsed": parsed is not None,
    }
