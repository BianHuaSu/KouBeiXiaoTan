#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Android UI Automator 界面树解析：按版面坐标切出评价卡片。"""

import re
import xml.etree.ElementTree as ET

try:
    from PIL import Image
except Exception:
    Image = None

from common import clean_line, chinese_len, is_date_text, is_ui_text, normalize

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
LEVEL_RE = re.compile(r"^Lv\s*\d+", re.I)
PRICE_RE = re.compile(r"[￥¥]\s*\d|/\s*人|人均")
STAR_RE = re.compile(r"[★☆⭐]")
DURATION_RE = re.compile(r'^\d+\s*["″\']$')
RATING_RE = re.compile(r"(?:商品|包装|口味|服务|配送|商家|骑手|评分|星级)?\s*(\d+(?:\.\d+)?)\s*(?:星|分)")
RATING_RE_STRICT = re.compile(r"(?:商品|包装|口味|服务|配送|满意度)\s*(\d+(?:\.\d+)?)\s*(?:星|分)?")
CN_STAR_RE = re.compile(r"([一二三四五])\s*星(半)?")
MERCHANT_RE = re.compile(r"^(?:\S{0,24}\s*)?(?:\(|（)?商家(?:\)|）)?\s*[:：]")
# 商家回复模板句：这类文本会以“孤立正文”的形式出现在首条评价卡上方（店铺公告/置顶回复），
# 按版面切卡时会被当成第一条评价，星级却是空的——必须剔掉，别让它污染评价数据。
MERCHANT_REPLY_RE = re.compile(
    r"(感谢您对本店|感谢您的评价|感谢您选择|感谢您的支持|感谢您的好评|感谢好评|感谢支持|"
    r"感谢您的认可|感谢您的信任|感谢您的光临|谢谢您的支持|本店的支持和信任|"
    r"欢迎您再次光临|欢迎再次光临|期待您的再次|我们会继续努力|我们会努力|继续努力|"
    r"我们将继续努力|祝您生活愉快|祝您用餐愉快|请您谅解|商家回复|商家致谢)"
)
MOODS = {"一般", "一般般", "很棒", "很好", "好", "超预期", "超出预期", "差", "较差", "很差", "很糟糕", "糟糕", "不错", "推荐", "不推荐", "满意", "不满意"}
TAGS = {
    "打卡后评价", "打卡", "广告", "赞助", "商家回复", "店铺回复", "已消费", "消费后评价",
    "有用", "无用", "点赞", "回复", "评论", "有帮助", "说点什么吧～", "说点什么吧",
    "收藏", "打卡", "写评价", "查看全部", "展开", "收起", "更多",
    "头像", "评论按钮", "有帮助按钮", "语音评价", "播放",
    "白金会员", "黄金会员", "黑金会员", "会员", "有用",
}
HEADER_WORDS = {"全部", "最新", "差评", "中评", "好评", "带图/视频", "筛选", "评价"}

# 京东外卖点评页（Manto 自绘小程序）会把标签和商品名混进正文：
# “用户评价，图片”是图片区的占位描述，“商家1天内回复”是回复条，
# 卡片底部还会再贴一遍推荐商品名/规格（如“大鸡腿2个+翅根2个+鸡叉骨100克+10薯条 一人份”）。
# 这些都不是用户写的话，必须按行剔掉，否则正文就是标签垃圾。
JD_NOISE_SEGS = (
    "用户评价，图片", "用户评价", "商家1天内回复", "商家1天回复", "商家回复",
    "去尝尝", "TA的推荐", "晒单", "有用",
    "份量升级", "限时抢购", "限时秒杀", "秒杀", "特惠", "爆品",
    # 京东店家回复的高频套话（出现在正文后面或卡片外的顶部区，整句剔掉）
    "生活不止有工作，还有美味", "美味让生活更加美好", "看到您的好评", "看到您的好评，心里暖洋洋的",
    "您的好评是对我们最大的鼓励", "忙碌了一天看到您的好评", "一流的食材创造出一流的美味",
    "流下的汗水", "为顾客提供美味的菜品", "收到您的五星好评", "期待与您再次相遇",
)
JD_UNIT_RE = re.compile(r"[+＋].*(?:个|支|块|克|份|串|盒|杯|条|片|只)")
JD_SPEC_RE = re.compile(r"[一二三四五六七八九十\d]+\s*人份$")
JD_PACK_RE = re.compile(r"【[^】]{1,20}】")
JD_NUM = r"[一二三四五六七八九十两\d]+"
# 整条就是一处标签的节点，直接跳过（避免中文长度凑够 4 就混进正文）
JD_TAG_ONLY = {
    "用户评价，图片", "用户评价", "商家1天内回复", "商家1天回复", "商家回复",
    "去尝尝", "晒单", "有用", "TA的推荐：", "TA的推荐",
}
# 出现这些标记节点，说明卡片下面的内容是商家回复/推荐商品，不是用户正文
JD_CUT_MARKS = {
    "商家1天内回复", "商家1天回复", "商家回复", "TA的推荐：", "TA的推荐",
    "去尝尝", "晒单，按钮", "晒单", "有用",
}
# 会被误当成昵称的界面词（京东页面右上角的配送/自提/拼单之类）
JD_UI_NAMES = {"配送", "自提", "拼单", "预订", "预订 按钮", "搜索", "搜索，按钮", "更多", "返回", "返回，按钮", "晒单，按钮"}


def is_jd_product_line(t):
    """京东卡片里的推荐商品名 / 规格行，不是用户评价正文。"""
    x = clean_line(t)
    if not x:
        return True
    if JD_PACK_RE.search(x) and chinese_len(x) <= 30:
        return True
    if JD_UNIT_RE.search(x) and chinese_len(x) <= 40:
        return True
    if JD_SPEC_RE.match(x):
        return True
    if x == "默认" or x.endswith("默认"):
        return True
    return False


def clean_jd_line(t):
    x = clean_line(t)
    for s in JD_NOISE_SEGS:
        x = x.replace(s, " ")
    return clean_line(x)


# 京东把“商品名 + 规格 + 正文 + 商家回复”粘成一段，光按行删不够，还得按片段切。
JD_SPEC_INLINE_RE = re.compile(
    rf"[^ ，。！？；]{{0,20}}?(?:丨[^ ，。！？；]{{1,30}}|【[^】]{{1,20}}】[^ ，。！？；]{{0,30}}|{JD_NUM}\s*(?:人份|份))"
)
JD_STORE_SUMMARY_RE = re.compile(r"商家评分\s*\d+(?:\.\d+)?(?:\s*[，,]\s*包装\s*\d+(?:\.\d+)?)?(?:\s*[，,]\s*配送满意度\s*\d+%)?")
JD_PAGE_TEXT_RE = re.compile(r"自提[，,]?\s*查看路线[，,]?\s*更省不用等|查看路线|立即抢购|加入购物车")
JD_REPLY_START_RE = re.compile(
    r"(?:感谢您|感谢亲|感谢顾客|谢谢亲|谢谢您|客官|欢迎您|欢迎亲|请您|祝您|"
    r"您的评价|您的满足|您的肯定|我们的努力|每个顾客|希望您|期待您)"
)
JD_REPLY_TAIL_RE = re.compile(r"亲|好评|光临|鼓励|支持|期待|光顾|开心|评价|满足|肯定|努力|意义|想起|常来")


def clean_jd_body(text):
    """京东评价正文：剔掉内联商品名/规格，并在商家回复起点处截断。

    京东把一条评价拼成一段：“商品名 1人份 正文 商品名 商家回复”。
    商品名没有独立节点，只能靠“数字+份/人份”前面的词、含“丨/【】/+”的长串，
    以及“同一串出现两次”来认。
    """
    t = clean_line(text)
    for s in JD_NOISE_SEGS:
        t = t.replace(s, " ")
    t = JD_STORE_SUMMARY_RE.sub(" ", t)
    t = JD_PAGE_TEXT_RE.sub(" ", t)

    removed = set()

    def _drop_spec(m):
        seg = m.group(0)
        name = re.sub(rf"\s*{JD_NUM}\s*(?:人份|份)$", "", seg).strip("，。！？、 ")
        # “还送了一份 / 点了两份”是用户在说数量，不是商品名：只删“一份”，别吞掉动作
        if re.search(r"送|吃|点|要|来|给|加|配|做|喝|尝|有|是|了|的", name):
            return (name + " ") if name else " "
        if len(name) >= 3:
            removed.add(name)
        return " "

    # 贪婪吃掉“1人份 / 一人份 / 1份”紧邻前面的商品名，并记下来以便删掉后面重复的那一遍
    t = re.sub(rf"[^ ，。！？；]{{1,20}}\s*{JD_NUM}\s*(?:人份|份)", _drop_spec, t)
    t = re.sub(r"\s+", " ", t)

    toks = [x for x in t.split(" ") if x]
    keep, seen = [], set()
    for tk in toks:
        core = tk.strip("，。！？、 ")
        if not core:
            continue
        if ("+" in core or "丨" in core) and len(core) >= 8:
            continue
        # 只删“本身就是那个商品名”的短 token；正文里顺口提到商品名的长句不能整句丢
        if any(name and (core == name or (len(core) <= len(name) + 8 and name in core))
               for name in removed):
            continue
        if len(core) >= 6:
            if core in seen:
                continue          # 同一商品名贴了两遍，只留一次
            seen.add(core)
        keep.append(tk)
    t = " ".join(keep)

    # 商家回复：正文后面跟着店家套话，从这里截断（截到上一个空格/句号处，别把正文尾巴带走）
    m = JD_REPLY_START_RE.search(t)
    cut_at = m.start() if m else None
    if cut_at is None:
        for kw in ("小店", "本店", "亲的好评", "亲的满意"):
            idx = t.find(kw, 0)
            if idx >= 0 and JD_REPLY_TAIL_RE.search(t[idx:]):
                cut_at = idx
                break
    if cut_at is not None:
        cut = max(t.rfind(" ", 8, cut_at), t.rfind("。", 8, cut_at))
        t = t[:cut if cut > 8 else cut_at]
        # 整条基本就是店家套话（截完只剩几个字）→ 不是用户评价，丢掉
        if chinese_len(t) < 8:
            return ""

    t = re.sub(r"\s+", " ", t)
    return clean_line(t).lstrip("，。！？、； ")


def parse_bounds(text):
    m = BOUNDS_RE.search(text or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def read_nodes(xml_path):
    root = ET.parse(xml_path).getroot()
    out = []
    for node in root.iter("node"):
        text = clean_line(node.get("text", ""))
        if not text:
            continue
        b = parse_bounds(node.get("bounds", ""))
        if not b:
            continue
        x1, y1, x2, y2 = b
        out.append({
            "text": text,
            "x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1,
            "cls": node.get("class", ""),
            "desc": node.get("content-desc", ""),
            "clickable": node.get("clickable", "false") == "true",
        })
    # 同一文本、同一位置只留一个
    seen = set()
    uniq = []
    for n in out:
        key = (n["text"], n["x"], n["y"], n["w"], n["h"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)
    return uniq


def is_meta(text):
    t = clean_line(text)
    if not t:
        return True
    if t in TAGS or t in MOODS or t in HEADER_WORDS:
        return True
    if re.fullmatch(r"正文\d*|图片\d*|头像\d*", t):
        return True
    if re.fullmatch(r"当前为您定位至.*?条评价", t):
        return True
    if re.fullmatch(r"(?:商品|包装|口味|服务|配送|商家|骑手|评分|星级)\s*\d+(?:\.\d+)?\s*星", t):
        return True
    if re.fullmatch(r"(?:全部|好评|差评|中评|最新|有图/视频|评价)\s*\d*", t):
        return True
    if t.startswith("好评商品") or re.fullmatch(r"买过[≥\s]*\d+\s*次", t):
        return True
    if LEVEL_RE.match(t) or PRICE_RE.search(t) or STAR_RE.search(t) or DURATION_RE.match(t):
        return True
    if is_date_text(t) or is_ui_text(t):
        return True
    return False


def is_star_only(text):
    """整段就是几颗星（"★★★★★"），才算星级；正文里的"★★★麻辣拌★★"不算。"""
    t = clean_line(text)
    if not STAR_RE.search(t):
        return False
    return len(re.sub(r"[★☆⭐\s]", "", t)) <= 1


def is_merchant_reply(text):
    t = clean_line(text)
    return bool(MERCHANT_RE.match(t)) or "商家回复" in t[:12] or "店铺回复" in t[:12]


def mood_rating(text):
    t = clean_line(text)
    if t in {"超预期", "超出预期", "很好", "推荐"}:
        return 5
    if t in {"很棒", "满意"}:
        return 4.5
    if t in {"不错", "好"}:
        return 4
    if t in {"一般", "一般般"}:
        return 2.5
    if t in {"差", "较差", "不满意", "不推荐"}:
        return 2
    if t in {"很差", "很糟糕", "糟糕"}:
        return 1
    return None


def stars_rating(shot_path, mood, width):
    """从截图里数心情标签右侧的橙色星星，返回 1~5 的星级（含 0.5）。

    大众点评的星星是自绘的，界面树不会暴露星级；只能按橙色底块逐颗数。
    """
    if Image is None or not shot_path or not mood:
        return None
    try:
        im = Image.open(shot_path).convert("RGB")
    except Exception:
        return None
    x0 = max(0, mood["x"] + mood["w"] + 4)
    x1 = min(im.width, mood["x"] + int(width * 0.42))
    y0 = max(0, mood["y"] - 8)
    y1 = min(im.height, mood["y"] + mood["h"] + 8)
    if x1 - x0 < 30 or y1 - y0 < 12:
        return None

    on = []
    for x in range(x0, x1):
        cnt = 0
        for y in range(y0, y1):
            r, g, b = im.getpixel((x, y))
            if r > 200 and 40 < g < 170 and b < 120:
                cnt += 1
        on.append(cnt >= 3)

    runs = []
    start = None
    for i, flag in enumerate(on):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(on) - 1))
    if not runs:
        return None

    # 星星之间只隔 4~6 px；标签文字与最后一颗星之间通常隔 30 px 以上。
    groups = []
    cur = [runs[0]]
    for r in runs[1:]:
        if r[0] - cur[-1][1] <= 14:
            cur.append(r)
        else:
            groups.append(cur)
            cur = [r]
    groups.append(cur)
    widths = [b - a + 1 for a, b in groups[0]]
    widths = [w for w in widths if w >= 8]
    if not widths:
        return None

    widths.sort()
    unit = widths[len(widths) // 2]
    full = sum(1 for w in widths if w >= unit * 0.72)
    half = sum(1 for w in widths if unit * 0.25 <= w < unit * 0.72)
    score = min(5.0, full + 0.5 * min(1, half))
    return score if score > 0 else None


def pick_user(nodes, date, width):
    """日期附近、左侧的用户名。"""
    cands = []
    for n in nodes:
        t = n["text"]
        if t == date["text"]:
            continue
        # 美团/点评有纯数字昵称（如 0212），4 位以上才当昵称；3 位多是“评价 615”这类计数
        numeric_name = bool(re.fullmatch(r"\d{4,12}", t))
        if is_meta(t) and not numeric_name:
            continue
        if t in {"头像", "用户头像"} or n.get("cls") == "android.widget.ImageView":
            continue
        if n["x"] > width * 0.55:
            continue
        if abs(n["y"] - date["y"]) > 150:
            continue
        # 用户名通常没有标点，长度 2–20
        if len(t) > 24 or re.search(r"[，。！？；,.!?;：:]", t):
            continue
        cands.append(n)
    if not cands:
        return ""
    # 优先与日期同一行附近；同距离时优先更像昵称的非纯界面文本
    cands.sort(key=lambda n: (abs(n["y"] - date["y"]), is_ui_text(n["text"]), -len(n["text"])))
    name = cands[0]["text"]
    name = LEVEL_RE.sub("", name).strip()
    return name


def clean_body(text):
    """去掉大众点评的图标标签（[服务铃]/[点赞]/￼）和多余空白。"""
    t = clean_line(text)
    t = re.sub(r"\[[^\]\n]{1,12}\]", "", t)
    t = t.replace("\ufffc", "").replace("\u200b", "")
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]", "", t)
    # 平台争议提示：此评价商家提出异议，经大众评审投票，76%评审官认为“适合展示”
    t = re.sub(r"^此评价商家提出异议.*?适合展示\s*", "", t)
    t = t.replace("TA在这家店的全部评价", "").strip()
    return clean_line(t)


def pick_body(nodes, start, bottom, width, exclude=(), jd=False):
    cands = []
    for n in nodes:
        t = n["text"]
        if not (start <= n["y"] < bottom):
            continue
        if t in exclude:
            continue
        if n["x"] > width * 0.78:
            continue
        if is_meta(t) or is_merchant_reply(t):
            continue
        if jd:
            # 京东的节点自己就带着商品名/商家套话，先在节点级清一遍，
            # 别等到按行拼起来再切（拼完就分不出哪句是谁的了）
            t = clean_jd_body(t)
            if not t or chinese_len(t) < 4 or is_jd_product_line(t):
                continue
            n = dict(n, text=t)
        if chinese_len(t) < 4:
            continue
        if t.startswith("搜索“") or t.startswith("搜索\""):
            continue
        cands.append(n)
    if not cands:
        return ""
    # 同一行的多个片段按 x 合并
    cands.sort(key=lambda n: (n["y"], n["x"]))
    rows = []
    for n in cands:
        if rows and abs(n["y"] - rows[-1]["y"]) <= max(18, min(n["h"], rows[-1]["h"]) * 0.6):
            rows[-1]["parts"].append(n["text"])
        else:
            rows.append({"y": n["y"], "h": n["h"], "parts": [n["text"]]})
    if jd:
        lines = []
        for r in rows:
            line = clean_jd_line(" ".join(r["parts"]))
            if not line or chinese_len(line) < 4:
                continue
            if is_jd_product_line(line):
                continue
            lines.append(line)
        # 京东常把同一句商品名/正文再贴一遍在卡片底部，首尾重复只留一次
        if len(lines) > 1 and lines[-1] == lines[0]:
            lines.pop()
        text = clean_jd_body(" ".join(lines))
    else:
        text = " ".join(" ".join(r["parts"]) for r in rows)
    return clean_body(text)


def pick_orphan_body(nodes, end, width, jd=False):
    """屏幕顶部可能露出上一条评价的正文，但用户名/日期已经滚出屏幕。"""
    if end <= 0:
        return ""
    if jd:
        # 顶部区间里如果出现过“商家1天内回复/TA的推荐”标记，露出来的那段是
        # 店家回复或推荐商品，不是用户正文，宁可不收
        if any(n["text"] in JD_CUT_MARKS and 0 <= n["y"] < end for n in nodes):
            return ""
    cands = []
    for n in nodes:
        t = n["text"]
        if not (0 <= n["y"] < end):
            continue
        if n["x"] > width * 0.78:
            continue
        if is_meta(t) or is_merchant_reply(t):
            continue
        if jd and (t in JD_TAG_ONLY or is_jd_product_line(t)):
            continue
        # 京东页面上方的推荐位/搜索提示，不是评价
        if jd and re.search(r"同款评价|为你精选|猜你喜欢|为你推荐|附近好店|更多评价|精选", t):
            continue
        # 京东店铺头部（返回/配送/搜索/已售 4000万+ 那一串）会被当成“首条孤立正文”
        if jd and re.search(r"返回，按钮|搜索，按钮|预订 按钮|已售|京东秒送|约\d+分钟", t):
            continue
        if jd:
            t = clean_jd_body(t)
            if chinese_len(t) < 10:
                continue
        if chinese_len(t) < 8:
            continue
        if t.startswith("推荐：") or t.startswith("推荐菜"):
            continue
        if t.startswith("搜索“") or t.startswith("搜索\""):
            continue
        # 美团顶部常混入店铺介绍/加盟广告，不是评价正文
        if re.search(r"加盟|连锁|门店|订餐|起送|配送费|营业时间|商家信息|联系电话|优惠活动", t):
            continue
        cands.append(dict(n, text=t) if jd else n)
    if not cands:
        return ""
    best = max(cands, key=lambda n: (chinese_len(n["text"]), -n["y"]))
    return clean_body(clean_jd_body(best["text"]) if jd else best["text"])


def extract_rating(node):
    """无障碍节点里的真实评分：显式分项星级优先，裸小数分视为页面汇总分跳过。

    - "商品5星"、"包装4星"、"满意度5" 这类带分项的，是评价卡自己的星级；
    - 裸的 "4.7分"、"3.7分" 基本是店铺/口味汇总分，不能当单条评价星级。
    大众点评的自绘星星没有节点，这里返回 None，仍回退到心情标签。
    """
    texts = [clean_line(node.get("text", "")), clean_line(node.get("desc", ""))]
    for t in texts:
        if not t:
            continue
        m = CN_STAR_RE.search(t)
        if m:
            value = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}[m.group(1)]
            if m.group(2):
                value += 0.5
            return min(5.0, value)
        m = RATING_RE_STRICT.search(t)
        if m:
            try:
                value = float(m.group(1))
            except ValueError:
                return None
            if 0 < value <= 5:
                return value
        m = RATING_RE.search(t)
        if m:
            try:
                value = float(m.group(1))
            except ValueError:
                continue
            # 没有分项前缀的裸小数（"4.7分"）多是汇总分，只接受整数星
            if value.is_integer() and 0 < value <= 5:
                return value

    # Android RatingBar 的 RangeInfo：min|max|current
    raw = node.get("range", "") or ""
    if raw:
        parts = raw.split("|")
        if len(parts) == 3:
            try:
                mn, mx, cur = map(float, parts)
            except ValueError:
                return None
            if mx <= 0:
                return None
            if mx <= 1.0:
                score = cur * 5
            elif mx <= 5.0:
                score = cur
            elif mx <= 10.0:
                score = cur / 2
            elif mx <= 100.0:
                score = cur / 20
            else:
                score = cur * 5 / mx
            if score > 0:
                return round(min(5.0, score), 1)
    return None


def average_rating(values):
    values = [v for v in values if v is not None and 0 < v <= 5]
    if not values:
        return None
    # 单条评价的星级只会是 0.5 的整数倍；4.3 / 4.7 / 3.7 这种一般是页面上的
    # 店铺汇总分（"口味 4.7"），混进来会把真实星级平均成小数。
    # 只要卡里存在半星值，就只按半星值算。
    half = [v for v in values if abs(v * 2 - round(v * 2)) < 1e-6]
    values = half or values
    return round(sum(values) / len(values), 1)


def parse_ui_nodes(nodes, width, height, shot_path=None, include_orphan=True, jd=False, stats=None):
    """返回 [{rating,review,user,date}]；有截图时优先数真实星星。

    stats 传入 CollectStats 时，把“读到卡片但正文为空 / 命中商家回复模板被丢掉”
    的样本也记一笔，避免采集端只统计有效样本、清洗率恒为 0。
    """
    if not nodes or width <= 0 or height <= 0:
        return []
    body_bottom = max([height] + [n["y"] + n["h"] for n in nodes])
    dates = [
        n for n in nodes
        if is_date_text(n["text"]) and n["y"] > height * 0.12
    ]
    dates.sort(key=lambda n: n["y"])
    if not dates:
        return []

    anchors = []
    for d in dates:
        u = pick_user(nodes, d, width)
        if jd and u in JD_UI_NAMES:
            u = ""
        anchors.append({"date": d, "user": u, "top": min(d["y"], next((n["y"] for n in nodes if n["text"] == u and abs(n["y"] - d["y"]) < 160), d["y"]))})

    rows = []
    for i, a in enumerate(anchors):
        top = a["top"] - 20
        bottom = anchors[i + 1]["top"] - 20 if i + 1 < len(anchors) else body_bottom * 0.995
        # 卡片顶部到第一条正文之间是用户名/日期/星级/人均/标签，正文从这些元信息之后开始
        exclude = {a["user"], a["date"]["text"]}
        cut = bottom
        if jd:
            # 京东卡片里“商家1天内回复”和“TA的推荐：”是独立节点，它们下面的内容
            # 是店家回复和推荐商品名，不是用户写的话：正文只读到最早的标记节点为止。
            marks = [n["y"] for n in nodes
                     if top <= n["y"] < bottom and n["text"] in JD_CUT_MARKS]
            if marks:
                cut = min(marks)
        body = pick_body(nodes, top + 40, cut, width, exclude, jd=jd)
        if not body:
            # 卡片在，但正文节点没暴露（京东常见：只有框架节点）；
            # 卡里只剩一句商家套话的，pick_body 也会当噪音丢掉，原因分开记
            reason = "正文为空"
            if any((is_merchant_reply(n["text"]) or MERCHANT_REPLY_RE.search(n["text"]))
                   and top <= n["y"] < cut for n in nodes):
                reason = "商家回复"
            if stats is not None:
                stats.note_drop(reason, "", a["date"]["text"], a["user"])
            continue
        # 商家回复是店家的套话，不是用户评价；短句命中模板就整条丢掉，
        # 否则它会顶着评价卡的日期和星级被当成一条真实评价收进去。
        if MERCHANT_REPLY_RE.search(body) and chinese_len(body) <= 40:
            if stats is not None:
                stats.note_drop("商家回复", body, a["date"]["text"], a["user"])
            continue
        # 标签/心情在日期和正文之间；真实星级优先从无障碍节点/截图星星数出来
        rating_values = []
        mood_node = None
        for n in nodes:
            # 屏幕顶部那一条是固定栏（店铺评分"评分 4.4"、搜索框），不属于任何一条评价
            if n["y"] < height * 0.12:
                continue
            if not (top <= n["y"] < bottom):
                continue
            r = extract_rating(n)
            if r is not None:
                rating_values.append(r)
            if n["text"] in MOODS:
                mood_node = n
                rating_values.append(mood_rating(n["text"]))
            elif is_star_only(n["text"]):
                rating_values.append(min(5, len(STAR_RE.findall(n["text"]))))
        if mood_node:
            star = stars_rating(shot_path, mood_node, width)
            if star is not None:
                rating_values.append(star)
        rating = average_rating(rating_values)
        rows.append({
            "rating": rating if rating is not None else "",
            "review": body,
            "user": a["user"],
            "date": a["date"]["text"],
        })
        if stats is not None:
            # 这张卡前面可能只露出框架被记成“正文为空”，现在读全了就撤掉
            stats.note_keep(body, a["date"]["text"], a["user"])

    if include_orphan and anchors:
        first_top = anchors[0]["top"] - 20
        orphan = pick_orphan_body(nodes, first_top, width, jd=jd)
        # 首条评价卡上方那段“孤立正文”如果是商家回复/店铺公告，就不是评价，丢掉
        if orphan and MERCHANT_REPLY_RE.search(orphan):
            if stats is not None:
                stats.note_drop("商家回复", orphan)
        elif orphan:
            rows.insert(0, {"rating": "", "review": orphan, "user": "", "date": ""})
    return rows


def merge_ui_rows(rows, max_reviews=10000):
    out = []
    for r in rows:
        text = clean_line(r.get("review", ""))
        if chinese_len(text) < 4:
            continue
        n = normalize(text)
        for old in out:
            on = normalize(old["review"])
            if n == on or n in on:
                break
            if on in n:
                old.update(r)
                break
        else:
            if len(out) < max_reviews:
                out.append(dict(r))
    return out
