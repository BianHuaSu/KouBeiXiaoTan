"""京东外卖点评页采集：截图 OCR + 数红星。

为什么要单独一条路：京东外卖点评页跑在 Manto 小程序容器
（com.jingdong.manto.card.MantoLightActivity）里，是自绘页面。无障碍服务在这页
只能拿到 17 个粗节点——容器名、返回/搜索/预订/拼单等按钮、日期、"用户评价，图片"
（图片占位描述）、"TA的推荐"、"有用"、"晒单"，**正文、星级、昵称都没有独立节点**。
所以直接走无障碍读出来的"正文"其实是标签拼接（用户评价，图片 + 商家回复 + 商品名），
星级也基本为空。打开触摸探索同样只有 17 个节点，京东不需要它。

这里改成截图 OCR：按"评分"两字做锚点切卡，在"评分"右侧数红色实心星得到星级，
卡片内按行合并 OCR 文本得到正文，过滤掉图片里印的大字、页脚"投诉与建议"、
推荐商品名和"有用/晒单"这类按钮。
"""
import difflib
import re
import time
from pathlib import Path

from PIL import Image

import ocr_core

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
BOTTOM_LABELS = {"有用", "晒单", "＋ 晒单", "+ 晒单", "TA的推荐:", "TA的推荐：",
                 "商家1天内回复", "去尝尝"}
NOISE_TXT = {"有用", "无用", "晒单", "＋ 晒单", "去尝尝", "TA的推荐：", "TA的推荐",
             "商家1天内回复", "商家回复", "展开", "收起", "查看全部", "回复", "点赞",
             "举报", "写评价", "全部", "最新", "好评", "差评", "有图"}
BAD_WORDS = ("投诉", "电话", "建议")


def count_stars(im, y0, y1, x0, x1):
    """在指定区域数红色实心星（JD 的星级是自绘红色五角星，没有文字）。"""
    px = im.load()
    w, h = max(0, x1 - x0), max(0, y1 - y0)
    if w <= 0 or h <= 0:
        return 0
    mask = [[0] * w for _ in range(h)]
    for yy in range(h):
        for xx in range(w):
            r, g, b = px[x0 + xx, y0 + yy]
            if r > 140 and g < 95 and b < 95:
                mask[yy][xx] = 1
    seen = [[0] * w for _ in range(h)]
    stars = 0
    for yy in range(h):
        for xx in range(w):
            if mask[yy][xx] and not seen[yy][xx]:
                stack = [(yy, xx)]
                seen[yy][xx] = 1
                n = 0
                minx = maxx = xx
                while stack:
                    cy, cx = stack.pop()
                    n += 1
                    minx, maxx = min(minx, cx), max(maxx, cx)
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < h and 0 <= nx < w and mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = 1
                            stack.append((ny, nx))
                if n >= 120 and (maxx - minx) >= 18:
                    stars += 1
    return min(5, stars)


def parse_screen(shot_path, min_score=0.5, stats=None):
    """解析一屏，返回 [{rating, review, user, date}]。"""
    shot_path = Path(shot_path)
    boxes = ocr_core.ocr_image(str(shot_path), min_score=min_score)
    if not boxes:
        return []
    im = Image.open(shot_path).convert("RGB")
    w, h = im.size
    anchors = [b for b in boxes if b["text"].strip() in ("评分", "评分：")]
    anchors.sort(key=lambda b: b["y"])
    rows = []
    all_dates = sorted([b for b in boxes if DATE_RE.search(b["text"])], key=lambda b: b["y"])
    for i, a in enumerate(anchors):
        # 卡片上沿 = 这条评价的日期行（昵称在日期上方一点），
        # 不能用“评分 - 170”：那样会把上一张卡底部的“TA的推荐”商品名圈进来，
        # 商品名就会插进正文中间。
        own_date = None
        for b in all_dates:
            if b["y"] < a["y"]:
                own_date = b
        top = (own_date["y"] - 68) if own_date else (a["y"] - 120)
        nxt = anchors[i + 1]["y"] - 120 if i + 1 < len(anchors) else h
        star = count_stars(im, int(a["y"]) - 2, int(a["y"] + a["h"]) + 2,
                           int(a["x"] + a["w"]), int(a["x"] + a["w"]) + 520)
        inner = [b for b in boxes if top <= b["y"] < nxt]
        # “TA的推荐：”后面跟的商品名和它是同一行，会插进正文中间，整行丢掉
        ta_ys = [b["y"] for b in inner if b["text"].strip().startswith("TA的推荐")]
        # 卡片底部：评分行下方出现的“有用/晒单/TA的推荐/商家回复”
        body_limit = nxt
        for b in inner:
            t = b["text"].strip()
            if b["y"] > a["y"] + a["h"] and t in BOTTOM_LABELS:
                body_limit = min(body_limit, b["y"])
        date, user, body = "", "", []
        stop_body = False
        for b in sorted(inner, key=lambda z: (z["y"], z["x"])):
            t = b["text"].strip()
            if b["h"] > 70:            # 图片里印的大字（店名 logo）
                continue
            if any(k in t for k in BAD_WORDS):
                continue
            if ta_ys and any(abs(b["y"] - ty) <= 42 for ty in ta_ys):
                continue                       # 和“TA的推荐：”同一行的商品名
            if len(t) <= 30 and re.search(r"\d+\s*(人份|个|支|块|克|份)", t):
                continue                       # 购买商品/规格行，不是评价正文
            m = DATE_RE.search(t)
            if m:
                date = m.group(0)
                continue
            if t in ("评分", "评分："):
                continue
            if t.startswith("商家") and "回复" in t:
                stop_body = True
                continue
            if stop_body:
                continue
            if t in NOISE_TXT or t.startswith("TA的推荐"):
                continue
            if b["y"] < a["y"] - 20:
                # 昵称是日期同一行的左侧小字；离得远的一律不要（搜索框、店铺名会混进来）
                d = next((b for b in all_dates if b["y"] < a["y"]), None)
                if (d and abs(b["y"] - d["y"]) <= 55 and b["x"] < d["x"] - 40
                        and len(t) >= 2 and t not in NOISE_TXT):
                    user = t
                continue
            if a["y"] + a["h"] < b["y"] < body_limit and len(t) >= 2:
                body.append((int(b["y"]), int(b["x"]), t))
        lines = []
        for y, x, t in sorted(body):
            if lines and abs(y - lines[-1][0]) <= 26:
                lines[-1][1].append((x, t))
            else:
                lines.append((y, [(x, t)]))
        text = " ".join("".join(t for _, t in sorted(parts)).strip() for _, parts in lines).strip()
        if len(text) < 4:
            if stats is not None:
                stats.note_drop("正文为空/太短", text, date, user)
            continue
        rows.append({"rating": star if star else "", "review": text,
                     "user": user, "date": date})
    return rows


def merge_similar(rows, ratio=0.88):
    """OCR 每屏读同一张卡会有抖动（少一个字、多个字），用相似度合并成一条。

    相似的两条保留正文更长的那条（信息更完整），但不会把两条不同评价合掉——
    实测不同评价的相似度都远低于 0.88。
    """
    out = []
    for r in rows:
        n = re.sub(r"\s", "", r.get("review", ""))
        for old in out:
            on = re.sub(r"\s", "", old["review"])
            if difflib.SequenceMatcher(None, n, on).ratio() >= ratio:
                if len(n) > len(on):
                    keep_rating = r.get("rating") or old.get("rating", "")
                    keep_user = r.get("user") or old.get("user", "")
                    keep_date = r.get("date") or old.get("date", "")
                    old.update(r)
                    old["rating"] = keep_rating
                    old["user"] = keep_user
                    old["date"] = keep_date
                break
        else:
            out.append(dict(r))
    return out


def collect(dev, max_seconds=120, max_reviews=80, settle=0.3, swipe_duration=100,
            y1=0.86, y2=0.51, brake=True, idle_pages=5, log=print,
            on_rows=None, shot_path=None, stats=None):
    """边滑边截图 OCR，累积去重。返回 rows。"""
    from a11y_collect import swipe_once                    # 延迟导入，避免循环依赖
    from common import merge_rows

    shot = Path(shot_path) if shot_path else Path.cwd() / "_jd_screen.png"
    holder, seen, page = [], set(), 0
    no_new = 0
    started = time.time()
    w, h = dev.screen_size()
    while True:
        page += 1
        if max_seconds and time.time() - started > max_seconds:
            log(f"到达最长采集时间（{max_seconds}s），停止。")
            break
        dev.screenshot(shot)
        try:
            rows = parse_screen(shot, stats=stats)
        except Exception as exc:
            log(f"第 {page} 屏解析失败：{exc}")
            rows = []
        fresh = 0
        for r in rows:
            key = re.sub(r"\s+", "", r["review"])[:40]
            if key in seen:
                continue
            seen.add(key)
            r["source"] = "jd_ocr"
            r["page"] = page
            holder.append(r)
            fresh += 1
        holder = merge_rows(holder)
        holder = merge_similar(holder)
        log(f"第 {page} 屏：读到 {len(rows)} 条，新增 {fresh} 条，累计 {len(holder)} 条")
        if on_rows:
            on_rows(list(holder))
        if max_reviews and len(holder) >= max_reviews:
            log("达到目标评价数，停止。")
            break
        if fresh == 0:
            no_new += 1
            if no_new >= idle_pages:
                log(f"连续 {no_new} 屏没有新评价，停止。")
                break
        else:
            no_new = 0
        if settle:
            time.sleep(settle)
        try:
            swipe_once(dev, w, h, swipe_duration, y1, y2, brake=brake)
        except Exception as exc:
            log(f"滑动失败：{exc}")
            break
    return holder

