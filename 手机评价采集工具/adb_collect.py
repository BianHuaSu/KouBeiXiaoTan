#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安卓 ADB 可见页面采集器。

只读取手机当前屏幕，自动下滑，OCR 后去重导出。不逆向 App 接口、不破解验证；
需要你手动登录 App 并打开店铺评价页。
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import APP_DIR, CollectStats, make_out_dir, merge_rows, parse_screen, write_outputs
from ocr_core import ocr_image_cropped

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class InputPermissionError(RuntimeError):
    """手机拒绝 ADB 注入触摸事件。"""


def log(msg):
    print(msg, flush=True)


def find_adb(explicit=None):
    if explicit and Path(explicit).exists():
        return str(Path(explicit))
    env = os.environ.get("ADB")
    if env and Path(env).exists():
        return env
    bundled = APP_DIR / "adb" / "platform-tools" / "adb.exe"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("adb")
    if found:
        return found
    return ""


class Adb:
    def __init__(self, adb, serial=""):
        self.adb = adb
        self.serial = serial

    @property
    def base(self):
        return [self.adb] + (["-s", self.serial] if self.serial else [])

    def run(self, args, binary=False):
        cmd = self.base + args
        if binary:
            return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
        )

    def shell(self, args):
        return self.run(["shell"] + args)

    def devices(self):
        r = self.run(["devices"])
        out = (r.stdout or "") + "\n" + (r.stderr or "")
        devs = []
        for line in out.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+device\b", line)
            if m:
                devs.append(m.group(1))
            elif re.match(r"^(\S+)\s+unauthorized\b", line):
                log(f"设备 {line.split()[0]} 未授权：请在手机上点“允许 USB 调试”。")
        return devs

    def screen_size(self):
        r = self.shell(["wm", "size"])
        sizes = re.findall(r"(\d+)\s*x\s*(\d+)", (r.stdout or "") + (r.stderr or ""))
        if not sizes:
            return 1080, 2400
        w, h = sizes[-1]
        return int(w), int(h)

    def screenshot(self, path):
        with open(path, "wb") as f:
            r = subprocess.run(
                self.base + ["exec-out", "screencap", "-p"],
                stdout=f, stderr=subprocess.PIPE, creationflags=CREATE_NO_WINDOW,
            )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or b"").decode("utf-8", "replace") or "screencap 失败")
        if path.stat().st_size < 100:
            raise RuntimeError("截图为空，确认手机已解锁并允许 USB 调试")

    def swipe(self, duration=600):
        w, h = self.screen_size()
        x = w // 2
        y1 = int(h * 0.80)
        y2 = int(h * 0.22)
        r = self.shell(["input", "swipe", str(x), str(y1), str(x), str(y2), str(duration)])
        if r.returncode != 0:
            err = (r.stderr or "").strip()
            if "INJECT_EVENTS" in err or "SecurityException" in err:
                raise InputPermissionError(
                    "手机拒绝了 ADB 模拟滑动（INJECT_EVENTS 权限）。\n"
                    "小米/Redmi/HyperOS：到 设置 → 更多设置 → 开发者选项，打开「USB调试（安全设置）」；\n"
                    "开启后重新插拔数据线，或关闭再打开「USB调试」，再试一次。\n"
                    "其他品牌如果也拦截 input，请改用「截图 OCR 导入」手动截图。"
                )
            raise RuntimeError(f"滑动失败：{err or 'adb input swipe 返回非零'}")


def parse_crop(text):
    parts = [float(x.strip()) for x in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop 需要四个比例：top,bottom,left,right")
    return tuple(max(0.0, min(0.5, x)) for x in parts)


def main():
    ap = argparse.ArgumentParser(description="安卓 ADB 可见页面采集")
    ap.add_argument("--adb", help="adb.exe 路径；默认用工具自带 platform-tools")
    ap.add_argument("--serial", help="设备序列号；多台设备时必填")
    ap.add_argument("--out", help="输出目录；默认 output/时间_ADB采集")
    ap.add_argument("--max-reviews", type=int, default=80)
    ap.add_argument("--max-swipes", type=int, default=20)
    ap.add_argument("--start-delay", type=int, default=5, help="开始前留给你切到评价页的秒数")
    ap.add_argument("--interval", type=float, default=0.8, help="每次滑动后的等待秒数")
    ap.add_argument("--swipe-duration", type=int, default=600)
    ap.add_argument("--mode", choices=["screen", "card"], default="screen")
    ap.add_argument("--crop", default="0,0,0,0", help="裁剪比例 top,bottom,left,right")
    ap.add_argument("--min-score", type=float, default=0.35)
    args = ap.parse_args()

    adb = find_adb(args.adb)
    if not adb:
        log("没有找到 adb。把 Android platform-tools 放到 adb/platform-tools/，或设置 ADB 环境变量。")
        sys.exit(2)
    try:
        crop = parse_crop(args.crop)
    except ValueError as e:
        log(str(e))
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

    out_dir = Path(args.out) if args.out else make_out_dir("ADB采集")
    (out_dir / "screens").mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "ocr_raw.txt"

    log(f"请在 {args.start_delay} 秒内把手机切到店铺评价页，并保持屏幕常亮。")
    for i in range(args.start_delay, 0, -1):
        log(f"  {i}...")
        time.sleep(1)

    all_rows = []
    stats = CollectStats()
    raw_blocks = []
    no_new = 0
    pages = 0
    try:
        for page in range(args.max_swipes + 1):
            shot = out_dir / "screens" / f"{page + 1:03d}.png"
            dev.screenshot(shot)
            try:
                lines = ocr_image_cropped(shot, crop, args.min_score)
            except Exception as e:
                log(f"第 {page + 1} 屏 OCR 失败：{e}")
                break
            rows = parse_screen(lines, args.mode, stats=stats)
            for r in rows:
                r["source"] = "adb"
                r["page"] = f"{page + 1:03d}"
            before = len(merge_rows(all_rows))
            all_rows.extend(rows)
            after = len(merge_rows(all_rows))
            pages += 1
            log(f"第 {page + 1} 屏：识别 {len(lines)} 行，提取 {len(rows)} 条，新增 {after - before} 条，累计 {after} 条")
            raw_blocks.append(f"===== 第 {page + 1} 屏 =====")
            raw_blocks.extend([x["text"] for x in lines])
            raw_path.write_text("\n".join(raw_blocks), encoding="utf-8")
            write_outputs(all_rows, out_dir, "adb", make_page=False, stats=stats)

            if after >= args.max_reviews:
                break
            if after == before:
                no_new += 1
            else:
                no_new = 0
            if no_new >= 2:
                log("连续两屏没有新增评论，停止滑动。")
                break
            if page < args.max_swipes:
                dev.swipe(args.swipe_duration)
                time.sleep(max(0.2, args.interval))
    except KeyboardInterrupt:
        log("手动停止。")
    except InputPermissionError as e:
        log(f"\n{e}\n采集已停止：当前只能截到第一屏，继续跑只会重复。")
    except Exception as e:
        log(f"采集中止：{e}")

    full, demo, page = write_outputs(all_rows, out_dir, "adb", shop_name="手机 ADB 采集", stats=stats)
    total = len(merge_rows(all_rows))
    if stats.dropped:
        detail = " · ".join(f"{k} {v}" for k, v in stats.reasons().most_common())
        log(f"完成：原始 {total + stats.dropped} 条 · 有效 {total} 条 · "
            f"过滤 {stats.dropped} 条（{detail}），截图 {pages} 张")
    else:
        log(f"完成，共 {total} 条，截图 {pages} 张")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    log(f"OCR 原始文本：{raw_path}")
    if total < 10:
        log("提示：Demo 上传至少需要 10 条；可以多滑几屏，或先用 OCR 工具补充。")


if __name__ == "__main__":
    main()
