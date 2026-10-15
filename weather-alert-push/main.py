#!/usr/bin/env python3
"""指定地区天气预警主动推送工具 —— 入口。

用法：
  python main.py                  # 运行一轮监测（供计划任务调用）
  python main.py --loop           # 常驻运行，按配置间隔循环
  python main.py --dry-run        # 干跑：只展示将推送什么，不实际发送、不写状态
  python main.py --status         # 查看配置与当前关注地区命中的现行预警
  python main.py --list-provinces # 列出省级名称（帮助填写 province）
  python main.py --config PATH    # 指定配置文件
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from config import load_config, validate_config
from matcher import find_matching_regions, normalize_name
from notify import run_once, send_system_notice, summarize
from parse import parse_alert
from source import fetch_alerts, fetch_provinces
from store import Store
from util import project_dir, setup_logging


def _make_store(cfg: dict, dry_run: bool = False) -> Store:
    if dry_run:
        return Store(":memory:")
    db = Path(project_dir()) / "state.db"
    return Store(str(db))


def _run_cycle(cfg: dict, store: Store, dry_run: bool, log):
    """运行一轮监测，并在失败/恢复时主动通知（需求五.7）。返回 (result, error)。"""
    try:
        result = run_once(cfg, store, dry_run=dry_run)
        if not dry_run and store.get_meta("fault") == "1":
            store.set_meta("fault", "0")
            log.info("本轮恢复正常。")
            try:
                send_system_notice(cfg, "recover")
            except Exception as exc:
                log.error("恢复通知发送失败：%s", exc)
        return result, None
    except Exception as exc:
        log.exception("运行出错：%s", exc)
        if not dry_run:
            if store.get_meta("fault") != "1":
                # 首次故障：记录并尝试通过可用渠道提醒
                store.set_meta("fault", "1")
                try:
                    send_system_notice(cfg, "fault", str(exc))
                except Exception as e2:
                    log.error("故障通知发送失败：%s", e2)
        return None, exc


def cmd_once(cfg: dict, dry_run: bool) -> int:
    log = setup_logging(cfg["log"]["dir"], cfg["log"]["level"])
    problems = validate_config(cfg)
    if problems and not dry_run:
        for p in problems:
            log.warning("配置问题：%s", p)

    store = _make_store(cfg, dry_run)
    rc = 0
    try:
        result, err = _run_cycle(cfg, store, dry_run, log)
        if err is not None:
            rc = 2
        else:
            log.info("本轮完成：%s", summarize(result))
            for item in result["pushed"]:
                log.info("  · 推送：%s", item.get("title"))
            for item in result["cancelled"]:
                log.info("  · 解除：%s", item.get("title"))
    finally:
        store.close()
    return rc


def cmd_loop(cfg: dict) -> int:
    log = setup_logging(cfg["log"]["dir"], cfg["log"]["level"])
    interval = int(cfg.get("poll", {}).get("interval_minutes", 10) or 10)
    interval = max(interval, 1)
    log.info("开始常驻运行，每 %d 分钟监测一次。按 Ctrl+C 退出。", interval)

    store = _make_store(cfg)
    try:
        while True:
            result, err = _run_cycle(cfg, store, False, log)
            if err is None:
                log.info("本轮完成：%s", summarize(result))
            try:
                time.sleep(interval * 60)
            except KeyboardInterrupt:
                log.info("收到退出信号，停止运行。")
                break
    finally:
        store.close()
    return 0


def cmd_status(cfg: dict) -> int:
    log = setup_logging(cfg["log"]["dir"], cfg["log"]["level"])
    regions = cfg.get("regions", [])
    print("=" * 60)
    print("已配置的关注地区：")
    for i, r in enumerate(regions, 1):
        prov = f"（省：{r['province']}）" if r.get("province") else ""
        types = "、".join(r["types"]) if r["types"] else "全部"
        levels = "、".join(r["levels"]) if r["levels"] else "全部"
        print(f"  {i}. {r['name']}{prov}  类型[{types}] 级别[{levels}]")

    print("-" * 60)
    print("正在拉取全国现行预警并与配置匹配…")
    try:
        raw = fetch_alerts(cfg.get("poll", {}).get("alert_page_size", 500))
        alerts = [parse_alert(a) for a in raw if parse_alert(a)["parsed"]]
    except Exception as exc:
        print(f"[错误] 拉取预警失败：{exc}")
        return 2

    print(f"当前全国现行预警 {len(raw)} 条，成功解析 {len(alerts)} 条。")
    print("各关注地区当前命中的预警：")
    for r in regions:
        hits = [a for a in alerts if find_matching_regions(a, [r])]
        print(f"  · {r['name']}：命中 {len(hits)} 条")
        for a in hits[:20]:
            print(f"      - [{a['level']}] {a['type']} {a['region']}（{a['issuetime']}）")
    return 0


def cmd_list_provinces() -> int:
    try:
        provs = fetch_provinces()
    except Exception as exc:
        print(f"[错误] 拉取省份失败：{exc}")
        return 2
    print("省级行政区列表（province 字段可填这些名称）：")
    for p in provs:
        print(f"  {p.get('code')}  {p.get('name')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 保证 Windows 控制台输出中文不乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="指定地区天气预警主动推送工具")
    parser.add_argument("--config", help="配置文件路径（默认项目目录下 config.json）")
    parser.add_argument("--loop", action="store_true", help="常驻循环运行")
    parser.add_argument("--dry-run", action="store_true", help="干跑：只展示，不推送、不写状态")
    parser.add_argument("--status", action="store_true", help="查看配置与命中情况")
    parser.add_argument("--list-provinces", action="store_true", help="列出省级名称")
    args = parser.parse_args(argv)

    if args.list_provinces:
        return cmd_list_provinces()

    cfg = load_config(args.config)

    if args.status:
        return cmd_status(cfg)
    if args.loop:
        return cmd_loop(cfg)
    return cmd_once(cfg, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
