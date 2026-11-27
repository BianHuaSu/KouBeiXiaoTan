#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机评价采集的公共解析与导出逻辑。"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = APP_DIR / "output"
DEMO_FILE = APP_DIR / "口碑小探-demo.html"
if not DEMO_FILE.exists():
    DEMO_FILE = APP_DIR.parent / "口碑小探-demo.html"

DATE_RE = re.compile(
    r"(20\d{2}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
    r"|昨天|前天|今天"
    r"|\d+\s*(?:天|小时|分钟)\s*前)"
)
UI_LABELS = {
    "回复", "赞", "点赞", "举报", "投诉", "展开", "收起", "查看全部",
    "匿名用户", "用户评价", "全部评价", "综合评分", "商家回复", "店铺回复",
    "评价详情", "更多", "返回", "分享", "收藏", "有用", "无用",
    "配送评价", "店铺评价", "口味", "服务", "包装", "评分",
    "食安信息", "点菜", "商家", "评价", "商品", "好评商品",
    "美团外卖鼓励真实、有帮助的评价", "美团外卖", "平台提示",
}
NUMERIC_RE = re.compile(r"^[\d\s.+\-/%]+$")


def clean_line(text):
    text = (text or "").replace("\u200b", "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:展开|收起)\s*", "", text).strip()
    return text


def chinese_len(text):
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


def is_date_text(text):
    return bool(DATE_RE.fullmatch(clean_line(text)))


def split_date(text):
    """返回 (date, rest)；rest 是去掉日期后的文字。"""
    text = clean_line(text)
    m = DATE_RE.search(text)
    if not m:
        return "", text
    date = re.sub(r"\s+", "", m.group(0))
    rest = clean_line(text[:m.start()] + " " + text[m.end():])
    return date, rest


def is_ui_text(text):
    text = clean_line(text)
    if not text:
        return True
    if text in UI_LABELS:
        return True
    if re.fullmatch(r"(?:回复|赞|点赞|举报|投诉)\s*[\(（]?\d*[\)）]?", text):
        return True
    if NUMERIC_RE.fullmatch(text):
        return True
    if len(text) <= 1:
        return True
    return False


def is_body_text(text):
    text = clean_line(text)
    if is_ui_text(text) or is_date_text(text):
        return False
    if chinese_len(text) < 3:
        return False
    if text in {"展开更多", "查看更多", "查看全部", "加载更多"}:
        return False
    return True


def normalize(text):
    return re.sub(r"[^\u4e00-\u9fffa-zA-Z0-9]+", "", text or "").lower()


class CollectStats:
    """采集端“读到过但没留下”的样本统计。

    以前只把能解析成完整评价的卡片写进 CSV，被过滤掉的（正文为空、商家回复、
    太短/重复）直接消失，报表里的“原始 X 条”就等于有效条数，清洗率永远是 0%。
    这里把每一条被过滤的样本按（原因 + 正文）去重记下来，最后一起交给
    write_outputs：原始 = 有效 + 被过滤，清洗率才有意义。
    同一张卡片前面只露出框架（记“正文为空”）、后面滑到位又读全了，note_keep 会
    把那条待定记录撤掉，不会既不丢也不算。
    """

    def __init__(self):
        self._items = {}         # key -> (reason, text, date, user)

    @staticmethod
    def _text_key(reason, text):
        # 只取前 12 个有效字符做指纹：同一张卡被半屏截断时正文长度会变，
        # 用全长会把“同一条”算成两条
        n = normalize(text)[:12]
        return (reason, "T", n) if n else None

    @staticmethod
    def _card_key(reason, date, user):
        return (reason, "E", clean_line(date), clean_line(user))

    def note_drop(self, reason, text="", date="", user=""):
        """记一条被过滤的样本；同一条卡片在多屏里重复出现只算一次。"""
        key = self._text_key(reason, text) or self._card_key(reason, date, user)
        if key in self._items:
            return False
        self._items[key] = (reason, clean_line(text), clean_line(date), clean_line(user))
        return True

    def note_keep(self, text="", date="", user=""):
        """这张卡片最终进了 CSV：把之前记下的“正文为空”之类撤掉。"""
        for key in [k for k in self._items if k[1] == "E" and k[2:] == (clean_line(date), clean_line(user))]:
            self._items.pop(key, None)
        n = normalize(text)[:12]
        if n:
            for key in [k for k in self._items if k[1] == "T" and k[2] == n]:
                self._items.pop(key, None)

    @property
    def items(self):
        return list(self._items.values())

    @property
    def dropped(self):
        return len(self._items)

    def reasons(self):
        from collections import Counter
        return Counter(reason for reason, *_ in self._items.values())

    def to_dict(self, kept=0):
        return {
            "raw": kept + len(self._items),      # 原始 = 有效 + 被过滤
            "kept": kept,
            "dropped": len(self._items),
            "reasons": dict(self.reasons()),
        }


def merge_rows(rows, max_reviews=10000):
    """按正文去重，并处理“半屏截断 / 完整正文”的包含关系。"""
    out = []
    for r in rows:
        text = clean_line(r.get("review", ""))
        if chinese_len(text) < 4:
            continue
        n = normalize(text)
        if len(n) < 4:
            continue
        r = dict(r)
        r["review"] = text
        replaced = False
        for i, old in enumerate(out):
            on = normalize(old["review"])
            if n == on:
                replaced = True
                break
            if n in on:
                # 新文本是旧文本的一部分：旧文本更完整，保留旧的
                replaced = True
                break
            if on in n:
                # 旧文本是新文本的一部分：保留更完整的新文本
                out[i] = r
                replaced = True
                break
        if not replaced:
            out.append(r)
        if len(out) >= max_reviews:
            break
    return out


def merge_same_row(lines, y_tol=12):
    """OCR 同一行可能被拆成多块，按 y 坐标合并。"""
    rows = []
    for line in sorted(lines, key=lambda x: (x.get("y", 0), x.get("x", 0))):
        text = clean_line(line.get("text", ""))
        if not text:
            continue
        if rows and abs(line.get("y", 0) - rows[-1]["y"]) <= y_tol:
            rows[-1]["text"] = clean_line(rows[-1]["text"] + " " + text)
            rows[-1]["x"] = min(rows[-1]["x"], line.get("x", 0))
        else:
            rows.append({"text": text, "x": line.get("x", 0), "y": line.get("y", 0), "h": line.get("h", 20)})
    return rows


def is_user_like(text):
    text = clean_line(text)
    if not text or len(text) > 24 or is_ui_text(text) or is_date_text(text):
        return False
    if re.search(r"[，。！？；,.!?;：:]", text):
        return False
    return 1 <= chinese_len(text) <= 12


def parse_screen(lines, mode="screen", stats=None):
    """把 OCR 行解析成评论。

    mode=screen：一张截图里可能有多条评论，按日期/间距切块。
    mode=card：一张截图就是一条评论，去掉 UI 行后整段作为正文。
    stats：传入 CollectStats 时，太短/没有正文的候选也记一笔，别静默丢弃。
    """
    rows = merge_same_row(lines)
    if mode == "card":
        body = [r["text"] for r in rows if is_body_text(r["text"])]
        text = clean_line(" ".join(body))
        if chinese_len(text) >= 4:
            return [{"review": text, "date": "", "user": ""}]
        if stats is not None:
            stats.note_drop("正文为空/太短", text)
        return []

    out = []
    cur = []
    cur_date = ""
    cur_user = ""
    last_y = None
    heights = [r.get("h", 20) for r in rows if r.get("h")]
    median_h = sorted(heights)[len(heights) // 2] if heights else 20
    gap_limit = max(28, median_h * 2.2)

    def finalize():
        nonlocal cur, cur_date, cur_user
        text = clean_line(" ".join(cur))
        if chinese_len(text) >= 4:
            out.append({"review": text, "date": cur_date, "user": cur_user})
        elif stats is not None and cur:
            stats.note_drop("正文为空/太短", text, cur_date, cur_user)
        cur = []
        cur_date = ""
        cur_user = ""

    for r in rows:
        text = r["text"]
        date, rest = split_date(text)
        if date:
            if cur:
                finalize()
            cur_date = date
            if rest:
                if is_user_like(rest) and not cur_user:
                    cur_user = rest
                elif is_body_text(rest):
                    cur.append(rest)
            last_y = r["y"]
            continue
        if is_ui_text(text):
            continue
        if last_y is not None and r["y"] - last_y > gap_limit and cur:
            finalize()
        cur.append(text)
        last_y = r["y"]

    if cur:
        finalize()
    return out


def make_demo_page(rows, out_dir, shop_name, source="手机 ADB / 截图 OCR", stats=None):
    """把采集结果预载进口碑小探 Demo，生成可直接双击打开的分析页。"""
    if not rows or not DEMO_FILE.exists():
        return None
    csv_lines = ["rating,review"]
    for r in rows:
        txt = str(r.get("review", "")).replace('"', '""')
        csv_lines.append(f'{r.get("rating") or 3},"{txt}"')
    preload = {
        "name": shop_name,
        "csv": "\n".join(csv_lines),
        "users": [r.get("user", "") for r in rows],
        "platform": "手机采集",
        "source": source,
        "dishes": [],
        # 采集端过滤掉的样本：让报表能算“原始 / 清洗”而不是永远 0%
        "stats": stats or {},
    }
    html = DEMO_FILE.read_text(encoding="utf-8")
    if "</body>" not in html:
        return None
    # 预载页是真的手机采集，不能沿用主页的“评论虚构”说明
    html = html.replace(
        "店铺与菜品为演示虚构，评论每次点击现场抽样。",
        "店铺名与菜品仅作展示；评论来自手机现场采集，不做虚构。",
    )
    inject = DEMO_SCRIPT.replace("__PRELOAD__", json.dumps(preload, ensure_ascii=False))
    html = html.replace("</body>", inject + "\n</body>")
    out = Path(out_dir) / "口碑小探-手机采集.html"
    out.write_text(html, encoding="utf-8")
    return out


DEMO_SCRIPT = """
<script>
(function () {
  var P = __PRELOAD__;
  function boot() {
    if (typeof parseData !== 'function' || typeof startAnalysis !== 'function') return;
    var reviews = parseData(P.csv).map(function (r, i) {
      r.id = 'phone-' + String(i + 1).padStart(3, '0');
      r.user = P.users[i] || r.user;
      r.ts = Date.now() - i * 60000;
      r.dish = '—';
      return r;
    });
    var store = {
      id: 'phone-real',
      name: P.name,
      cat: '手机采集 · 当场分析',
      rating: '—',
      sales: '采集 ' + reviews.length + ' 条',
      avg: reviews.length + ' 条有效文本',
      emoji: '📱',
      color: '#0f766e',
      dist: P.source,
      dishes: [],
      reviews: reviews,
      // 采集端过滤掉的无效样本（正文为空 / 商家回复 / 太短），计入“原始”分母
      preStats: P.stats || null
    };
    startAnalysis(store);
  }
  if (typeof parseData === 'function' && typeof startAnalysis === 'function') boot();
  else document.addEventListener('DOMContentLoaded', boot);
})();
</script>
"""


def write_outputs(rows, out_dir, source="mobile", shop_name="手机采集", make_page=True, stats=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = merge_rows(rows)
    full = out_dir / "reviews_full.csv"
    demo = out_dir / "reviews_demo.csv"
    with open(full, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rating", "review", "user", "date", "source", "page"])
        w.writeheader()
        for r in rows:
            w.writerow({
                "rating": r.get("rating", ""),
                "review": r["review"],
                "user": r.get("user", ""),
                "date": r.get("date", ""),
                "source": r.get("source", source),
                "page": r.get("page", ""),
            })
    with open(demo, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rating", "review"])
        for r in rows:
            w.writerow([r.get("rating") or 3, r["review"]])
    # 被采集端过滤掉的样本单独落盘：既能复核为什么被丢，也让“原始 / 清洗”有分母
    stats_dict = stats.to_dict(len(rows)) if stats is not None else None
    if stats_dict is not None:
        dropped_csv = out_dir / "reviews_dropped.csv"
        with open(dropped_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["reason", "review", "date", "user"])
            for reason, text, date, user in stats.items:
                w.writerow([reason, text, date, user])
        (out_dir / "collect_stats.json").write_text(
            json.dumps(stats_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    page = None
    if make_page and len(rows) >= 10:
        source_label = {
            "uiauto": "手机界面树（UI Automator）",
            "ocr": "手机截图 OCR",
            "adb": "手机 ADB 截图 OCR",
            "a11y": "手机无障碍服务（边滑边读）",
            "a11y_dianping": "大众点评 · 手机无障碍服务（边滑边读）",
            "a11y_meituan": "美团 · 手机无障碍服务（边滑边读）",
            "a11y_eleme": "饿了么 · 手机无障碍服务（边滑边读）",
            "a11y_jd": "京东 · 手机无障碍服务（边滑边读）",
            "jd_ocr": "京东 · 截图 OCR（现场滚动识别 + 数红星）",
            "a11y_taobao": "淘宝 · 手机无障碍服务（边滑边读）",
            "taobao_ocr": "淘宝 · 手机截图 OCR（现场滚动识别）",
        }.get(source, source)
        page = make_demo_page(rows, out_dir, shop_name, source_label, stats=stats_dict)
    return full, demo, page


def make_out_dir(prefix):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{stamp}_{prefix}"
