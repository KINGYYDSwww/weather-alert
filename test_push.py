#!/usr/bin/env python3
"""推送自检：向所有已启用的渠道发送一条测试消息，用于验证密钥/通道是否配置正确。"""
from __future__ import annotations

import argparse
import sys

from config import load_config, validate_config
from push import push_bark, push_serverchan, push_email
from util import setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="推送自检")
    parser.add_argument("--config", help="配置文件路径")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg["log"]["dir"], cfg["log"]["level"])

    problems = validate_config(cfg)
    if problems:
        for p in problems:
            print(f"[配置问题] {p}")

    push_cfg = cfg.get("push", {})
    title = "天气预警推送自检"
    body = "这是一条测试消息。如果你收到它，说明推送通道配置成功。\n\n—— 天气预警主动推送工具"

    print("=" * 60)
    print("推送自检开始…")

    any_enabled = False
    if push_cfg.get("bark", {}).get("enabled"):
        any_enabled = True
        ok, err = push_bark(push_cfg["bark"], title, body)
        print(f"  [Bark]      {'✅ 成功' if ok else '❌ 失败：' + err}")
    if push_cfg.get("serverchan", {}).get("enabled"):
        any_enabled = True
        ok, err = push_serverchan(push_cfg["serverchan"], title, body)
        print(f"  [Server酱]  {'✅ 成功' if ok else '❌ 失败：' + err}")
    if push_cfg.get("email", {}).get("enabled"):
        any_enabled = True
        ok, err = push_email(push_cfg["email"], title, body)
        print(f"  [邮件]      {'✅ 成功' if ok else '❌ 失败：' + err}")

    if not any_enabled:
        print("  没有启用任何推送渠道。请编辑 config.json 启用至少一个渠道。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
