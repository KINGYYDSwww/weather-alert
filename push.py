#!/usr/bin/env python3
"""推送渠道：Bark（iPhone 锁屏）、Server酱（微信）、邮件。"""
from __future__ import annotations

import logging
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from util import http_post_json

log = logging.getLogger("waalert")

# Bark 的 level 取值（决定是否点亮屏幕/穿透专注模式）。
# active=点亮屏幕即时显示；timeSensitive=时效性通知，可穿透专注模式（无需额外授权）。
# 如需红色预警在"勿扰模式"下也响铃，可把红色改为 "critical"（需在 iOS 设置→通知→Bark 开启"重要警告"）。
BARK_LEVEL = {"蓝色": "active", "黄色": "active", "橙色": "timeSensitive", "红色": "timeSensitive"}


def push_bark(bark_cfg: dict, title: str, body: str, url: str = "", level: str = "") -> tuple[bool, str]:
    """通过 Bark 推送到 iPhone（APNs）。成功返回 (True, '')，失败返回 (False, 错误)。"""
    key = (bark_cfg.get("key") or "").strip()
    server = (bark_cfg.get("server") or "https://api.day.app").rstrip("/")
    if not key:
        return False, "Bark key 为空"
    payload = {
        "device_key": key,
        "title": title,
        "body": body,
        "group": "天气预警",
    }
    if url:
        payload["url"] = url
    if level and level in BARK_LEVEL:
        payload["level"] = BARK_LEVEL[level]
    try:
        resp = http_post_json(f"{server}/push", payload)
        # Bark 成功时返回 {"code":200,...}
        if isinstance(resp, dict) and resp.get("code") in (200, 0, "200"):
            return True, ""
        return False, f"响应异常: {resp}"
    except Exception as exc:
        return False, str(exc)


def push_serverchan(sc_cfg: dict, title: str, desp: str) -> tuple[bool, str]:
    """通过 Server酱 推送（微信/App）。SendKey 前缀决定端点。"""
    sendkey = (sc_cfg.get("sendkey") or "").strip()
    if not sendkey:
        return False, "Server酱 sendkey 为空"

    if sendkey.startswith("sctp"):
        # Server酱³：sctp<num>t<token> -> https://<num>.push.ft07.com/send/<key>.send
        m = __import__("re").match(r"^sctp(\d+)t", sendkey)
        if not m:
            return False, "Server酱³ SendKey 格式不正确"
        url = f"https://{m.group(1)}.push.ft07.com/send/{sendkey}.send"
    else:
        # Server酱 Turbo
        url = f"https://sctapi.ftqq.com/{sendkey}.send"

    try:
        resp = http_post_json(url, {"title": title, "desp": desp})
        if isinstance(resp, dict) and resp.get("code") == 0:
            return True, ""
        return False, f"响应异常: {resp}"
    except Exception as exc:
        return False, str(exc)


def push_email(email_cfg: dict, subject: str, body: str) -> tuple[bool, str]:
    """通过 SMTP 发送邮件。body 为纯文本。"""
    host = email_cfg.get("smtp_host")
    port = int(email_cfg.get("smtp_port", 465))
    user = email_cfg.get("username")
    password = email_cfg.get("password")
    to_list = email_cfg.get("to") or []
    if not (host and user and password and to_list):
        return False, "邮件配置不完整"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(user, "utf-8")), user))
    msg["To"] = ", ".join(to_list)

    try:
        if email_cfg.get("use_ssl"):
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        server.login(user, password)
        server.sendmail(user, to_list, msg.as_string())
        server.quit()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def send_all(push_cfg: dict, title: str, body_text: str, bark_body: str,
             sc_desp: str, url: str, level: str) -> list[str]:
    """向所有已启用的渠道推送。返回本次成功渠道列表（用于日志）。"""
    sent: list[str] = []

    if push_cfg.get("bark", {}).get("enabled"):
        ok, err = push_bark(push_cfg["bark"], title, bark_body, url, level)
        if ok:
            sent.append("bark")
            log.info("已通过 Bark 推送：%s", title)
        else:
            log.error("Bark 推送失败：%s", err)

    if push_cfg.get("serverchan", {}).get("enabled"):
        ok, err = push_serverchan(push_cfg["serverchan"], title, sc_desp)
        if ok:
            sent.append("serverchan")
            log.info("已通过 Server酱 推送：%s", title)
        else:
            log.error("Server酱 推送失败：%s", err)

    if push_cfg.get("email", {}).get("enabled"):
        ok, err = push_email(push_cfg["email"], title, body_text)
        if ok:
            sent.append("email")
            log.info("已通过邮件推送：%s", title)
        else:
            log.error("邮件推送失败：%s", err)

    return sent
