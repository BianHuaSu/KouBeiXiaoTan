#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""安装 / 启用“口碑小探评价读取”无障碍辅助 App。

用法：
  python a11y_setup.py                 # 安装并启用服务
  python a11y_setup.py --check         # 只检查状态
  python a11y_setup.py --apk 某个.apk   # 指定 APK

说明：
- 只把 com.koubei.a11y 追加到 enabled_accessibility_services，不覆盖小跳跳/小米钱包等其他服务；
- 服务监听大众点评 / 美团 / 饿了么 / 京东（见 a11y_app/res/xml/a11y_config.xml）；
- PC 端通过 run-as 读取 App 内部 a11y_stream.jsonl；APK 是 debuggable 的 debug 包。
"""

import argparse
import sys
from pathlib import Path

from adb_collect import Adb, find_adb, log

APP_DIR = Path(__file__).resolve().parent
APP_PKG = "com.koubei.a11y"
SERVICE = "com.koubei.a11y/com.koubei.a11y.ReviewAccessibilityService"


def get_devices(adb_path, serial=""):
    dev = Adb(adb_path, serial or "")
    devs = dev.devices()
    if not devs:
        log("没有检测到已授权设备。请解锁手机，确认 USB 调试弹窗已点“允许”。")
        return None, []
    if not dev.serial:
        dev.serial = devs[0]
    return dev, devs


def is_installed(dev):
    r = dev.shell(["pm", "path", APP_PKG])
    return "package:" in ((r.stdout or "") + (r.stderr or ""))


def install_apk(dev, apk):
    log(f"安装 {apk.name} ...")
    r = dev.run(["install", "--no-streaming", "-r", str(apk)])
    out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    log(out)
    if r.returncode != 0 or "Success" not in out:
        if "INSTALL_FAILED_USER_RESTRICTED" in out:
            log("手机拦截了安装。请在手机上关闭“监控安装应用/安装验证”，或手动点允许后重试。")
        return False
    dev.shell(["pm", "enable", APP_PKG])
    return True


def enable_service(dev):
    r = dev.shell(["settings", "get", "secure", "enabled_accessibility_services"])
    current = (r.stdout or "").strip()
    parts = [p for p in current.split(":") if p and p != "null"]
    if SERVICE not in parts:
        parts.append(SERVICE)
    value = ":".join(parts)
    dev.shell(["settings", "put", "secure", "enabled_accessibility_services", value])
    dev.shell(["settings", "put", "secure", "accessibility_enabled", "1"])
    log("已写入无障碍服务列表：" + value)
    log("如果系统没有自动绑定，请到 设置 → 无障碍 → 已下载的服务，手动打开“口碑小探评价读取”。")


def check(dev):
    log("—— 状态检查 ——")
    log("设备：" + dev.serial)
    log("已安装：" + ("是" if is_installed(dev) else "否"))
    r = dev.shell(["settings", "get", "secure", "enabled_accessibility_services"])
    log("服务列表：" + ((r.stdout or "").strip() or "(空)"))
    r = dev.shell(["dumpsys", "accessibility"])
    text = (r.stdout or "") + (r.stderr or "")
    log("已绑定：" + ("是" if "com.koubei.a11y" in text and "Bound services" in text else "未确认"))
    r = dev.shell(["run-as", APP_PKG, "ls", "-l", "files"])
    log("内部文件：\n" + ((r.stdout or "") + (r.stderr or "")).strip())


def main():
    ap = argparse.ArgumentParser(description="安装并启用手机无障碍评价读取服务")
    ap.add_argument("--adb", help="adb.exe 路径")
    ap.add_argument("--serial", help="设备序列号")
    ap.add_argument("--apk", help="辅助 APK；默认用同目录 a11y_helper.apk")
    ap.add_argument("--check", action="store_true", help="只检查状态")
    ap.add_argument("--no-enable", action="store_true", help="只安装，不自动开服务")
    args = ap.parse_args()

    adb = find_adb(args.adb)
    if not adb:
        log("找不到 adb。")
        return 1
    dev, devices = get_devices(adb, args.serial)
    if not dev:
        return 1
    if args.check:
        check(dev)
        return 0

    apk = Path(args.apk) if args.apk else (APP_DIR / "a11y_helper.apk")
    if not apk.exists():
        apk = APP_DIR / "手机评价采集工具" / "a11y_helper.apk"
    if not apk.exists():
        log(f"找不到辅助 APK：{apk}")
        log("请确认工具包根目录里有 a11y_helper.apk。")
        return 1

    if not install_apk(dev, apk):
        return 1
    if not args.no_enable:
        enable_service(dev)
    check(dev)
    log("\n下一步：手机打开大众点评 / 美团 / 饿了么 / 京东的店铺评价页，然后运行 a11y_collect.py。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
