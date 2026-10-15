#!/usr/bin/env python3
"""数据采集：中央气象台公开预警接口 + 详情页 + 省份/城市解析。"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlencode

from util import BASE_URL, http_get_json, http_get_text


def fetch_alerts(page_size: int = 500) -> list[dict]:
    """拉取全国现行预警信号列表（一次取全量）。

    接口：GET /rest/findAlarm?pageNo=1&pageSize=N&signaltype=&signallevel=&province=
    返回 data.page.list[]，每条含 alertid / issuetime / title / url / pic。
    """
    query = urlencode({
        "pageNo": 1,
        "pageSize": int(page_size or 500),
        "signaltype": "",
        "signallevel": "",
        "province": "",
    })
    payload = http_get_json(f"/rest/findAlarm?{query}")
    data = payload.get("data") or {}
    page = data.get("page") or {}
    return page.get("list") or []


class _TextExtractor(HTMLParser):
    """把 HTML 剥成纯文本行（用于提取详情页正文）。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("div", "p", "br", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


# 详情页页脚及导航等非预警正文内容，用于截断"防御指南"
_FOOTER_MARKERS = [
    "推荐服务", "妈祖", "早期预警", "世界气象中心", "台风网", "气象期刊",
    "航空气象", "沙尘网", "科技合作", "关于我们", "联系方式", "网站声明",
    "网站地图", "网站动态", "触摸屏版", "国家气象中心", "版权所有", "制作维护",
    "京公网安备", "京ICP", "技术支持", "商务合作", "新浪微博", "微信公众号",
    "中央气象台", "科技创新", "抖音号", "业务信息",
]


def _strip_tags(text: str) -> list[str]:
    p = _TextExtractor()
    p.feed(text)
    raw = "".join(p.parts)
    raw = html.unescape(raw).replace("\xa0", " ")
    raw = re.sub(r"[ \t\r]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return [ln.strip() for ln in raw.split("\n") if ln.strip()]


def _is_footer_line(line: str) -> bool:
    return any(mk in line for mk in _FOOTER_MARKERS)


def fetch_detail(url_path: str) -> dict:
    """抓取单条预警详情页，提取发布日期、正文、防御指南。"""
    url = url_path if url_path.startswith("http") else BASE_URL + url_path
    text = http_get_text(url)
    lines = _strip_tags(text)

    publish_date = ""
    content = ""
    defense = ""
    title = ""
    # 标题行：包含"气象台"且含"预警"
    for ln in lines:
        if "气象台" in ln and "预警" in ln and not title:
            title = ln
            break

    for i, ln in enumerate(lines):
        if ln.startswith("发布日期"):
            publish_date = ln.replace("发布日期：", "").replace("发布日期:", "").strip()
        # 正文行：通常是"XX气象台…发布…预警信号：…"的长句
        if ("预警信号" in ln or "预警" in ln) and "气象台" in ln and len(ln) > 30:
            if not content:
                content = ln
        if ln.startswith("防御指南"):
            # 从"防御指南"起，截取到页脚之前
            seg = []
            for ln2 in lines[i:]:
                if _is_footer_line(ln2):
                    break
                seg.append(ln2)
            defense = "\n".join(seg)

    if not content:
        # 退而求其次：把"防御指南"之前、标题/发布日期之后的较长行当作正文
        for ln in lines:
            if ("预警" in ln) and len(ln) > 20 and ln != title and not ln.startswith("发布日期"):
                content = ln
                break

    return {
        "title": title,
        "publish_date": publish_date,
        "content": content,
        "defense": defense,
        "url": url,
    }


def fetch_provinces() -> list[dict]:
    """省级列表（用于帮助用户选择省份名称）。"""
    return http_get_json("/rest/province/all")


def fetch_cities(province_code: str) -> list[dict]:
    """某省的城市/站点列表。"""
    return http_get_json(f"/rest/province/{province_code}")
