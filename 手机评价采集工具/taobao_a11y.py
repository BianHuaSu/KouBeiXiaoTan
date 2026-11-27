#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""淘宝评价页的真·无障碍读取（Flutter 语义树）。

实测结论，别再沿用“淘宝无障碍是空的、只能 OCR”的说法：

1. 淘宝外卖/店铺评价页跑在 io.unicorn（阿里基于 Flutter 的自绘引擎）里：
   内容根是 io.unicorn.embedding.android.UnicornSurfaceView，
   整页都是 GPU 自绘，没有任何原生 View，所以普通状态下 uiautomator 只能看到一层空 FrameLayout。

2. Flutter 系引擎在系统“触摸探索（touch exploration）”开启时，会把语义树通过
   AccessibilityNodeProvider 发布出来。打开之后，每条评价就是一个节点，content-desc 是
   淘宝自己拼好的结构化文案：
       评价用户：e***7，满意度5，味道5星，包装5星，这家店的外卖包装干净卫生，……，有商家回复
   星级、用户名、正文一次拿全，不需要再靠 OCR 猜。

3. 本机 HyperOS / Android 16 会把第三方 App 的 FLAG_REQUEST_TOUCH_EXPLORATION_MODE 降级
   （dumpsys 里 capabilities 只剩 1），只有系统级读屏服务能把触摸探索真正打开。
   所以采集淘宝时临时启用 TalkBack，采完立刻还原。

4. 触摸探索打开后，TalkBack 的焦点浮层会抢走 getRootInActiveWindow()，
   常驻无障碍服务读不到淘宝根节点；因此淘宝这一路改用系统界面树 dump 取语义节点。
   dump 会等界面 idle，正好对上 Flutter 列表的惯性动画。
"""

import html
import re
import subprocess
import time

HELPER_SERVICE = "com.koubei.a11y/com.koubei.a11y.ReviewAccessibilityService"
HELPER_PKG = "com.koubei.a11y"
TALKBACK_SERVICE = "com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService"
TAOBAO_PKG = "com.taobao.taobao"
DUMP_PATH = "/sdcard/koubei_taobao.xml"

USER_RE = re.compile(r"评价用户[：:]\s*([^，,。]{1,30})")
SATISFY_RE = re.compile(r"满意度\s*([0-9]+(?:\.[0-9]+)?)")
TASTE_RE = re.compile(r"味道\s*([0-9]+(?:\.[0-9]+)?)\s*星")
PACK_RE = re.compile(r"包装\s*([0-9]+(?:\.[0-9]+)?)\s*星")
RIDER_RE = re.compile(r"骑士\s*(满意|不满意)")
STAR_BLOCK_RE = re.compile(
    r"[，,]?\s*(?:满意度\s*[0-9]+(?:\.[0-9]+)?)"
    r"(?:[，,]\s*味道\s*[0-9]+(?:\.[0-9]+)?\s*星)?"
    r"(?:[，,]\s*包装\s*[0-9]+(?:\.[0-9]+)?\s*星)?"
    r"(?:[，,]\s*骑士\s*(?:满意|不满意))?"
)
TAIL_RE = re.compile(
    r"[，,]?\s*(?:有商家回复|商家回复|TA的点赞[：:].*|展开|收起|有用\s*\d*|点赞\s*\d*|"
    r"已购\s*\d*\s*次|追评|该用户.*?)\s*$"
)
NODE_RE = re.compile(r"<node ([^>]*)/>")
ATTR_RE = re.compile(r'([\w:-]+)="([^"]*)"')


def _shell(dev, args, timeout=25):
    return dev.shell(args)


def get_enabled_services(dev):
    r = _shell(dev, ["settings", "get", "secure", "enabled_accessibility_services"])
    raw = ((r.stdout or "") + (r.stderr or "")).strip()
    if raw in ("", "null", "Null"):
        return []
    return [s for s in raw.split(":") if s and s != "null"]


def set_enabled_services(dev, services):
    value = ":".join(services) if services else "null"
    _shell(dev, ["settings", "put", "secure", "enabled_accessibility_services", value])


def touch_exploration_on(dev):
    r = _shell(dev, ["settings", "get", "secure", "touch_exploration_enabled"])
    return ((r.stdout or "") + (r.stderr or "")).strip() == "1"


def talkback_installed(dev):
    r = _shell(dev, ["pm", "list", "packages", "com.google.android.marvin.talkback"])
    return "com.google.android.marvin.talkback" in ((r.stdout or "") + (r.stderr or ""))


def enable_touch_exploration(dev, log=print, wait=10.0):
    """临时打开触摸探索；返回原始服务列表，供采集结束后还原。"""
    prev = get_enabled_services(dev)
    if not talkback_installed(dev):
        raise RuntimeError(
            "这台手机没装 TalkBack。淘宝是 Flutter 自绘页，必须靠系统的触摸探索才能读到语义节点；\n"
            "请在应用商店装回“TalkBack（屏幕朗读）”后重试，或改用 --ocr 走截图识别。"
        )
    want = prev[:]
    for s in (HELPER_SERVICE, TALKBACK_SERVICE):
        if s not in want:
            want.append(s)
    if want != prev:
        set_enabled_services(dev, want)
    deadline = time.time() + wait
    while time.time() < deadline:
        if touch_exploration_on(dev):
            log("触摸探索已开启：淘宝语义树已发布。")
            return prev
        time.sleep(0.5)
    raise RuntimeError(
        "触摸探索没能打开，淘宝语义树读不到。\n"
        "请手动确认：系统设置 → 无障碍 → 屏幕朗读(TalkBack) 已开启，再重试。"
    )


def service_bound(dev):
    """检查助手服务是否已绑定。

    dumpsys 的 Bound services 是跨多行输出的，前面通常是别的服务，
    所以必须扫全文，不能只看第一行。
    """
    try:
        r = _shell(dev, ["dumpsys", "accessibility"])
    except Exception:
        return False
    text = (r.stdout or "") + (r.stderr or "")
    return "Bound services" in text and ("口碑小探" in text or HELPER_PKG in text)


def _rebind(dev):
    set_enabled_services(dev, [])
    time.sleep(0.8)
    _shell(dev, ["am", "force-stop", HELPER_PKG])
    time.sleep(0.8)
    return None


def restore_services(dev, prev, log=print):
    """采集结束把无障碍服务还原，并确保它真的处于可工作状态。

    注意：只是把列表写回去不够。淘宝路径会连续改两次
    enabled_accessibility_services，系统会留下一个“绑定还在、事件流已死”的
    服务实例，表现就是采集完淘宝后，美团/大众点评等原生页面再也读不到快照。
    实测下来最稳的顺序是：断开全部服务 → 等触摸探索真的关闭 → 结束进程 →
    重新绑定 → 再确认一次（HyperOS 上常常要重绑两轮才拿到健康的事件流）。
    """
    try:
        target = [s for s in (prev or []) if s != TALKBACK_SERVICE] or [HELPER_SERVICE]

        # 1) 断开全部服务（含 TalkBack），等触摸探索真的关闭
        set_enabled_services(dev, [])
        deadline = time.time() + 10.0
        while time.time() < deadline and touch_exploration_on(dev):
            time.sleep(0.5)

        # 2) 结束进程 + 重绑，做两轮，避开“绑着但事件流是死的”实例
        bound = False
        for attempt in range(2):
            _shell(dev, ["am", "force-stop", HELPER_PKG])
            time.sleep(1.0)
            set_enabled_services(dev, target)
            deadline = time.time() + 10.0
            bound = False
            while time.time() < deadline:
                if service_bound(dev):
                    bound = True
                    break
                time.sleep(0.8)
            time.sleep(1.5)
            if bound and attempt == 0:
                continue

        if touch_exploration_on(dev):
            log("已还原无障碍服务，但触摸探索仍开着：请到系统无障碍里关一次 TalkBack。")
        elif not bound:
            log("还原后没检测到服务绑定：请到系统无障碍里手动开关一次“口碑小探评价读取”，"
                "或运行 a11y_collect.py --repair。")
        else:
            log("已还原无障碍服务（已重新绑定并确认），触摸探索关闭。")
    except Exception as exc:
        log(f"还原无障碍服务失败：{exc}")


def parse_review_label(label):
    """把淘宝语义标签解析成 user / rating / review / 分项星。"""
    if not label:
        return None
    if "评价用户" not in label and "满意度" not in label:
        return None

    user = ""
    m = USER_RE.search(label)
    if m:
        user = m.group(1).strip()

    rating = ""
    m = SATISFY_RE.search(label)
    if m:
        rating = m.group(1)
    taste_m = TASTE_RE.search(label)
    pack_m = PACK_RE.search(label)
    rider_m = RIDER_RE.search(label)
    taste = taste_m.group(1) if taste_m else ""
    pack = pack_m.group(1) if pack_m else ""
    rider = rider_m.group(1) if rider_m else ""
    if not rating and taste and pack:
        try:
            rating = "%.1f" % ((float(taste) + float(pack)) / 2.0)
        except ValueError:
            rating = ""

    body = label
    m = USER_RE.search(body)
    if m:
        body = body[m.end():]
    body = re.sub(r"^[，,、]\s*", "", body)
    m = STAR_BLOCK_RE.search(body)
    if m:
        body = body[:m.start()] + body[m.end():]
    body = re.sub(r"^[，,、\s]+", "", body)
    for _ in range(3):
        nb = TAIL_RE.sub("", body).strip()
        if nb == body:
            break
        body = nb
    body = re.sub(r"\s+", " ", body).replace("\n", " ").strip("，,、 ")
    # XML 属性里的换行/引号是转义的（&amp;#10; 之类），不清掉正文里会带出来
    body = html.unescape(body)
    body = re.sub(r"\s+", " ", body).strip("，,、 ")
    if not body:
        return None
    return {
        "user": user or "匿名用户",
        "rating": rating,
        "review": body,
        "taste": taste,
        "pack": pack,
        "rider": rider,
    }


def dump_xml(dev, path=DUMP_PATH):
    """取当前界面的节点树（XML 文本）。

    dump 取的是最上层窗口，短信/通知浮窗、系统弹窗会把它抢走，
    所以这里校验根节点包名，不是淘宝就返回空，交给调用方跳过重试。
    """
    _shell(dev, ["uiautomator", "dump", path])
    r = _shell(dev, ["cat", path], timeout=30)
    out = r.stdout or ""
    if "hierarchy" not in out:
        return ""
    if ('package="%s"' % TAOBAO_PKG) not in out:
        return ""
    return out


def rows_from_xml(xml, page="", stats=None):
    rows = []
    if not xml:
        return rows
    for m in NODE_RE.finditer(xml):
        attrs = dict(ATTR_RE.findall(m.group(1)))
        desc = (attrs.get("content-desc") or "").strip()
        text = (attrs.get("text") or "").strip()
        label = desc if ("评价用户" in desc or "满意度" in desc) else text
        parsed = parse_review_label(label)
        if not parsed:
            # 确实是评价节点（带“评价用户/满意度”语义）但解析不出正文：
            # 算一条被过滤的无效样本，别让它凭空消失
            if stats is not None and ("评价用户" in label or "满意度" in label):
                stats.note_drop("解析失败", label)
            continue
        rows.append({
            "rating": parsed["rating"],
            "review": parsed["review"],
            "user": parsed["user"],
            "date": "",
            "source": "a11y_taobao",
            "page": page,
            "bounds": attrs.get("bounds", ""),
        })
    return rows


def _merge(rows, new_rows):
    """按 (用户, 正文) 归并，同一张卡被截断时保留更长的那份。"""
    key_index = {}
    for r in rows:
        key_index[(r["user"], r["review"][:12])] = r
    for nr in new_rows:
        key = (nr["user"], nr["review"][:12])
        old = key_index.get(key)
        if old is None:
            rows.append(nr)
            key_index[key] = nr
        elif len(nr["review"]) > len(old["review"]):
            old["review"] = nr["review"]
            old["rating"] = nr["rating"] or old["rating"]
    return rows


def swipe_once(dev, w, h, duration, y1, y2, brake=True):
    """一次快滑；默认滑完立刻 DOWN+CANCEL 刹住惯性，和原生 App 那条链路一致。"""
    x = w // 2
    y1px, y2px = int(h * y1), int(h * y2)
    if brake:
        sy = (y1px + y2px) // 2
        return _shell(dev, [f"input swipe {x} {y1px} {x} {y2px} {duration}; "
                            f"input motionevent DOWN {x} {sy}; "
                            f"input motionevent CANCEL {x} {sy}"])
    return _shell(dev, ["input", "swipe", str(x), str(y1px), str(x), str(y2px), str(duration)])


def collect(dev, max_seconds=120, max_reviews=80, idle_stop=15.0, settle=0.2,
            swipe_duration=100, y1=0.86, y2=0.51, manual=False, brake=True,
            idle_pages=6, log=print, on_rows=None, stats=None):
    """边滑边 dump，返回淘宝评价行列表。

    节奏跟主链路对齐：950px、100ms 滑完立刻刹住、停 200ms 再 dump。
    淘宝是 Flutter 自绘页，滑程别一次拉到极限（超过一屏的一半容易 dump 到没刷新的帧）。
    """
    rows = []
    w, h = dev.screen_size()
    started = time.time()
    last_new = time.time()
    page = 0
    no_new_pages = 0
    blocked = 0
    while True:
        if max_seconds and time.time() - started >= max_seconds:
            log("到达最长采集时间，停止。")
            break
        xml = dump_xml(dev)
        if not xml:
            blocked += 1
            if blocked <= 5:
                log("当前界面不是淘宝（通知/弹窗挡住），先等待，不上报空屏。")
            time.sleep(1.2)
            continue
        blocked = 0
        page += 1
        new_rows = rows_from_xml(xml, page, stats=stats)
        if not new_rows:
            # 偶尔会 dump 到还没刷完的一帧，补读一次
            time.sleep(1.0)
            xml2 = dump_xml(dev)
            if xml2:
                new_rows = rows_from_xml(xml2, page, stats=stats)
        before = len(rows)
        _merge(rows, new_rows)
        added = len(rows) - before
        log(f"第 {page} 屏：读到 {len(new_rows)} 条，新增 {added} 条，累计 {len(rows)} 条")
        if added:
            last_new = time.time()
            no_new_pages = 0
        else:
            no_new_pages += 1
        if on_rows:
            on_rows(rows)
        if max_reviews and len(rows) >= max_reviews:
            log("达到目标评价数，停止。")
            break
        # dump 一次要 3–5 秒，用“秒”当阈值会一屏 0 新增就误判到底；
        # 改成连续若干屏都没有新卡才停（淘宝一屏通常就 1–2 条，偶发 0 是正常的）。
        if rows and idle_pages and no_new_pages >= idle_pages:
            log(f"连续 {no_new_pages} 屏没有新增评价，可能已经到底了，停止。")
            break
        if rows and idle_stop and time.time() - last_new >= idle_stop:
            log(f"连续 {idle_stop:g}s 没有新增评价，停止。")
            break
        if manual:
            time.sleep(1.0)
            continue
        swipe_once(dev, w, h, swipe_duration, y1, y2, brake=brake)
        if settle:
            time.sleep(settle)
    return rows


def taobao_in_foreground(dev):
    try:
        r = _shell(dev, ["dumpsys", "window"])
        text = (r.stdout or "") + (r.stderr or "")
    except Exception:
        return False
    for line in text.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            if TAOBAO_PKG in line:
                return True
    return False
