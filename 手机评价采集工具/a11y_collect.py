#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机无障碍服务采集：滑动时持续读快照，不再逐屏 uiautomator dump。

前置：
1. 手机安装并启用“口碑小探评价读取”无障碍服务（a11y_helper.apk）；
2. 手机打开大众点评 / 美团 / 饿了么 / 京东 / 淘宝的店铺评价页；
3. 数据线连接，USB 调试已授权。

淘宝说明：淘宝评价页跑在 io.unicorn（Flutter 自绘引擎）里，普通状态无障碍树是空的。
脚本检测到淘宝时会临时打开系统“触摸探索”（借系统级 TalkBack），
Flutter 语义树随即发布，每条评价都能读到“评价用户：X，满意度N，味道N星…”这样的结构化标签，
采完自动还原无障碍服务。这条路读的是真节点，不是 OCR。

特点：
- 采集端由手机无障碍服务在页面滚动/内容变化时主动抓节点；
- PC 端只读取服务写出的 a11y_stream.jsonl，按 seq 取新增快照；
- 滑动由 ADB 连续触发，但读取不依赖“滑一屏停三秒 dump”，所以能边滑边读。
"""

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from adb_collect import Adb, InputPermissionError, CREATE_NO_WINDOW, find_adb, log
import taobao_a11y as tb
import jd_ocr
from common import (APP_DIR, CollectStats, chinese_len, clean_line, make_out_dir,
                    merge_rows, write_outputs)
from uiauto_core import merge_ui_rows, parse_bounds, parse_ui_nodes

APP_PKG = "com.koubei.a11y"
STREAM = "files/a11y_stream.jsonl"

APP_SOURCE = {
    "com.dianping.v1": "a11y_dianping",
    "com.sankuai.meituan": "a11y_meituan",
    "com.sankuai.meituan.takeoutnew": "a11y_meituan",
    "me.ele": "a11y_eleme",
    "com.jingdong.app.mall": "a11y_jd",
    "com.taobao.taobao": "a11y_taobao",
}

JD_PKG = "com.jingdong.app.mall"


def source_for(snap):
    return APP_SOURCE.get(snap.get("pkg", ""), "a11y")


def dominant_source(rows):
    counts = {}
    for r in rows:
        s = r.get("source") or "a11y"
        counts[s] = counts.get(s, 0) + 1
    if not counts:
        return "a11y"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def log_stats(rows, stats, prefix="完成"):
    """把“原始 / 有效 / 过滤”一起打出来，别只报有效条数。"""
    if stats is None:
        log(f"{prefix}，共 {len(rows)} 条")
        return
    raw, dropped = len(rows) + stats.dropped, stats.dropped
    detail = " · ".join(f"{k} {v}" for k, v in stats.reasons().most_common())
    if dropped:
        log(f"{prefix}：原始 {raw} 条 · 有效 {len(rows)} 条 · 过滤 {dropped} 条"
            f"（{detail}）")
    else:
        log(f"{prefix}：原始 {raw} 条 · 有效 {len(rows)} 条（本次没有过滤样本）")


def service_enabled(dev):
    r = dev.shell(["settings", "get", "secure", "enabled_accessibility_services"])
    return "com.koubei.a11y" in ((r.stdout or "") + (r.stderr or ""))


def last_snap_pkg(stream_text):
    """无障碍流最后一条快照来自哪个 App（用来判断事件流停在淘宝还是当前页面）。"""
    for line in reversed((stream_text or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "snap":
            return obj.get("pkg") or ""
    return ""


def read_stream(dev):
    r = dev.shell(["run-as", APP_PKG, "cat", STREAM])
    out = r.stdout or ""
    err = (r.stderr or "").strip()
    if r.returncode != 0:
        if "not debuggable" in err:
            raise RuntimeError(
                "辅助 App 不是 debuggable，PC 读不到内部文件。\n"
                "请重新安装工具包里的 a11y_helper.apk（debug 版），再重试。"
            )
        if "No such file" in err or "No such file" in out:
            raise RuntimeError(
                "还没有收到无障碍快照。\n"
                "请确认：手机已安装并启用“口碑小探评价读取”服务，且当前页面是大众点评/美团/饿了么/京东的评价页。\n"
                "可以打开辅助 App 点“刷新服务状态”，或到系统无障碍设置里重新开关一次。"
            )
        raise RuntimeError(f"读取无障碍流失败：{err or out}")
    return out


def nodes_from_snap(snap):
    nodes = []
    for n in snap.get("nodes", []):
        text = clean_line(n.get("t", ""))
        desc = clean_line(n.get("d", ""))
        if not text and not desc and not n.get("r"):
            continue
        b = parse_bounds(n.get("b", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        nodes.append({
            "text": text,
            "x": x1,
            "y": y1,
            "w": x2 - x1,
            "h": y2 - y1,
            "cls": n.get("c", ""),
            "desc": desc,
            "range": n.get("r", ""),
            "clickable": bool(n.get("k")),
        })
    return nodes


def parse_stream(text, last_seq=0, initial_latest=False):
    """返回 (snapshots, last_seq, ready)。"""
    snaps = []
    ready = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            # 文件正在写入时可能读到半行，下一次会补全
            continue
        if obj.get("type") == "ready":
            ready = True
            continue
        if obj.get("type") != "snap":
            continue
        seq = int(obj.get("seq", 0))
        if seq <= last_seq:
            continue
        snaps.append(obj)
        last_seq = seq
    if initial_latest and snaps:
        snaps = [snaps[-1]]
    return snaps, last_seq, ready


def rows_from_snaps(snaps, source=None, stats=None):
    rows = []
    for snap in snaps:
        nodes = nodes_from_snap(snap)
        w = int(snap.get("w") or 0)
        h = int(snap.get("h") or 0)
        if not nodes or w <= 0 or h <= 0:
            continue
        try:
            parsed = parse_ui_nodes(nodes, w, h, jd=(snap.get("pkg") == JD_PKG), stats=stats)
        except Exception as exc:
            log(f"快照 {snap.get('seq')} 解析失败：{exc}")
            continue
        src = source or source_for(snap)
        for r in parsed:
            r["source"] = src
            r["page"] = snap.get("seq", "")
            r["user"] = r.get("user") or "匿名用户"
            rows.append(r)
    return rows


def swipe_once(dev, w, h, duration, y1_ratio, y2_ratio, brake=True):
    """一次“快滑 + 立刻刹住”。

    input swipe 到手指抬起时会有惯性甩动，屏幕不会立刻停；
    所以滑完马上补一发 DOWN+CANCEL，把惯性吃掉（CANCEL 不会触发点击），
    这样「滑 100ms → 停住」才是真的停住，紧接着的 200ms 就是纯读快照的时间。
    """
    x = w // 2
    y1 = int(h * y1_ratio)
    y2 = int(h * y2_ratio)
    if brake:
        sy = (y1 + y2) // 2
        cmd = (f"input swipe {x} {y1} {x} {y2} {duration}; "
               f"input motionevent DOWN {x} {sy}; "
               f"input motionevent CANCEL {x} {sy}")
        r = dev.shell([cmd])
    else:
        r = dev.shell(["input", "swipe", str(x), str(y1), str(x), str(y2), str(duration)])
    if r.returncode != 0:
        err = ((r.stdout or "") + (r.stderr or "")).strip()
        if "INJECT_EVENTS" in err or "SecurityException" in err:
            raise InputPermissionError(
                "手机拒绝了 ADB 模拟滑动（INJECT_EVENTS 权限）。\n"
                "小米/Redmi/HyperOS：设置 → 更多设置 → 开发者选项 → 打开「USB调试（安全设置）」；\n"
                "开启后重新插拔数据线，或关闭再打开 USB 调试。\n"
                "也可以加 --manual，由你手动滑动，手机端仍会持续读取。"
            )
        raise RuntimeError(f"滑动失败：{err or 'adb input swipe 返回非零'}")


def repair_service(dev):
    """重启无障碍助手服务，修复“绑定还在、事件流已死”的僵死状态。

    分两种情况：
    - TalkBack 不在列表（淘宝采完的常态）：整表清空再重绑。HyperOS 上只有
      “断开全部 → 结束进程 → 重新绑定”能真正清掉坏实例，只摘助手一项不够。
    - TalkBack 还在列表（用户手动 --tb-keep 或采集途中）：只动助手这一项，
      别把触摸探索一起关掉，免得又变成“反复开关”。
    """
    services = tb.get_enabled_services(dev)
    if tb.TALKBACK_SERVICE in services:
        others = [s for s in services if s != tb.HELPER_SERVICE] or [tb.TALKBACK_SERVICE]
        tb.set_enabled_services(dev, others)
        time.sleep(0.8)
        dev.shell(["am", "force-stop", tb.HELPER_PKG])
        time.sleep(0.8)
        tb.set_enabled_services(dev, services or [tb.HELPER_SERVICE])
        time.sleep(2.0)
        return services
    tb.set_enabled_services(dev, [])
    time.sleep(1.0)
    dev.shell(["am", "force-stop", tb.HELPER_PKG])
    time.sleep(1.0)
    tb.set_enabled_services(dev, services or [tb.HELPER_SERVICE])
    time.sleep(2.0)
    return services


def scroll_loop(dev, w, h, args, stop_event, error_box):
    while not stop_event.is_set():
        try:
            swipe_once(dev, w, h, args.swipe_duration, args.y1, args.y2,
                       brake=not getattr(args, "no_brake", False))
        except InputPermissionError as exc:
            error_box.append(str(exc))
            stop_event.set()
            return
        except Exception as exc:
            error_box.append(f"滑动失败：{exc}")
            stop_event.set()
            return
        # 淘宝这类 Flutter 自绘页在惯性滑动中语义树是抖的，
        # 滑完要留一段静止时间，服务才能读到完整评价卡。
        if args.settle and stop_event.wait(args.settle):
            return
        if stop_event.wait(args.swipe_interval):
            return


def foreground_package(dev):
    """取当前前台包名（用来判断是不是淘宝、要不要切采集路径）。"""
    try:
        r = dev.shell(["dumpsys", "window"])
        text = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return ""
    for line in text.splitlines():
        if "mCurrentFocus" not in line and "mFocusedApp" not in line:
            continue
        m = re.search(r"([A-Za-z0-9_.]+)/[A-Za-z0-9_.$]+", line)
        if m:
            return m.group(1)
    return ""


def run_taobao_ocr(adb, dev, args):
    log("改用淘宝截图 OCR 现场采集（淘宝语义树不可用时的兜底）。")
    cmd = [
        sys.executable, str(APP_DIR / "taobao_collect.py"),
        "--adb", adb, "--serial", dev.serial,
        "--max-seconds", str(args.max_seconds or 20),
        "--start-delay", str(int(round(max(0, args.start_delay)))),
        "--interval", "0.6",
        "--max-reviews", str(args.max_reviews or 80),
    ]
    if args.out:
        cmd += ["--out", args.out]
    log("淘宝采集命令：" + " ".join(cmd))
    rc = subprocess.call(cmd)
    log(f"淘宝 OCR 采集退出码：{rc}")
    return rc


def mute_taobao_speech(dev):
    """淘宝采集期间把媒体音量压到 0。

    TalkBack 的朗读和“开/关”提示音走媒体流，开着触摸探索采集时会不停报界面内容。
    记下原始音量，采完恢复，只影响这一小段时间。
    """
    try:
        r = dev.shell(["settings", "get", "system", "volume_music"])
        old = ((r.stdout or "") + (r.stderr or "")).strip()
        if old.isdigit():
            dev.shell(["settings", "put", "system", "volume_music", "0"])
            return old
    except Exception:
        pass
    return None


def unmute_taobao_speech(dev, old):
    if old and str(old).isdigit():
        try:
            dev.shell(["settings", "put", "system", "volume_music", str(old)])
        except Exception:
            pass


def disable_talkback(dev, log=print, restore=None):
    """把 TalkBack 从无障碍列表里摘掉，触摸探索随之关闭。

    只动 TalkBack 这一项：口碑小探、李跳跳、钱包读屏都保持原样。
    但 HyperOS 摘掉 TalkBack 时会把 SelectToSpeak 这类“伴生读屏服务”一起带走，
    所以采前记下的那份列表（restore，不含 TalkBack）要在之后补回去，
    否则用户原本开着的读屏能力会莫名其妙消失。
    """
    services = tb.get_enabled_services(dev)
    if tb.TALKBACK_SERVICE not in services:
        return True
    keep = [s for s in services if s != tb.TALKBACK_SERVICE]
    tb.set_enabled_services(dev, keep)
    deadline = time.time() + 10.0
    while time.time() < deadline and tb.touch_exploration_on(dev):
        time.sleep(0.5)
    ok = not tb.touch_exploration_on(dev)
    if ok:
        log("淘宝采集结束：已关闭 TalkBack 与触摸探索，单指单击恢复正常。")
    else:
        log("TalkBack 已移出列表，但触摸探索还开着：请到系统无障碍里手动关一次 TalkBack。")
    if restore:
        want = [s for s in restore if s != tb.TALKBACK_SERVICE]
        cur = tb.get_enabled_services(dev)
        cur_pkgs = {s.split("/")[0] for s in cur}
        missing = [s for s in want if s.split("/")[0] not in cur_pkgs]
        if missing:
            kept = list(cur)
            for s in missing:
                if s.split("/")[0] not in {x.split("/")[0] for x in kept}:
                    kept.append(s)
            tb.set_enabled_services(dev, kept)
            log(f"已补回被系统连带摘掉的无障碍服务：{'、'.join(s.split('/')[0] for s in missing)}")
    return ok


def run_jd_ocr(adb, dev, args):
    """京东外卖点评页：Manto 自绘页，无障碍读不到正文/星级，改走截图 OCR + 数红星。"""
    log("京东点评页跑在 Manto 小程序容器里（自绘）：无障碍只能拿到容器、按钮、日期和"
        "“用户评价，图片”这类占位节点，正文/星级没有独立节点。")
    log("所以京东改走截图 OCR：按“评分”切卡、在评分右侧数红色实心星，图片里印的字和页脚会被过滤。")
    out_dir = Path(args.out) if args.out else make_out_dir("京东OCR采集")
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"设备：{dev.serial}")
    log(f"输出：{out_dir}")

    holder = []
    last_write = [0.0]
    stats = CollectStats()

    def on_rows(rows):
        holder[:] = rows
        if time.time() - last_write[0] >= 2.0:
            last_write[0] = time.time()
            write_outputs(holder, out_dir, "jd_ocr", shop_name=args.shop_name,
                          make_page=False, stats=stats)

    try:
        jd_ocr.collect(
            dev,
            max_seconds=args.max_seconds or 120,
            max_reviews=args.max_reviews,
            settle=(args.jd_settle if args.jd_settle is not None else 0.3),
            swipe_duration=args.swipe_duration,
            y1=args.y1,
            y2=args.y2,
            brake=not getattr(args, "no_brake", False),
            idle_pages=5,
            log=log,
            on_rows=on_rows,
            shot_path=out_dir / "_screen.png",
            stats=stats,
        )
    except KeyboardInterrupt:
        log("收到 Ctrl+C，停止采集。")

    holder = merge_rows(holder)
    holder = jd_ocr.merge_similar(holder)
    full, demo, page = write_outputs(holder, out_dir, "jd_ocr",
                                     shop_name=args.shop_name, make_page=not args.no_page, stats=stats)
    log_stats(holder, stats, "完成")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    if len(holder) < 10:
        log("提示：Demo 上传至少需要 10 条；确认手机停在该店铺的「点评」标签页，再重跑一次。")
    return 0


def run_taobao_a11y(adb, dev, args):
    """淘宝走 Flutter 语义树：采集开始时开一次 TalkBack，采集结束关掉。"""
    prev = None
    baseline = tb.get_enabled_services(dev)   # 采前列表，采完照这份恢复（TalkBack 除外）
    if tb.touch_exploration_on(dev):
        log("「触摸探索」已经开着：直接读淘宝语义树，本次不再重复开启。")
    else:
        log("淘宝是 Flutter 自绘页，需要「触摸探索」把语义树发布出来：本次采集开一次，采完自动关掉。")
        try:
            prev = tb.enable_touch_exploration(dev, log)
        except Exception as exc:
            log(str(exc))
            return run_taobao_ocr(adb, dev, args)

    out_dir = Path(args.out) if args.out else make_out_dir("淘宝无障碍采集")
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"设备：{dev.serial}")
    log(f"输出：{out_dir}")

    holder = []
    last_write = [0.0]
    stats = CollectStats()
    old_volume = None
    if not getattr(args, "tb_sound", False):
        old_volume = mute_taobao_speech(dev)
        if old_volume:
            log(f"已临时静音（原音量 {old_volume}）：淘宝模式开着触摸探索会不停朗读界面，"
                f"采集期间先静下来，采完自动恢复。")

    def publish():
        if not holder:
            return
        write_outputs(holder, out_dir, "a11y_taobao", shop_name=args.shop_name,
                      make_page=not args.no_page, stats=stats)

    def on_rows(rows):
        holder[:] = rows
        if time.time() - last_write[0] >= 2.0:
            last_write[0] = time.time()
            publish()

    try:
        # 淘宝也走同一套快滑节奏：950px、100ms 内甩完、立刻刹住。
        # 读的时候不再先停 200ms —— dump 本身会等页面空闲，早一点发起就能把
        # “等页面渲染”和“滑动”重叠掉，实测 4.00s/屏降到 2.94s/屏，新增条数不变。
        tb.collect(
            dev,
            max_seconds=args.max_seconds or 120,
            max_reviews=args.max_reviews,
            idle_stop=0,          # 淘宝 dump 慢，用“秒”判到底会误停，改由屏计数判断
            idle_pages=6,
            settle=(args.tb_settle if args.tb_settle is not None else 0.0),
            swipe_duration=args.swipe_duration,
            y1=args.y1,
            y2=args.y2,
            brake=not getattr(args, "no_brake", False),
            manual=args.manual,
            log=log,
            on_rows=on_rows,
            stats=stats,
        )
    except KeyboardInterrupt:
        log("收到 Ctrl+C，停止采集。")
    finally:
        unmute_taobao_speech(dev, old_volume)
        # 淘宝只在采集期间用 TalkBack：采完就把 TalkBack 摘掉，触摸探索随之关闭，
        # 单指单击恢复正常，其他 App 的读取不受影响。
        if getattr(args, "tb_keep", False):
            log("按 --tb-keep 保持触摸探索开启（连续采淘宝时省一次开关）。")
        else:
            disable_talkback(dev, log, restore=baseline)
        # dump 走的 UiAutomation 会把助手的事件流顶掉。但**不能在淘宝前台重绑**：
        # 那时助手绑到的是淘宝的 Flutter 窗口，切回美团后照样读不到，白折腾一趟；
        # 而且在淘宝前台重绑，系统还会顺势把助手从启用列表里摘掉。
        # 所以这里只做两件事：确认助手还在列表里；真正修等切回目标 App 后由
        # 主链路启动时自检 / 12 秒无快照自愈来完成（那时前台才是对的）。
        try:
            svc = tb.get_enabled_services(dev)
            if tb.HELPER_SERVICE not in svc:
                tb.set_enabled_services(dev, svc + [tb.HELPER_SERVICE])
                log("助手被系统摘出了启用列表，已补回；切到美团/大众点评后会自动重连。")
        except Exception as exc:
            log(f"检查读取服务失败：{exc}")

    holder = merge_rows(holder)
    full, demo, page = write_outputs(holder, out_dir, "a11y_taobao",
                                     shop_name=args.shop_name, make_page=not args.no_page, stats=stats)
    log_stats(holder, stats, "完成")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    if len(holder) < 10:
        log("提示：Demo 上传至少需要 10 条；把 --max-seconds 调大，或先把评价列表滑到顶部再采。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="手机无障碍服务边滑边读采集")
    ap.add_argument("--adb", help="adb.exe 路径；默认用工具自带 platform-tools")
    ap.add_argument("--serial", help="设备序列号；多台设备时必填")
    ap.add_argument("--out", help="输出目录；默认 output/时间_无障碍采集")
    ap.add_argument("--shop-name", default="外卖店铺", help="报表上的店铺名")
    ap.add_argument("--manual", action="store_true", help="不自动滑动，由你手动滑，手机端持续读取")
    ap.add_argument("--dump-only", action="store_true", help="只解析手机里已有的快照，不滑动")
    ap.add_argument("--start-delay", type=float, default=3.0, help="开始滑动前留给你切页面的秒数")
    ap.add_argument("--swipe-duration", type=int, default=100, help="滑动时长（毫秒），默认 100（快滑）")
    ap.add_argument("--swipe-interval", type=float, default=0.2, help="两次滑动之间间隔；越小越连续")
    ap.add_argument("--settle", type=float, default=0.2, help="滑完到下一滑之间留给快照读取的静止时间，默认 0.2 秒")
    ap.add_argument("--tb-settle", type=float, default=None,
                    help="淘宝滑完后静止多久再读，默认 0（直接 dump，让它自己等页面空闲；比先停 200ms 快约 1 秒/屏）")
    ap.add_argument("--y1", type=float, default=0.86, help="滑动起点占屏高比例")
    ap.add_argument("--y2", type=float, default=0.51, help="滑动终点占屏高比例；0.86→0.51 约 950px，100ms 内甩完即停，一次滑走两三张卡")
    ap.add_argument("--no-brake", action="store_true",
                    help="不刹车：滑完让屏幕自己惯性滑行（默认会立刻刹住，做到“滑 100ms 即停”）")
    ap.add_argument("--tb-swipe-duration", type=int, default=700, help="（已废弃）淘宝现在跟随 --swipe-duration")
    ap.add_argument("--tb-y1", type=float, default=0.81, help="（已废弃）淘宝现在跟随 --y1")
    ap.add_argument("--tb-y2", type=float, default=0.51, help="（已废弃）淘宝现在跟随 --y2")
    ap.add_argument("--tb-keep", action="store_true",
                    help="淘宝采完不关 TalkBack（默认采完即关，TalkBack 只在淘宝采集期间用）")
    ap.add_argument("--jd-settle", type=float, default=0.3,
                    help="京东滑完后停留多久再读，默认 0.3 秒（比美团/淘宝长一点）")
    ap.add_argument("--jd-y1", type=float, default=0.86, help="京东滑动起点占屏高比例")
    ap.add_argument("--jd-y2", type=float, default=0.49,
                    help="京东滑动终点；0.86→0.49 约 1000px，一次滑过一整张评价卡")
    ap.add_argument("--jd-swipe-duration", type=int, default=500,
                    help="京东一次上滑时长，默认 500ms（慢速长滑，滑到位再停，避免惯性跳卡）")
    ap.add_argument("--jd-ocr", dest="jd_ocr_mode", action="store_true",
                    help="京东改走截图 OCR + 数红星（默认走无障碍；这页无障碍常只有粗节点）")
    ap.add_argument("--tb-off", action="store_true",
                    help="只关闭「触摸探索」，恢复正常单指单击，不采集")
    ap.add_argument("--tb-sound", action="store_true",
                    help="淘宝采集时保留媒体音量（默认临时静音，避免 TalkBack 一直朗读界面）")
    ap.add_argument("--poll", type=float, default=0.30, help="PC 读取无障碍流的间隔秒数")
    ap.add_argument("--max-reviews", type=int, default=80, help="达到多少条停止；0 表示不限")
    ap.add_argument("--max-seconds", type=float, default=75.0, help="最长采集秒数；0 表示不限")
    ap.add_argument("--idle-stop", type=float, default=12.0, help="连续多少秒没有新评价就停；0 表示不停")
    ap.add_argument("--no-page", action="store_true", help="不生成预载分析页")
    ap.add_argument("--ocr", action="store_true", help="淘宝改走截图 OCR（默认走 Flutter 语义树无障碍读取）")
    ap.add_argument("--repair", action="store_true",
                    help="只重启无障碍助手服务（修复采集完淘宝后其他 App 读不到的问题）")
    args = ap.parse_args()

    adb = find_adb(args.adb)
    if not adb:
        log("找不到 adb。请用工具包里的 adb/platform-tools/adb.exe，或设环境变量 ADB。")
        return 1
    dev = Adb(adb, args.serial or "")
    devs = dev.devices()
    if not devs:
        log("没有检测到已授权设备。请解锁手机，确认 USB 调试弹窗已点“允许”。")
        return 1
    if not dev.serial:
        dev.serial = devs[0]
    if args.tb_off:
        services = tb.get_enabled_services(dev)
        tb.restore_services(dev, services, log)
        log("已关闭「触摸探索」：单指单击恢复正常，口碑小探的服务仍在。")
        return 0
    if args.repair:
        if not service_enabled(dev):
            tb.set_enabled_services(dev, [tb.HELPER_SERVICE])
        kept = repair_service(dev)
        log("已重启无障碍助手服务：" + " | ".join(s.split("/")[0] for s in kept))
        log("现在回到评价页点“开始连续采集”即可。")
        return 0

    fg = foreground_package(dev)
    if fg == tb.TAOBAO_PKG and not args.ocr:
        return run_taobao_a11y(adb, dev, args)
    if fg == JD_PKG and not args.ocr:
        # 京东默认走无障碍；滑得比美团/淘宝小一点（一次约一张卡），滑完停 300ms 再读。
        # 这两条设置对 OCR 兜底路径同样生效。
        args.settle = args.jd_settle if args.jd_settle is not None else 0.3
        args.y1, args.y2 = args.jd_y1, args.jd_y2
        args.swipe_duration = args.jd_swipe_duration
        args.brake = True  # 滑完立刻刹住，不靠惯性
        if getattr(args, "jd_ocr_mode", False):
            return run_jd_ocr(adb, dev, args)
        # 不预滑回顶：就从你手机当前停留的位置开始读，滑多少由下面的节奏决定。
        w, h = dev.screen_size()
        log(f"京东走无障碍读取；每滑 {abs(args.jd_y1 - args.jd_y2) * h:.0f}px / "
            f"{args.swipe_duration}ms / 滑完立刻刹住 / 停 {args.settle * 1000:.0f}ms 再读快照。")
    if not service_enabled(dev):
        # 淘宝 dump 之后 HyperOS 有时会直接把这个服务从启用列表里摘掉，
        # 表现为“设置里明明开过，现在没了”。这里自动补回去，不用你手动进设置。
        svc = tb.get_enabled_services(dev)
        tb.set_enabled_services(dev, svc + [tb.HELPER_SERVICE])
        log("助手服务被系统从启用列表摘掉了（淘宝采集的后遗症），已自动补回，稍等重连……")
        time.sleep(2.5)
    if not service_enabled(dev):
        log("无障碍服务没有启用。请先安装 a11y_helper.apk，并在系统无障碍设置里打开“口碑小探评价读取”。")
        return 1

    try:
        stream = read_stream(dev)
    except Exception as exc:
        log(str(exc))
        return 1
    # 淘宝采集会把助手的事件流顶掉：切回美团/点评后助手“绑着但不写快照”。
    # 启动时看一眼最后一条快照来自淘宝，就趁前台已经是目标 App 时先修一次。
    if last_snap_pkg(stream) == tb.TAOBAO_PKG:
        log("上一条快照停在淘宝（淘宝采集顶掉了事件流），先重启一次读取服务再采……")
        try:
            repair_service(dev)
            time.sleep(3.0)
            stream = read_stream(dev)
        except Exception as exc:
            log(f"自动重启失败：{exc}")
    if not stream.strip():
        log("无障碍流是空的，先自动重启一次服务……")
        try:
            repair_service(dev)
            time.sleep(3.0)
            stream = read_stream(dev)
        except Exception as exc:
            log(f"自动重启失败：{exc}")
    if not stream.strip():
        log("还是空的。请在评价页上下滑一下，让服务产生快照再重跑；或到系统无障碍里手动开关一次“口碑小探评价读取”。")
        return 1

    out_dir = Path(args.out) if args.out else make_out_dir("无障碍采集")
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"设备：{dev.serial}")
    log(f"输出：{out_dir}")

    # 先把当前屏幕解析出来，避免“开始采集时已有一屏”被跳过
    stats = CollectStats()
    snaps, last_seq, _ = parse_stream(stream, 0, initial_latest=True)
    all_rows = rows_from_snaps(snaps, stats=stats)
    log(f"当前屏快照 {len(snaps)} 个，解析出 {len(all_rows)} 条")

    last_len = len(stream)
    last_new_at = time.time()
    last_write_at = 0.0
    stop_event = threading.Event()
    error_box = []
    if args.dump_only:
        stop_event.set()
        log("只解析现有快照，不滑动。")

    w, h = dev.screen_size()
    if not args.manual and not args.dump_only:
        step = int(abs(args.y1 - args.y2) * h)
        brake = "不刹车" if getattr(args, "no_brake", False) else "滑完立刻刹住"
        log(f"屏幕 {w}x{h}；每滑 {step}px / {args.swipe_duration}ms / {brake} / 停 "
            f"{args.settle * 1000:.0f}ms 读快照；{args.start_delay:g}s 后开始")
        if args.start_delay > 0:
            time.sleep(args.start_delay)
        t = threading.Thread(
            target=scroll_loop,
            args=(dev, w, h, args, stop_event, error_box),
            daemon=True,
        )
        t.start()
    elif args.manual:
        log("手动模式：请自己在手机上滑；手机端会持续读取，按 Ctrl+C 结束。")

    started_at = time.time()
    last_status = 0.0
    last_snap_at = time.time()   # 最后一次收到快照的时间（判“服务僵死”只看这个）
    repaired = [False]
    try:
        while not stop_event.is_set():
            if args.max_seconds and time.time() - started_at >= args.max_seconds:
                log("到达最长采集时间，停止。")
                break
            if args.max_reviews and len(merge_ui_rows(all_rows)) >= args.max_reviews:
                log("达到目标评价数，停止。")
                break
            try:
                stream = read_stream(dev)
            except Exception as exc:
                log(f"读取中断：{exc}")
                break

            # 服务重启或文件被截断时，seq 会重置；重新从头取
            if last_len and len(stream) < last_len:
                last_seq = 0
                log("检测到无障碍流重启，重新读取。")
            last_len = len(stream)

            new_snaps, last_seq, _ = parse_stream(stream, last_seq)
            if new_snaps:
                last_snap_at = time.time()
                new_rows = rows_from_snaps(new_snaps, stats=stats)
                all_rows.extend(new_rows)
                if new_rows:
                    last_new_at = time.time()
                    log(f"快照 +{len(new_snaps)}，新增 {len(new_rows)} 条，累计 {len(merge_ui_rows(all_rows))} 条")
                elif time.time() - last_status > 2.0:
                    log(f"快照 +{len(new_snaps)}（这一屏暂时没有完整评价）")
                    last_status = time.time()

            # 服务僵死自愈：连续 10 秒一条快照都收不到才重启。
            # 有快照、只是这一屏没有完整评价，不算僵死——别去开关服务。
            if (not args.dump_only) and (not repaired[0]) and time.time() - started_at >= 12.0 \
                    and time.time() - last_snap_at >= 10.0 and not new_snaps:
                repaired[0] = True
                log("10 秒内没有任何快照，疑似无障碍服务僵死，自动重启服务……")
                try:
                    kept = repair_service(dev)
                    log("已重启无障碍助手服务：" + " | ".join(s.split("/")[0] for s in kept))
                    last_seq = 0
                    last_len = 0
                    last_new_at = time.time()
                    time.sleep(2.0)
                    continue
                except Exception as exc:
                    log(f"自动重启失败：{exc}")

            # 定期落盘，Demo 可以边采边看
            if time.time() - last_write_at >= 1.5:
                last_write_at = time.time()
                rows = merge_ui_rows(all_rows)
                src = dominant_source(rows)
                write_outputs(rows, out_dir, src, shop_name=args.shop_name,
                              make_page=not args.no_page, stats=stats)

            if args.idle_stop and len(merge_ui_rows(all_rows)) >= 1 and time.time() - last_new_at >= args.idle_stop:
                log(f"连续 {args.idle_stop:g}s 没有新增评价，停止。")
                break
            time.sleep(args.poll)
    except KeyboardInterrupt:
        log("收到 Ctrl+C，停止采集。")
    finally:
        stop_event.set()

    if error_box:
        log("\n" + error_box[0])

    rows = merge_ui_rows(all_rows)
    src = dominant_source(rows)
    full, demo, page = write_outputs(rows, out_dir, src, shop_name=args.shop_name,
                                     make_page=not args.no_page, stats=stats)
    log_stats(rows, stats, "完成")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    if len(rows) < 10:
        log("提示：Demo 上传至少需要 10 条；可以多滑一会儿，或把 --max-seconds 调大。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
