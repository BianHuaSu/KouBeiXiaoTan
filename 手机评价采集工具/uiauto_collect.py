#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android UI Automator 界面树采集器。

比 OCR 更准：直接读取系统暴露的文本节点和坐标，再按评价卡片的版面切分。
只读取手机当前可见页面，不逆向 App 接口、不破解验证。
"""

import argparse
import csv
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

from adb_collect import Adb, InputPermissionError, find_adb, log
from common import CollectStats, make_out_dir, merge_rows, write_outputs
from uiauto_core import merge_ui_rows, parse_ui_nodes, read_nodes

ANIM_KEYS = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")


class AnimationGuard:
    """临时关闭系统动画，避免 uiautomator dump 一直等 idle；结束后恢复。"""

    def __init__(self, dev):
        self.dev = dev
        self.old = {}

    def __enter__(self):
        for key in ANIM_KEYS:
            try:
                r = self.dev.shell(["settings", "get", "global", key])
                val = (r.stdout or "").strip()
                if val and val != "null":
                    self.old[key] = val
                    self.dev.shell(["settings", "put", "global", key, "0"])
            except Exception:
                pass
        return self

    def __exit__(self, *exc):
        for key, val in self.old.items():
            try:
                self.dev.shell(["settings", "put", "global", key, val])
            except Exception:
                pass


def reset_uiautomator(dev):
    """清掉卡死的 uiautomator 进程；真机上偶尔会残留并让下一次 dump 被 SIGKILL。"""
    try:
        dev.shell(["sh", "-c", "pkill -f uiautomator || true"])
    except Exception:
        pass


def dump_nodes(dev, local_xml, retries=3):
    remote = "/sdcard/window_dump.xml"
    for i in range(retries):
        r = dev.shell(["uiautomator", "dump", "--compressed", remote])
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        if r.returncode == 0 and "dumped" in out.lower():
            # adb on Windows 对部分中文路径无法直接创建文件；先拉到纯 ASCII 临时目录，再由 Python 复制。
            tmp_dir = Path(tempfile.mkdtemp(prefix="uiauto_"))
            tmp_xml = tmp_dir / "page.xml"
            try:
                pull = dev.run(["pull", remote, str(tmp_xml)])
                if pull.returncode == 0 and tmp_xml.exists() and tmp_xml.stat().st_size > 100:
                    local_xml.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(tmp_xml, local_xml)
                    return read_nodes(local_xml)
                out = ((pull.stdout or "") + "\n" + (pull.stderr or "")).strip()
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
        if i + 1 < retries:
            log(f"界面树读取失败，重试 {i + 1}/{retries - 1}：{out.splitlines()[-1] if out else '无输出'}；清理 uiautomator 进程")
            reset_uiautomator(dev)
            time.sleep(1.2)
    raise RuntimeError(out or "uiautomator dump 失败")


def main():
    ap = argparse.ArgumentParser(description="Android UI Automator 界面树采集")
    ap.add_argument("--adb", help="adb.exe 路径；默认用工具自带 platform-tools")
    ap.add_argument("--serial", help="设备序列号；多台设备时必填")
    ap.add_argument("--out", help="输出目录；默认 output/时间_UI树采集")
    ap.add_argument("--max-reviews", type=int, default=80)
    ap.add_argument("--max-screens", type=int, default=20)
    ap.add_argument("--start-delay", type=int, default=5)
    ap.add_argument("--interval", type=float, default=0.35, help="每屏读取后等待秒数")
    ap.add_argument("--swipe-duration", type=int, default=320)
    ap.add_argument("--single-screen", action="store_true", help="只抓当前一屏，不滑动")
    ap.add_argument("--manual-scroll", action="store_true", help="每屏后由你手动滑动，按回车继续")
    ap.add_argument("--append", action="store_true", help="把当前屏追加到已有 reviews_full.csv；手动逐屏采集用")
    ap.add_argument("--with-shots", action="store_true", help="同时截图校准真实半星（慢；默认不截图）")
    args = ap.parse_args()

    adb = find_adb(args.adb)
    if not adb:
        log("没有找到 adb。把 Android platform-tools 放到 adb/platform-tools/，或设置 ADB 环境变量。")
        sys.exit(2)

    devs = Adb(adb).devices()
    if not devs:
        log("没有检测到已授权设备。请开 USB 调试，连接手机，手机上点“允许”。")
        sys.exit(3)
    serial = args.serial
    if serial:
        if serial not in devs:
            log(f"没有找到授权设备 {serial}；当前设备：{'、'.join(devs)}")
            sys.exit(3)
    else:
        if len(devs) > 1:
            log("检测到多台设备：" + "、".join(devs) + "；请用 --serial 指定。")
            sys.exit(3)
        serial = devs[0]

    dev = Adb(adb, serial)
    w, h = dev.screen_size()
    log(f"设备 {serial}，屏幕 {w}x{h}")

    out_dir = Path(args.out) if args.out else make_out_dir("UI树采集")
    ui_dir = out_dir / "ui"
    ui_dir.mkdir(parents=True, exist_ok=True)
    shot_dir = out_dir / "screens" if args.with_shots else None
    if shot_dir:
        shot_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "ui_raw.txt"
    full_path = out_dir / "reviews_full.csv"

    all_rows = []
    stats = CollectStats()
    page_start = 1
    raw_prefix = ""
    if args.append and full_path.exists():
        try:
            with open(full_path, "r", encoding="utf-8-sig", newline="") as f:
                all_rows = [dict(r) for r in csv.DictReader(f) if r.get("review")]
            nums = [int(r["page"]) for r in all_rows if str(r.get("page", "")).isdigit()]
            page_start = max(nums) + 1 if nums else 1
            log(f"追加模式：已有 {len(all_rows)} 条，从第 {page_start} 屏继续。")
        except Exception as e:
            log(f"读取已有 CSV 失败，按新目录开始：{e}")
            all_rows = []
            page_start = 1
    if args.append and raw_path.exists():
        raw_prefix = raw_path.read_text(encoding="utf-8").rstrip() + "\n"

    log(f"请在 {args.start_delay} 秒内把手机切到店铺评价页，并保持屏幕常亮。")
    for i in range(args.start_delay, 0, -1):
        log(f"  {i}...")
        time.sleep(1)

    raw_blocks = []
    no_new = 0
    pages = 0
    try:
        with AnimationGuard(dev):
            for page in range(args.max_screens):
                page_no = page_start + page
                xml_path = ui_dir / f"page_{page_no:03d}.xml"
                try:
                    nodes = dump_nodes(dev, xml_path)
                except Exception as e:
                    log(f"第 {page_no} 屏界面树读取失败：{e}")
                    break
                shot_path = None
                if shot_dir:
                    shot_path = shot_dir / f"{page_no:03d}.png"
                    try:
                        dev.screenshot(shot_path)
                    except Exception as e:
                        shot_path = None
                        log(f"第 {page_no} 屏截图失败，星级退回标签估算：{e}")
                rows = parse_ui_nodes(nodes, w, h, shot_path, stats=stats)
                for r in rows:
                    r["source"] = "uiauto"
                    r["page"] = f"{page_no:03d}"
                before = len(merge_rows(all_rows))
                all_rows.extend(rows)
                after = len(merge_rows(all_rows))
                pages += 1
                log(f"第 {page_no} 屏：界面节点 {len(nodes)} 个，评论 {len(rows)} 条，新增 {after - before} 条，累计 {after} 条")
                raw_blocks.append(f"===== 第 {page_no} 屏 =====")
                raw_blocks.append("\n".join(n["text"] for n in nodes if n["text"]))
                raw_path.write_text(raw_prefix + "\n".join(raw_blocks), encoding="utf-8")
                write_outputs(all_rows, out_dir, "uiauto", shop_name="手机界面树采集",
                              make_page=False, stats=stats)

                if args.single_screen or after >= args.max_reviews:
                    break
                if after == before:
                    no_new += 1
                else:
                    no_new = 0
                if no_new >= 2:
                    log("连续两屏没有新增评论，停止。")
                    break
                if args.manual_scroll:
                    try:
                        input("请在手机上向上滑动到下一屏，然后按回车继续……")
                    except EOFError:
                        break
                else:
                    dev.swipe(args.swipe_duration)
                time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        log("手动停止。")
    except InputPermissionError as e:
        log(f"\n{e}\n采集已停止：当前只能读到第一屏，继续跑只会重复。")
    except Exception as e:
        log(f"采集中止：{e}")
        if os.environ.get("UIAUTO_DEBUG"):
            traceback.print_exc()

    full, demo, page = write_outputs(all_rows, out_dir, "uiauto", shop_name="手机界面树采集",
                                     stats=stats)
    total = len(merge_rows(all_rows))
    if stats.dropped:
        detail = " · ".join(f"{k} {v}" for k, v in stats.reasons().most_common())
        log(f"完成：原始 {total + stats.dropped} 条 · 有效 {total} 条 · "
            f"过滤 {stats.dropped} 条（{detail}），界面树 {pages} 屏")
    else:
        log(f"完成，共 {total} 条，界面树 {pages} 屏")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    log(f"界面树原始文本：{raw_path}")
    if total < 10:
        log("提示：Demo 上传至少需要 10 条；可以多滑几屏，或先用 OCR 工具补充。")


if __name__ == "__main__":
    main()
