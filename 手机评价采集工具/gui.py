#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机评价采集器 · 图形界面（无障碍边滑边读 + ADB 界面树 + 截图 OCR）。"""

import os
import re
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
ADB = BASE_DIR / "adb" / "platform-tools" / "adb.exe"
OUTPUT_DIR = BASE_DIR / "output"

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class App:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.busy = False
        self.out_path = None
        self.page_path = None
        self.manual_out = None

        root.title("手机评价采集器")
        root.geometry("920x720")
        root.minsize(820, 640)
        root.configure(bg="#f5f7f6")

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TFrame", background="#f5f7f6")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("TLabel", background="#f5f7f6", foreground="#1f2937", font=("Microsoft YaHei UI", 10))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 17, "bold"), foreground="#0f766e")
        style.configure("Hint.TLabel", foreground="#64748b", font=("Microsoft YaHei UI", 9))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 6))
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 10, "bold"), padding=(14, 7))
        style.configure("TNotebook", background="#f5f7f6")
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=(14, 7))

        outer = ttk.Frame(root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="手机评价采集器", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="无障碍服务边滑边读 + ADB 界面树 + 截图 OCR。只读你手动打开、且有权访问的页面；不登录、不破解验证、不逆向 App 接口。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        self.nb = ttk.Notebook(outer)
        self.nb.pack(fill="both", expand=True)
        self.tab_a11y = ttk.Frame(self.nb, padding=12)
        self.tab_adb = ttk.Frame(self.nb, padding=12)
        self.tab_ocr = ttk.Frame(self.nb, padding=12)
        self.nb.add(self.tab_a11y, text="无障碍连续采集")
        self.nb.add(self.tab_adb, text="安卓 ADB 采集")
        self.nb.add(self.tab_ocr, text="截图 OCR 导入")

        self.build_a11y()
        self.build_adb()
        self.build_ocr()

        self.status = ttk.Label(outer, text="就绪", style="Hint.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------- 无障碍 ----------------
    def build_a11y(self):
        card = ttk.Frame(self.tab_a11y, style="Card.TFrame", padding=14)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="设备", background="#ffffff").grid(row=0, column=0, sticky="w", pady=5)
        self.a11y_device = ttk.Combobox(card, state="readonly", width=34)
        self.a11y_device.grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=5)
        ttk.Button(card, text="检测设备", command=self.refresh_devices).grid(row=0, column=2, sticky="e", pady=5)

        ttk.Label(
            card,
            text="先安装并启用“口碑小探评价读取”无障碍服务，再打开大众点评/美团/饿了么/京东/淘宝评价页。大众点评/美团/饿了么/京东由手机端服务在页面滚动时持续读节点；淘宝是 Flutter 自绘页，需要系统触摸探索，工具只在你采淘宝时开一次 TalkBack，采完立刻关掉（单指单击恢复正常），平时不占着、不影响其他 App 和日常使用。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))

        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=2, column=0, columnspan=3, sticky="w")
        self.a11y_max = tk.IntVar(value=80)
        self.a11y_seconds = tk.IntVar(value=75)
        self.a11y_delay = tk.IntVar(value=3)
        self.a11y_idle = tk.IntVar(value=8)
        for i, (label, var, frm, to) in enumerate([
            ("最多采集", self.a11y_max, 10, 500),
            ("最长秒数", self.a11y_seconds, 10, 300),
            ("开始倒计时", self.a11y_delay, 0, 30),
            ("静默停止", self.a11y_idle, 0, 30),
        ]):
            box = ttk.Frame(opts, style="Card.TFrame")
            box.grid(row=0, column=i, padx=(0, 18))
            ttk.Label(box, text=label, background="#ffffff").pack(anchor="w")
            ttk.Spinbox(box, from_=frm, to=to, textvariable=var, width=7).pack(anchor="w", pady=(2, 0))

        actions = ttk.Frame(self.tab_a11y)
        actions.pack(fill="x", pady=10)
        self.a11y_setup = ttk.Button(actions, text="安装/启用无障碍包", command=self.setup_a11y)
        self.a11y_setup.pack(side="left")
        self.a11y_start = ttk.Button(actions, text="开始连续采集", style="Primary.TButton", command=lambda: self.start_a11y(False))
        self.a11y_start.pack(side="left", padx=(10, 0))
        self.a11y_manual = ttk.Button(actions, text="手动滑动采集", command=lambda: self.start_a11y(True))
        self.a11y_manual.pack(side="left", padx=(8, 0))
        self.a11y_repair = ttk.Button(actions, text="修复读取服务", command=self.repair_a11y)
        self.a11y_repair.pack(side="left", padx=(8, 0))
        self.a11y_one = ttk.Button(actions, text="只解析当前快照", command=self.capture_a11y_one)
        self.a11y_one.pack(side="left", padx=(8, 0))
        self.a11y_stop = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.a11y_stop.pack(side="left", padx=8)
        self.a11y_open = ttk.Button(actions, text="打开输出目录", command=self.open_output, state="disabled")
        self.a11y_open.pack(side="left", padx=8)
        self.a11y_page = ttk.Button(actions, text="打开分析页", command=self.open_page, state="disabled")
        self.a11y_page.pack(side="left")
        self.a11y_tboff = ttk.Button(actions, text="关闭淘宝读取模式", command=self.tb_mode_off)
        self.a11y_tboff.pack(side="left", padx=(8, 0))

        ttk.Label(self.tab_a11y, text="运行日志", style="Hint.TLabel").pack(anchor="w")
        self.a11y_log = self.make_log(self.tab_a11y)
        self.a11y_log.pack(fill="both", expand=True, pady=(4, 0))
        self.log_a11y("第 1 步：点“安装/启用无障碍包”。第 2 步：手机打开大众点评/美团/饿了么/京东/淘宝评价页。第 3 步：点“开始连续采集”。")
        self.log_a11y("淘宝会自动切到“Flutter 语义树”读取：采集时开一次 TalkBack，采完立刻关掉，采集期间自动静音；开启这一刻单指点击会变双击，采完即恢复。")

    # ---------------- ADB ----------------
    def build_adb(self):
        card = ttk.Frame(self.tab_adb, style="Card.TFrame", padding=14)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="设备", background="#ffffff").grid(row=0, column=0, sticky="w", pady=5)
        self.device = ttk.Combobox(card, state="readonly", width=34)
        self.device.grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=5)
        self.refresh_btn = ttk.Button(card, text="检测设备", command=self.refresh_devices)
        self.refresh_btn.grid(row=0, column=2, sticky="e", pady=5)

        ttk.Label(
            card,
            text="先在手机上打开 App，手动登录并进入店铺评价页；点开始后有倒计时，采集期间不要锁屏。这里仍是界面树逐屏快照（滑一屏读一屏）；要真正边滑边读请用“无障碍连续采集”标签。需要逐条真实半星再勾“截图校准星级”。小米/Redmi 需另开「USB调试（安全设置）」。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 8))

        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=2, column=0, columnspan=3, sticky="w")
        self.max_reviews = tk.IntVar(value=80)
        self.max_swipes = tk.IntVar(value=20)
        self.start_delay = tk.IntVar(value=5)
        self.swipe_ms = tk.IntVar(value=320)
        for i, (label, var, frm, to) in enumerate([
            ("最多采集", self.max_reviews, 10, 500),
            ("最多滑动", self.max_swipes, 0, 100),
            ("开始倒计时", self.start_delay, 0, 30),
            ("滑动时长(ms)", self.swipe_ms, 200, 2000),
        ]):
            box = ttk.Frame(opts, style="Card.TFrame")
            box.grid(row=0, column=i, padx=(0, 18))
            ttk.Label(box, text=label, background="#ffffff").pack(anchor="w")
            ttk.Spinbox(box, from_=frm, to=to, textvariable=var, width=7).pack(anchor="w", pady=(2, 0))

        mode_box = ttk.Frame(opts, style="Card.TFrame")
        mode_box.grid(row=0, column=4)
        ttk.Label(mode_box, text="一屏几条", background="#ffffff").pack(anchor="w")
        self.adb_mode = ttk.Combobox(mode_box, values=["一屏多条（推荐）", "一图一条"], state="readonly", width=16)
        self.adb_mode.current(0)
        self.adb_mode.pack(anchor="w", pady=(2, 0))

        engine_box = ttk.Frame(card, style="Card.TFrame")
        engine_box.grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))
        ttk.Label(engine_box, text="解析方式", background="#ffffff").pack(side="left")
        self.adb_engine = ttk.Combobox(engine_box, values=["界面树（推荐，准确切条）", "截图 OCR（兼容旧手机）"], state="readonly", width=26)
        self.adb_engine.current(0)
        self.adb_engine.pack(side="left", padx=(8, 0))
        self.shot_calib = tk.BooleanVar(value=False)
        ttk.Checkbutton(engine_box, text="截图校准星级（可选，慢）", variable=self.shot_calib).pack(side="left", padx=(12, 0))

        actions = ttk.Frame(self.tab_adb)
        actions.pack(fill="x", pady=10)
        self.adb_start = ttk.Button(actions, text="开始采集", style="Primary.TButton", command=self.start_adb)
        self.adb_start.pack(side="left")
        self.adb_one = ttk.Button(actions, text="抓当前屏（手动逐屏）", command=self.capture_one)
        self.adb_one.pack(side="left", padx=(10, 0))
        self.adb_stop = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.adb_stop.pack(side="left", padx=8)
        self.adb_open = ttk.Button(actions, text="打开输出目录", command=self.open_output, state="disabled")
        self.adb_open.pack(side="left", padx=8)
        self.adb_page = ttk.Button(actions, text="打开分析页", command=self.open_page, state="disabled")
        self.adb_page.pack(side="left")

        ttk.Label(self.tab_adb, text="运行日志", style="Hint.TLabel").pack(anchor="w")
        self.adb_log = self.make_log(self.tab_adb)
        self.adb_log.pack(fill="both", expand=True, pady=(4, 0))
        self.log_adb("提示：手机需开启“开发者选项 → USB 调试”，连接后在手机上点“允许”。")
        self.log_adb("采集范围是你当前屏幕能看到的评论；遇到登录/验证请先在手机上手动完成。")

    # ---------------- OCR ----------------
    def build_ocr(self):
        card = ttk.Frame(self.tab_ocr, style="Card.TFrame", padding=14)
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text="截图文件夹", background="#ffffff").grid(row=0, column=0, sticky="w", pady=5)
        self.ocr_input = ttk.Entry(card)
        self.ocr_input.grid(row=0, column=1, sticky="ew", padx=(10, 8), pady=5)
        ttk.Button(card, text="选择…", command=self.choose_input).grid(row=0, column=2, pady=5)

        ttk.Label(card, text="输出目录", background="#ffffff").grid(row=1, column=0, sticky="w", pady=5)
        self.ocr_out = ttk.Entry(card)
        self.ocr_out.grid(row=1, column=1, sticky="ew", padx=(10, 8), pady=5)
        ttk.Button(card, text="选择…", command=self.choose_out).grid(row=1, column=2, pady=5)

        opts = ttk.Frame(card, style="Card.TFrame")
        opts.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))
        mode_box = ttk.Frame(opts, style="Card.TFrame")
        mode_box.grid(row=0, column=0, padx=(0, 18))
        ttk.Label(mode_box, text="截图类型", background="#ffffff").pack(anchor="w")
        self.ocr_mode = ttk.Combobox(mode_box, values=["整屏多条评论（推荐）", "每张截图一条评论"], state="readonly", width=22)
        self.ocr_mode.current(0)
        self.ocr_mode.pack(anchor="w", pady=(2, 0))

        crop_box = ttk.Frame(opts, style="Card.TFrame")
        crop_box.grid(row=0, column=1)
        ttk.Label(crop_box, text="裁剪比例（上,下,左,右）", background="#ffffff").pack(anchor="w")
        self.crop = ttk.Entry(crop_box, width=24)
        self.crop.insert(0, "0,0,0,0")
        self.crop.pack(anchor="w", pady=(2, 0))
        ttk.Label(opts, text="一般保持 0,0,0,0；状态栏文字会被自动过滤。", style="Hint.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        actions = ttk.Frame(self.tab_ocr)
        actions.pack(fill="x", pady=10)
        self.ocr_start = ttk.Button(actions, text="开始 OCR", style="Primary.TButton", command=self.start_ocr)
        self.ocr_start.pack(side="left")
        self.ocr_stop = ttk.Button(actions, text="停止", command=self.stop, state="disabled")
        self.ocr_stop.pack(side="left", padx=8)
        self.ocr_open = ttk.Button(actions, text="打开输出目录", command=self.open_output, state="disabled")
        self.ocr_open.pack(side="left", padx=8)
        self.ocr_page = ttk.Button(actions, text="打开分析页", command=self.open_page, state="disabled")
        self.ocr_page.pack(side="left")

        ttk.Label(self.tab_ocr, text="运行日志", style="Hint.TLabel").pack(anchor="w")
        self.ocr_log = self.make_log(self.tab_ocr)
        self.ocr_log.pack(fill="both", expand=True, pady=(4, 0))
        self.log_ocr("适用：手机截图或录屏抽帧。整屏多条会按日期/间距切分；一张一条则整屏文字作为一条。")

    def make_log(self, parent):
        return ScrolledText(
            parent, height=14, font=("Consolas", 9), bg="#0f172a", fg="#d1fae5",
            insertbackground="#d1fae5", relief="flat", padx=10, pady=8,
        )

    # ---------------- 日志/进程 ----------------
    def log_adb(self, text):
        self.adb_log.insert("end", str(text).rstrip() + "\n")
        self.adb_log.see("end")

    def log_a11y(self, text):
        self.a11y_log.insert("end", str(text).rstrip() + "\n")
        self.a11y_log.see("end")

    def log_ocr(self, text):
        self.ocr_log.insert("end", str(text).rstrip() + "\n")
        self.ocr_log.see("end")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.a11y_start, self.a11y_manual, self.a11y_one, self.a11y_setup,
                  self.adb_start, self.ocr_start, self.refresh_btn):
            b.configure(state=state)
        self.a11y_stop.configure(state="normal" if busy else "disabled")
        self.adb_stop.configure(state="normal" if busy else "disabled")
        self.ocr_stop.configure(state="normal" if busy else "disabled")

    def _run(self, args, on_line, done):
        if self.busy:
            messagebox.showinfo("正在运行", "当前任务还没结束，请先停止或等它完成。")
            return
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self.out_path = None
        self.page_path = None
        self.a11y_open.configure(state="disabled")
        self.adb_open.configure(state="disabled")
        self.ocr_open.configure(state="disabled")
        self.a11y_page.configure(state="disabled")
        self.adb_page.configure(state="disabled")
        self.ocr_page.configure(state="disabled")
        self.set_busy(True)

        def worker():
            try:
                self.proc = subprocess.Popen(
                    [PYTHON, "-u"] + args,
                    cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                    creationflags=CREATE_NO_WINDOW,
                )
                for line in self.proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    self.root.after(0, on_line, line)
                    if line.startswith("完整数据：") or line.startswith("Demo 上传用："):
                        self.out_path = str(Path(line.split("：", 1)[1].strip()).parent)
                        self.a11y_open.configure(state="normal")
                        self.adb_open.configure(state="normal")
                        self.ocr_open.configure(state="normal")
                    if line.startswith("预载分析页："):
                        self.page_path = line.split("：", 1)[1].strip()
                        self.a11y_page.configure(state="normal")
                        self.adb_page.configure(state="normal")
                        self.ocr_page.configure(state="normal")
                code = self.proc.wait()
                if code == 0:
                    self.root.after(0, on_line, done)
                else:
                    self.root.after(0, on_line, f"进程结束，返回码 {code}。")
            except Exception as e:
                self.root.after(0, on_line, f"启动失败：{e}")
            finally:
                self.proc = None
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=worker, daemon=True).start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.status.configure(text="已停止")

    def open_output(self):
        path = self.out_path if self.out_path and Path(self.out_path).is_dir() else OUTPUT_DIR
        if Path(path).is_dir():
            os.startfile(str(path))
        else:
            messagebox.showinfo("暂无输出", "还没有生成结果目录，先运行一次采集。")

    def open_page(self):
        if self.page_path and Path(self.page_path).exists():
            os.startfile(self.page_path)
        else:
            messagebox.showinfo("暂无分析页", "采集到 10 条以上才会生成预载分析页；也可以打开 Demo 手动上传 CSV。")

    # ---------------- ADB 操作 ----------------
    def refresh_devices(self):
        adb = str(ADB) if ADB.exists() else "adb"
        try:
            r = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=12, creationflags=CREATE_NO_WINDOW)
            out = (r.stdout or "") + "\n" + (r.stderr or "")
        except Exception as e:
            self.log_adb(f"检测失败：{e}")
            return
        serials = []
        for line in out.splitlines():
            line = line.strip()
            m = re.match(r"^(\S+)\s+device\b", line)
            if m:
                serials.append(m.group(1))
            elif re.match(r"^(\S+)\s+unauthorized\b", line):
                self.log_adb(f"未授权：{line}（请在手机上点允许 USB 调试）")
        self.device["values"] = serials
        self.a11y_device["values"] = serials
        if serials:
            self.device.current(0)
            self.a11y_device.current(0)
            self.log_adb(f"检测到设备：{', '.join(serials)}")
            self.log_a11y(f"检测到设备：{', '.join(serials)}")
            self.status.configure(text=f"已连接 {len(serials)} 台设备")
        else:
            self.log_adb("没有检测到已授权设备。")
            self.status.configure(text="未检测到设备")

    @staticmethod
    def _read_int(var, default):
        try:
            return int(str(var.get()).strip())
        except (TypeError, ValueError):
            return default

    def _a11y_serial(self):
        serial = self.a11y_device.get().strip()
        if not serial:
            messagebox.showwarning("没有设备", "先点“检测设备”，并在手机上允许 USB 调试。")
        return serial

    def setup_a11y(self):
        serial = self._a11y_serial()
        if not serial:
            return
        self.log_a11y(f"安装并启用无障碍包：{serial}")
        args = ["a11y_setup.py", "--serial", serial]
        self._run(args, self.log_a11y, "无障碍包安装/启用完成。请到手机系统无障碍设置确认服务已打开。")

    def repair_a11y(self):
        """货架上加一个“修复读取服务”：重启无障碍服务，修淘宝采集后读不到的问题。"""
        serial = self._a11y_serial()
        if not serial:
            return
        self.log_a11y("正在重启无障碍读取服务……（手机上请先停在要采集的评价页）")
        args = ["a11y_collect.py", "--serial", serial, "--repair"]
        self._run(args, self.log_a11y, "服务已重启。现在回到评价页点“开始连续采集”即可。")

    def tb_mode_off(self):
        """淘宝读取模式用得少了想恢复单指单击时点这个；采集过程本身不会反复开关。"""
        serial = self._a11y_serial()
        if not serial:
            return
        self.log_a11y("正在关闭淘宝读取模式（触摸探索），恢复单指单击……")
        args = ["a11y_collect.py", "--serial", serial, "--tb-off"]
        self._run(args, self.log_a11y, "已关闭淘宝读取模式，单指单击恢复正常。")

    def start_a11y(self, manual=False):
        serial = self._a11y_serial()
        if not serial:
            return
        seconds = max(10, self._read_int(self.a11y_seconds, 75))
        delay = max(0, self._read_int(self.a11y_delay, 3))
        idle = max(0, self._read_int(self.a11y_idle, 8))
        max_reviews = max(10, self._read_int(self.a11y_max, 80))
        args = [
            "a11y_collect.py", "--serial", serial,
            "--max-seconds", str(seconds),
            "--start-delay", str(delay),
            "--idle-stop", str(idle),
            "--max-reviews", str(max_reviews),
        ]
        if manual:
            args.append("--manual")
            self.log_a11y("手动滑动模式：手机端持续读取，你负责滑动。")
        else:
            self.log_a11y("连续滑动模式：手机端边滑边读，不再逐屏 dump。")
        self._run(args, self.log_a11y, "采集完成。Demo 可直接上传 reviews_demo.csv。")

    def capture_a11y_one(self):
        serial = self._a11y_serial()
        if not serial:
            return
        self._run(
            ["a11y_collect.py", "--serial", serial, "--dump-only"],
            self.log_a11y,
            "已解析手机里现有快照。",
        )

    def start_adb(self):
        serial = self.device.get().strip()
        if not serial:
            messagebox.showwarning("没有设备", "先点“检测设备”，并在手机上允许 USB 调试。")
            return
        use_ui = "界面树" in self.adb_engine.get()
        self.manual_out = None
        max_reviews = max(10, self._read_int(self.max_reviews, 80))
        swipes = max(0, self._read_int(self.max_swipes, 20))
        delay = max(0, self._read_int(self.start_delay, 5))
        duration = max(200, self._read_int(self.swipe_ms, 320))
        if use_ui:
            args = [
                "uiauto_collect.py", "--serial", serial,
                "--max-reviews", str(max_reviews),
                "--max-screens", str(max(1, swipes + 1)),
                "--start-delay", str(delay),
                "--swipe-duration", str(duration),
            ]
            if self.shot_calib.get():
                args.append("--with-shots")
            self.log_adb(f"开始界面树采集：{serial}")
        else:
            mode = "card" if "一图一条" in self.adb_mode.get() else "screen"
            args = [
                "adb_collect.py", "--serial", serial,
                "--max-reviews", str(max_reviews),
                "--max-swipes", str(swipes),
                "--start-delay", str(delay),
                "--swipe-duration", str(duration),
                "--mode", mode,
            ]
            self.log_adb(f"开始 OCR 采集：{serial}")
        self._run(args, self.log_adb, "采集完成。打开输出目录查看 CSV。")

    def capture_one(self):
        """手动逐屏：你在手机上滑到下一屏，点一次按钮，结果追加到同一批。"""
        serial = self.device.get().strip()
        if not serial:
            messagebox.showwarning("没有设备", "先点“检测设备”，并在手机上允许 USB 调试。")
            return
        if "界面树" not in self.adb_engine.get():
            messagebox.showinfo("先切界面树", "手动逐屏用的是界面树解析；请把“解析方式”切成“界面树（推荐，准确切条）”。")
            return
        if self.manual_out is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.manual_out = OUTPUT_DIR / f"{stamp}_手动逐屏"
        args = [
            "uiauto_collect.py", "--serial", serial,
            "--max-reviews", "500", "--max-screens", "1",
            "--single-screen", "--append",
            "--out", str(self.manual_out),
            "--start-delay", "0", "--swipe-duration", "320",
        ]
        if self.shot_calib.get():
            args.append("--with-shots")
        self.log_adb(f"抓取当前屏，追加到：{self.manual_out.name}")
        self._run(args, self.log_adb, "当前屏已追加。滑到下一屏，再点一次“抓当前屏”。")

    # ---------------- OCR 操作 ----------------
    def choose_input(self):
        p = filedialog.askdirectory(title="选择截图文件夹")
        if p:
            self.ocr_input.delete(0, "end")
            self.ocr_input.insert(0, p)

    def choose_out(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.ocr_out.delete(0, "end")
            self.ocr_out.insert(0, p)

    def start_ocr(self):
        inp = self.ocr_input.get().strip()
        if not inp or not Path(inp).exists():
            messagebox.showwarning("缺少截图", "先选择包含截图的文件夹。")
            return
        mode = "card" if "每张" in self.ocr_mode.get() else "screen"
        args = ["ocr_collect.py", "--input", inp, "--mode", mode, "--crop", self.crop.get().strip() or "0,0,0,0"]
        out = self.ocr_out.get().strip()
        if out:
            args += ["--out", out]
        self.log_ocr(f"开始 OCR：{inp}")
        self._run(args, self.log_ocr, "OCR 完成。打开输出目录查看 CSV。")

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("正在运行", "任务还没结束，确定退出并终止吗？"):
                return
            try:
                self.proc.terminate()
            except Exception:
                pass
        self.root.destroy()


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
