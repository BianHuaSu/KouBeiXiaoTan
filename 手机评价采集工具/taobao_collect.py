#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""淘宝外卖评价现场采集（截图 OCR 兜底）。

淘宝的评价页是自绘/WebView 容器，无障碍和 uiautomator 都拿不到文字节点，
所以这个采集器在淘宝页面上改用「滚动 + 截图 + OCR」，仍然是在手机上现场读，
不是预先分析好的数据。其他 App（美团/大众点评/京东）继续走无障碍服务。

用法：
  python taobao_collect.py --max-seconds 20
  python taobao_collect.py --serial SGNJVWXODI794PKN --max-seconds 30
"""

import argparse
import re
import sys
import time
from pathlib import Path

from adb_collect import Adb, InputPermissionError, find_adb, log
from common import clean_line, chinese_len, make_out_dir, write_outputs
from ocr_core import ocr_image
from uiauto_core import merge_ui_rows

# 这些是评价列表的界面文字，不进入正文
UI_EXACT = {
    "满意度", "TA的点赞:", "TA的点赞", "有用", "展开", "商家回复", "优质",
    "点餐", "商家", "明厨亮灶", "好友拼单", "商品优惠", "外送", "自取",
    "全部", "最新", "有图/视频", "近期差评", "匿名用户", "回头客",
}
UI_PREFIX = ("TA的点赞", "商家回复", "【", "（", "(", "分享", "点赞", "评价",
             "有图", "全部", "最新", "近期", "好评", "差评", "加载更多")
UI_STRONG = ("已连接", "USB调试", "点按即可关闭", "KB/s")
UI_RATING = re.compile(r"(?:味道|包装|商品|服务)?\s*\d(?:\.\d)?\s*星")


def _is_ui(text):
    """判断界面行；不把「好吃」「包装干净」这种正文误判成界面。"""
    t = clean_line(text)
    if not t:
        return True
    if t in UI_EXACT:
        return True
    if any(t.startswith(p) for p in UI_PREFIX):
        return True
    if any(p in t for p in UI_STRONG):
        return True
    if UI_RATING.search(t):
        return True
    if re.fullmatch(r"(?:好吃|全部|最新|有图/视频|近期差评|好评|差评|推荐)\s*\d*", t):
        return True
    if re.search(r"\d{4}-\d{1,2}-\d{1,2}", t):
        return True
    return False


def _digits(s):
    return re.sub(r"\D", "", s or "")


def normalize_date(text):
    """把 OCR 出的日期还原成 YYYY-MM-DD。

    淘宝日期在右侧，OCR 偶尔会把「优质」等水印粘进来，例如
    2026-11403 实际是 2026-11-03。这里取年份后第一组两位月份和最后两位日期。
    """
    m = re.search(r"20\d{2}", text or "")
    if not m:
        return ""
    year = m.group(0)
    tail = _digits(text[m.end():])
    if len(tail) < 4:
        return year
    month, day = tail[:2], tail[-2:]
    try:
        mi, di = int(month), int(day)
    except ValueError:
        return year
    if 1 <= mi <= 12 and 1 <= di <= 31:
        return f"{year}-{mi:02d}-{di:02d}"
    return year


def parse_rating(lines, anchor_y):
    """优先读「味道5星 / 包装5星」文字星级；没有文字星级时再数 ★。"""
    values = []
    for ln in lines:
        if abs(ln["y"] - anchor_y) > 90:
            continue
        text = ln["text"]
        for m in re.finditer(r"(?:味道|包装|商品|服务)?\s*(\d(?:\.\d)?)\s*星", text):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if 1 <= v <= 5:
                values.append(v)
    if values:
        return f"{sum(values) / len(values):.1f}"
    for ln in lines:
        if abs(ln["y"] - anchor_y) <= 35:
            stars = ln["text"].count("★") + ln["text"].count("☆")
            if stars:
                return f"{float(stars):.1f}"
    return ""


def parse_user(lines, top, anchor_y):
    """用户名在星级行上方，取最像用户名的一行；读不到就匿名。"""
    candidates = []
    for ln in lines:
        if not (top <= ln["y"] < anchor_y - 8):
            continue
        text = clean_line(ln["text"])
        if not text or len(text) > 20:
            continue
        if _is_ui(text):
            continue
        if re.fullmatch(r"[0-9\s.\-]+", text):
            continue
        if re.fullmatch(r"(?:Lv|LV|Dlv|DLV)\s*\d*", text):
            continue
        if "***" in text or re.search(r"[\u4e00-\u9fa5A-Za-z]", text):
            candidates.append((ln["y"], ln["x"], text))
    if not candidates:
        return "匿名用户"
    # 用户名离星级行最近的一行优先
    candidates.sort(key=lambda z: -z[0])
    user = candidates[0][2]
    if user in ("名用户", "用户") or user.endswith("名用户"):
        return "匿名用户"
    return user


def _is_body(text):
    t = clean_line(text)
    if not t or chinese_len(t) < 4:
        return False
    if _is_ui(t):
        return False
    if re.fullmatch(r"[0-9\s.\-:]+", t):
        return False
    return True


def parse_taobao_screen(lines):
    """按每个「满意度」锚点切一张截图里的多条评价。"""
    anchors = [ln for ln in lines if "满意度" in ln["text"]]
    if not anchors:
        return []
    anchors.sort(key=lambda z: z["y"])
    rows = []
    for i, a in enumerate(anchors):
        top = anchors[i - 1]["y"] + 20 if i else a["y"] - 230
        # 用户名只可能在星级行正上方，不能把上一条的正文当成用户名
        user_top = a["y"] - 230 if i == 0 else max(anchors[i - 1]["y"] + 20, a["y"] - 180)
        bottom = anchors[i + 1]["y"] - 20 if i + 1 < len(anchors) else 10 ** 9
        date = ""
        for ln in lines:
            if a["y"] - 40 <= ln["y"] <= a["y"] + 90 and ln["x"] > 550:
                d = normalize_date(ln["text"])
                if d:
                    date = d
                    break
        rating = parse_rating(lines, a["y"])
        user = parse_user(lines, user_top, a["y"])
        body = []
        for ln in lines:
            if not (a["y"] + 40 <= ln["y"] < bottom):
                continue
            if _is_body(ln["text"]):
                body.append(ln["text"])
        text = clean_line(" ".join(body))
        text = re.sub(r"(?<=[\u4e00-\u9fa5]) (?=[\u4e00-\u9fa5])", "", text)
        # 去掉评价卡底部的商品推荐/活动尾巴，只保留用户正文
        text = re.sub(r"(?:收藏有礼|加料福利|送考拉|超值加购|加购优惠)[^\n]*$", "", text)
        text = re.sub(r"^#?【[^】]{0,30}】#?", "", text)
        text = re.sub(r"#?【[^】]{0,30}】[^\n]*$", "", text)
        text = text.strip(" ，,。;；、")
        if chinese_len(text) < 4:
            continue
        rows.append({
            "user": user,
            "date": date,
            "rating": rating,
            "review": text,
            "source": "taobao_ocr",
        })
    return rows


def main():
    ap = argparse.ArgumentParser(description="淘宝外卖评价现场采集（截图 OCR）")
    ap.add_argument("--adb", help="adb.exe 路径；默认用工具自带 platform-tools")
    ap.add_argument("--serial", help="设备序列号；多台设备时必填")
    ap.add_argument("--out", help="输出目录；默认 output/时间_淘宝OCR采集")
    ap.add_argument("--max-seconds", type=float, default=20, help="采集时长（秒）")
    ap.add_argument("--max-reviews", type=int, default=80)
    ap.add_argument("--start-delay", type=int, default=3, help="开始前留给你切到淘宝评价页的秒数")
    ap.add_argument("--interval", type=float, default=1.0, help="每次滑动后等待秒数")
    ap.add_argument("--swipe-duration", type=int, default=350)
    ap.add_argument("--min-score", type=float, default=0.3)
    args = ap.parse_args()

    adb_path = find_adb(args.adb)
    if not adb_path:
        log("没有找到 adb。")
        sys.exit(2)
    adb = Adb(adb_path, args.serial or "")
    devs = adb.devices()
    if not devs:
        log("没有检测到已授权的设备。")
        sys.exit(2)
    if not adb.serial:
        adb.serial = devs[0]

    out_dir = Path(args.out) if args.out else make_out_dir("淘宝OCR采集")
    screen_dir = out_dir / "screens"
    screen_dir.mkdir(parents=True, exist_ok=True)

    log(f"设备 {adb.serial}，请停留在淘宝「外卖评价」页；{args.start_delay} 秒后开始。")
    time.sleep(max(0, args.start_delay))

    rows = []
    seen = set()
    start = time.time()
    shot = 0
    no_new = 0
    while time.time() - start < args.max_seconds and len(rows) < args.max_reviews:
        shot += 1
        img = screen_dir / f"{shot:03d}.png"
        try:
            adb.screenshot(img)
            lines = ocr_image(img, min_score=args.min_score)
            parsed = parse_taobao_screen(lines)
        except Exception as e:
            log(f"第 {shot} 屏失败：{e}")
            break
        before = len(rows)
        for r in parsed:
            key = re.sub(r"\W", "", r["review"])[:30]
            if key and key not in seen:
                seen.add(key)
                rows.append(r)
        log(f"第 {shot} 屏：OCR {len(lines)} 行，识别 {len(parsed)} 条，累计 {len(rows)} 条")
        no_new = no_new + 1 if len(rows) == before else 0
        if no_new >= 3:
            log("连续 3 屏没有新增，停止。")
            break
        try:
            adb.swipe(args.swipe_duration)
        except InputPermissionError as e:
            log(str(e))
            break
        time.sleep(max(0.3, args.interval))

    merged = merge_ui_rows(rows, max_reviews=args.max_reviews)
    if not merged:
        log("没有识别到评价。确认淘宝页面停在「外卖评价」列表，并且屏幕没有锁。")
        sys.exit(1)
    files = write_outputs(merged, out_dir, source="taobao_ocr", shop_name="淘宝外卖评价",
                          make_page=len(merged) >= 10)
    log(f"完成：{len(merged)} 条，输出 {out_dir}")
    for f in files:
        log(f"  {f}")


if __name__ == "__main__":
    main()
