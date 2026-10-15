#!/usr/bin/env python3
"""通知组装与运行主循环：拉取→匹配→去重→推送→解除检测。"""
from __future__ import annotations

import logging

from config import load_config, validate_config
from matcher import find_matching_regions, normalize_name
from parse import parse_alert
from push import send_all
from source import fetch_alerts, fetch_detail
from store import Store
from util import LEVEL_EMOJI, LEVEL_ORDER, now_str

log = logging.getLogger("waalert")


def fingerprint(alert: dict) -> str:
    """归一化地区 + 类型，用于识别"同一地区同类型"的升级/续报。"""
    return f"{normalize_name(alert.get('region', ''))}|{alert.get('type', '')}"


def _cut(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def build_new(alert: dict, detail: dict, kind: str, prev_level: str | None) -> dict:
    level = alert.get("level", "")
    emoji = LEVEL_EMOJI.get(level, "⚠️")

    if kind == "升级":
        title = f"{emoji}【{alert['type']}·{level}↑】{alert['region']}（原{prev_level}）"
        status = f"升级（{prev_level}→{level}）"
    elif kind == "降级":
        title = f"{emoji}【{alert['type']}·{level}↓】{alert['region']}（原{prev_level}）"
        status = f"降级（{prev_level}→{level}）"
    elif kind == "续报":
        title = f"{emoji}【{alert['type']}·{level}】{alert['region']}（续报）"
        status = "续报（同级别再次发布）"
    else:
        title = f"{emoji}【{alert['type']}·{level}】{alert['region']}"
        status = "新发布"

    lines = [
        f"气象预警 · {status}",
        "",
        f"类型：{alert.get('type', '')}",
        f"级别：{level}",
        f"地区：{alert.get('region', '')}",
        f"机构：{alert.get('agency', '')}",
        f"发布时间：{alert.get('issuetime', '')}",
    ]
    if detail.get("publish_date"):
        lines.append(f"发布日期：{detail['publish_date']}")
    if detail.get("content"):
        lines += ["", "【预警内容】", _cut(detail["content"], 600)]
    if detail.get("defense"):
        lines += ["", "【防御指南】", _cut(detail["defense"], 400)]
    lines += ["", f"来源：{detail.get('url') or alert.get('url', '')}"]

    body_text = "\n".join(lines)

    sc_desp_lines = [
        f"## {status}",
        f"- 类型：**{alert.get('type', '')}**",
        f"- 级别：**{level}**",
        f"- 地区：{alert.get('region', '')}",
        f"- 机构：{alert.get('agency', '')}",
        f"- 发布时间：{alert.get('issuetime', '')}",
    ]
    if detail.get("content"):
        sc_desp_lines += ["", "**预警内容**", _cut(detail["content"], 600)]
    if detail.get("defense"):
        sc_desp_lines += ["", "**防御指南**", _cut(detail["defense"], 400)]
    sc_desp_lines += ["", f"[查看原文]({detail.get('url') or alert.get('url', '')})"]
    sc_desp = "\n".join(sc_desp_lines)

    return {
        "title": title,
        "body_text": body_text,
        "bark_body": body_text,
        "sc_desp": sc_desp,
        "url": detail.get("url") or alert.get("url", ""),
        "level": level,
    }


def build_cancel(row) -> dict:
    emoji = "⚪"
    title = f"{emoji}【{row['type']}·已解除】{row['region']}"
    lines = [
        "气象预警 · 解除/到期",
        "",
        f"类型：{row['type']}",
        f"原级别：{row['level']}",
        f"地区：{row['region']}",
        f"机构：{row['agency']}",
        f"发布时间：{row['issuetime']}",
        "",
        "该预警已不再处于生效列表，可能已解除或到期。",
        "",
        f"来源：{row['url']}",
    ]
    body_text = "\n".join(lines)
    sc_desp = "\n".join([
        "## 解除/到期",
        f"- 类型：**{row['type']}**",
        f"- 原级别：**{row['level']}**",
        f"- 地区：{row['region']}",
        "",
        "该预警已不再处于生效列表，可能已解除或到期。",
        "",
        f"[查看原文]({row['url']})",
    ])
    return {
        "title": title,
        "body_text": body_text,
        "bark_body": body_text,
        "sc_desp": sc_desp,
        "url": row["url"],
        "level": row["level"],
    }


def run_once(cfg: dict, store: Store, dry_run: bool = False) -> dict:
    """执行一轮监测。返回统计结果。"""
    poll = cfg.get("poll", {})
    regions = cfg.get("regions", [])
    push_cfg = cfg.get("push", {})
    fetch_detail_flag = bool(poll.get("fetch_detail", True))
    notify_renewal = bool(poll.get("notify_renewal", False))
    notify_cancel = bool(poll.get("notify_cancel", True))

    result = {
        "fetched": 0,
        "parsed": 0,
        "matched": 0,
        "pushed": [],
        "cancelled": [],
    }

    raw = fetch_alerts(poll.get("alert_page_size", 500))
    result["fetched"] = len(raw)

    alerts = [parse_alert(a) for a in raw]
    parsed = [a for a in alerts if a["parsed"]]
    result["parsed"] = len(parsed)

    matched = []
    for a in parsed:
        rs = find_matching_regions(a, regions)
        if rs:
            a["fingerprint"] = fingerprint(a)
            matched.append(a)
    # 按发布时间升序处理：确保同一地区同类型出现多条时，
    # 以更早的那条为基准判断级别变化（否则可能把"升级"误判为"降级"）。
    matched.sort(key=lambda x: x.get("issuetime", ""))
    result["matched"] = len(matched)

    current_ids = {a["alertid"] for a in matched}
    current_fps = {a["fingerprint"] for a in matched}

    # 处理新发布 / 升级 / 降级 / 续报
    for a in matched:
        if store.is_pushed(a["alertid"]):
            store.upsert_seen(a)
            continue

        prev = store.last_pushed_for_fingerprint(a["fingerprint"])
        if prev is None:
            kind = "新发布"
        else:
            old, new = LEVEL_ORDER.get(prev["level"], 0), LEVEL_ORDER.get(a["level"], 0)
            kind = "升级" if new > old else ("降级" if new < old else "续报")

        store.upsert_seen(a)

        if kind == "续报" and not notify_renewal:
            # 不推送续报，但标记已处理，避免后续反复判断
            store.mark_pushed(a["alertid"], "续报")
            log.info("续报（不推送，因 notify_renewal=false）：%s", a["title"])
            continue

        detail = {}
        if fetch_detail_flag:
            try:
                detail = fetch_detail(a["url"])
            except Exception as exc:
                log.warning("详情获取失败 %s：%s", a["alertid"], exc)

        notif = build_new(a, detail, kind, prev["level"] if prev else None)

        if dry_run:
            result["pushed"].append({"kind": kind, "title": notif["title"]})
            log.info("[dry-run] 将推送（%s）：%s", kind, notif["title"])
        else:
            sent = send_all(
                push_cfg, notif["title"], notif["body_text"],
                notif["bark_body"], notif["sc_desp"], notif["url"], notif["level"],
            )
            result["pushed"].append({"kind": kind, "title": notif["title"], "channels": sent})
            if sent:
                store.mark_pushed(a["alertid"], kind)
            else:
                log.error("所有渠道推送失败，下一轮将重试：%s", notif["title"])

    # 处理解除/到期（已推送过、本轮不在生效列表、且无同指纹新预警顶替）
    if notify_cancel:
        for aid in store.active_alertids():
            if aid in current_ids:
                continue
            row = store.get(aid)
            if row is None:
                continue
            if row["fingerprint"] in current_fps:
                # 被同地区同类型的新预警顶替（升级/续报），不算解除
                store.mark_gone(aid)
                continue
            if not row["pushed"]:
                store.mark_gone(aid)
                continue
            notif = build_cancel(row)
            if dry_run:
                result["cancelled"].append(notif["title"])
                log.info("[dry-run] 将推送解除：%s", notif["title"])
            else:
                sent = send_all(
                    push_cfg, notif["title"], notif["body_text"],
                    notif["bark_body"], notif["sc_desp"], notif["url"], notif["level"],
                )
                result["cancelled"].append({"title": notif["title"], "channels": sent})
                if sent:
                    log.info("已推送解除通知：%s", notif["title"])
            store.mark_gone(aid)

    store.set_meta("last_run_at", now_str())
    return result


def summarize(result: dict) -> str:
    return (
        f"抓取 {result['fetched']} 条，解析 {result['parsed']} 条，"
        f"命中关注规则 {result['matched']} 条，推送 {len(result['pushed'])} 条，"
        f"解除 {len(result['cancelled'])} 条"
    )


def send_system_notice(cfg: dict, kind: str, message: str = "") -> bool:
    """发送系统级通知：监测异常 / 已恢复。返回是否成功发送到至少一个渠道。"""
    push_cfg = cfg.get("push", {})
    if kind == "fault":
        title = "⚠️ 天气预警监测异常"
        body = (
            "监测程序运行出错，可能无法及时获取最新预警。\n\n"
            f"错误：{_cut(message, 400)}\n\n"
            "请检查网络连接，或查看日志 logs/alerts.log。"
        )
    elif kind == "recover":
        title = "✅ 天气预警监测已恢复"
        body = "监测程序已恢复正常运行，将继续推送新预警。"
    else:
        return False
    return bool(send_all(push_cfg, title, body, body, body, "", ""))
