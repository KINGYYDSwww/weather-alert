#!/usr/bin/env python3
"""地区/类型/级别规则匹配。"""
from __future__ import annotations

import re

# 依次剥离的行政区划后缀（用于把"北京市海淀区"→"北京海淀"这类归一化后做包含匹配）
_SUFFIXES = [
    "维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区",
    "自治区", "自治州", "自治县", "地区", "盟",
    "省", "市", "县", "区", "新区", "林区", "旗",
]


def normalize_name(value: str) -> str:
    """归一化地区名：去空白、循环剥离常见区划后缀。"""
    text = re.sub(r"\s+", "", value or "")
    changed = True
    while changed:
        changed = False
        for suf in _SUFFIXES:
            if text.endswith(suf) and len(text) > len(suf):
                text = text[: -len(suf)]
                changed = True
    return text


def region_matches(alert_region: str, region_cfg: dict) -> bool:
    """判断预警发布地区是否命中某条地区配置。

    规则（对归一化后的名称做"包含"匹配）：
      - 配置了 province 时，预警地区须同时包含 province 与 name；
      - 未配置 province 时，预警地区包含 name 即命中。
    例：name="海淀", province="北京" 命中"北京市海淀区"，不命中"甘肃省…"里的海淀类名称。
    """
    if not alert_region:
        return False
    a = normalize_name(alert_region)
    name = normalize_name(region_cfg.get("name", ""))
    if not name:
        return False
    if name not in a:
        return False
    prov = normalize_name(region_cfg.get("province", ""))
    if prov and prov not in a:
        return False
    return True


def type_matches(alert_type: str, allowed_types: list[str]) -> bool:
    """类型匹配：allowed 为空=全部；否则精确相等或互为包含。"""
    if not allowed_types:
        return True
    if not alert_type:
        return False
    for t in allowed_types:
        if t == alert_type or t in alert_type or alert_type in t:
            return True
    return False


def level_matches(alert_level: str, allowed_levels: list[str]) -> bool:
    """级别匹配：allowed 为空=全部；否则必须在该列表内。"""
    if not allowed_levels:
        return True
    return alert_level in allowed_levels


def match_alert(alert: dict, region_cfg: dict) -> bool:
    """一条预警是否命中某条地区配置（地区 + 类型 + 级别 三者同时满足）。"""
    return (
        region_matches(alert.get("region", ""), region_cfg)
        and type_matches(alert.get("type", ""), region_cfg.get("types", []))
        and level_matches(alert.get("level", ""), region_cfg.get("levels", []))
    )


def find_matching_regions(alert: dict, regions: list[dict]) -> list[dict]:
    """返回命中该预警的全部地区配置（可能命中多条）。"""
    return [r for r in regions if match_alert(alert, r)]
