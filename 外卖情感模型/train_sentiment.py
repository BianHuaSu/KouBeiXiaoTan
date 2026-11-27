# -*- coding: utf-8 -*-
"""
外卖评价情感模型训练（纯 numpy）
- 特征：字符 1~4gram signed hashing + 情感词典先验桶（含否定翻转）
- 数据：waimai_10k + 模板合成增强（覆盖“弹牙/筋道/汤头浓”等语料外表达）
- 输出：int8 量化权重 + 词典 + 温度/阈值，供手机浏览器离线推理

python train_sentiment.py
"""
import base64
import csv
import json
import math
import os
import random
import re
import time

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261124
random.seed(SEED)
rng = np.random.default_rng(SEED)

with open(os.path.join(BASE, "lexicon.json"), "r", encoding="utf-8") as f:
    LEX = json.load(f)
LEX_POS, LEX_NEG = LEX["pos"], LEX["neg"]
NEG_CHARS = ("不", "没", "无", "别", "未")
NON_NEG = ("不仅", "不但", "不只", "不光")


def is_negated(pre: str) -> bool:
    """前 4 字内出现否定词即翻转；「不仅/不但」这类让步词不算否定。"""
    if any(pre.endswith(x) for x in NON_NEG):
        return False
    return any(ch in pre for ch in NEG_CHARS)


def norm(t: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(t)).lower()


def fnv1a32(s: str) -> int:
    h = 2166136261
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def lex_counts(s: str):
    """返回 (正向词命中数, 负向词命中数)，支持前 2 字否定翻转。"""
    pos = neg = 0
    for words, sign in ((LEX_POS, 1), (LEX_NEG, -1)):
        for w in words:
            start = 0
            while True:
                i = s.find(w, start)
                if i < 0:
                    break
                pre = s[max(0, i - 4):i]
                if is_negated(pre):
                    sign_now = -sign
                else:
                    sign_now = sign
                if sign_now > 0:
                    pos += 1
                else:
                    neg += 1
                start = i + len(w)
    return pos, neg


def featurize(text: str, D: int, max_n: int):
    s = norm(text)
    mask = D - 1
    out = []
    for n in range(1, max_n + 1):
        for i in range(0, len(s) - n + 1):
            h = fnv1a32(str(n) + ":" + s[i:i + n])
            out.append((h & mask, -1.0 if (h >> 31) & 1 else 1.0))
    pos, neg = lex_counts(s)
    bucket = max(-8, min(8, pos - neg))
    for token in ("LB:%d" % bucket, "LP:%d" % min(pos, 4), "LN:%d" % min(neg, 4)):
        h = fnv1a32(token)
        out.append((h & mask, 1.0))
    return out


def build_matrix(texts, D, max_n):
    fids, vals, sids = [], [], []
    for i, t in enumerate(texts):
        for idx, sign in featurize(t, D, max_n):
            fids.append(idx); vals.append(sign); sids.append(i)
    return (np.asarray(fids, dtype=np.int32),
            np.asarray(vals, dtype=np.float32),
            np.asarray(sids, dtype=np.int32))


def sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def evaluate(z, y, thr):
    p = sigmoid(z)
    pred = (p >= thr).astype(np.int32)
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    acc = (tp + tn) / max(1, len(y))
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    return {"acc": acc, "P": prec, "R": rec, "F1": f1, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def train_once(X, y, sw, D, l2=2e-4, epochs=35, lr=0.06):
    fids, vals, sids = X
    n = len(y)
    w = np.zeros(D, dtype=np.float32)
    b = np.float32(0.0)
    m_w = np.zeros(D, dtype=np.float32); v_w = np.zeros(D, dtype=np.float32)
    m_b = np.float32(0.0); v_b = np.float32(0.0)
    y32 = y.astype(np.float32)
    sep = max(1, y.sum()); sn = max(1, n - y.sum())
    cw = np.where(y == 1, sn / sep, 1.0).astype(np.float32) * sw
    for ep in range(1, epochs + 1):
        z = np.bincount(sids, weights=w[fids] * vals, minlength=n).astype(np.float32) + b
        dz = ((sigmoid(z) - y32) * cw).astype(np.float32)
        g_w = np.bincount(fids, weights=(dz[sids] * vals), minlength=D).astype(np.float32) / n + l2 * w
        g_b = np.float32(dz.mean())
        m_w = 0.9 * m_w + 0.1 * g_w
        v_w = 0.999 * v_w + 0.001 * (g_w * g_w)
        m_b = np.float32(0.9 * m_b + 0.1 * g_b)
        v_b = np.float32(0.999 * v_b + 0.001 * g_b * g_b)
        w -= lr * (m_w / (1 - 0.9 ** ep)) / (np.sqrt(v_w / (1 - 0.999 ** ep)) + 1e-8)
        b -= lr * (m_b / (1 - 0.9 ** ep)) / (math.sqrt(v_b / (1 - 0.999 ** ep)) + 1e-8)
        if ep % 10 == 0 or ep == epochs:
            yield ep, w.copy(), float(b)


def best_threshold(z, y):
    best_t, best_f1 = 0.5, -1
    for t in np.arange(0.2, 0.81, 0.01):
        f1 = evaluate(z, y, t)["F1"]
        if f1 > best_f1:
            best_t, best_f1 = float(t), f1
    return best_t


def fit_temperature(z, y):
    best_t, best_nll = 1.0, 1e18
    for t in np.arange(0.6, 2.51, 0.05):
        p = np.clip(sigmoid(z / t), 1e-6, 1 - 1e-6)
        nll = float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
        if nll < best_nll:
            best_nll, best_t = nll, float(t)
    return best_t, best_nll


# ---------------- 合成增强（覆盖语料外表达，不复制原句） ----------------
DISHES = ["黄焖鸡", "麻辣烫", "奶茶", "烧烤", "沙拉", "寿司", "皮蛋瘦肉粥", "酸菜鱼", "小笼包", "卤肉饭",
          "炸鸡", "牛肉面", "饺子", "咖啡", "麻辣香锅", "水果切盒", "芋泥麻薯", "烤鱼", "蛋炒饭", "鸡肉卷",
          "排骨年糕", "番茄牛腩", "豆浆油条", "鲜虾粥", "饭团", "拌面", "肠粉", "寿喜锅", "盐焗鸡", "千层蛋糕"]
POS_ADJ = ["好吃", "香", "鲜", "嫩", "入味", "爽口", "筋道", "弹牙", "酥脆", "软糯", "多汁", "不柴",
           "不腥", "不腻", "不咸", "新鲜", "浓郁", "下饭", "开胃", "实在", "料足", "干净", "热乎", "划算"]
NEG_ADJ = ["难吃", "太咸", "齁咸", "寡淡", "油腻", "腥", "柴", "干硬", "凉了", "坨了", "夹生",
           "发酸", "有怪味", "一股料理包味", "死甜", "发苦", "分量少", "不新鲜", "洒了", "漏了", "太贵", "不值"]
ASPECTS = ["口味", "配送", "包装", "分量", "性价比"]


POS_CLAUSE = [
    "的汤头很浓，喝着很鲜", "炖得很烂，筷子一夹就脱骨", "外皮很酥，里面还有汁水",
    "米粒分明，配的三文鱼也厚切", "奶泡细腻，喝着不苦", "皮薄馅多，汤汁也不洒",
    "封口严实，一点没洒", "到手还是热的，冰还没化", "分量足，一大盒装得满满",
    "这个价格能吃到这些，挺划算", "肥瘦合适，酱汁不腻", "处理得干净，没有异味",
    "辣得很舒服，不是干辣", "甜度刚好，一点不齁", "面条筋道，放久了也不坨",
    "粥熬得很绵，虾也给得多", "菜叶很新鲜，鸡胸肉一点不柴", "酱汁单独装，没有漏",
    "中规中矩，不算踩雷", "没有想象中差，汤挺鲜的", "不算难吃，肉还挺嫩"
]
NEG_CLAUSE = [
    "汤淡得像白开水", "肉柴得咬不动", "皮厚馅少，一口全是面", "米粒夹生，三文鱼薄得透光",
    "奶泡粗糙，苦得像中药", "封口没封好，洒了一袋子", "到手全凉了，冰也化了",
    "大半盒都是配菜，肉只有几片", "这个价就这点量，太不值", "酱汁死甜，吃两口就腻",
    "一股料理包味，工业味很重", "辣得胃疼，像放了辣椒精", "甜得发齁，喝一口就腻",
    "面坨成一团，汤也凉了", "粥稀得像水，皮蛋只有一点", "菜叶发黄，鸡肉又干又硬",
    "餐具没给，盒子还压扁了", "等了七十分钟，骑手还送错楼"
]
SARC_CLAUSE = [
    "五星好评，鸡肉嫩到咬不动", "真是谢谢老板，让我知道外卖能这么难吃",
    "味道好到我在厕所蹲了半宿", "这么少的量，真是良心商家",
    "汤鲜到像白开水，真是绝了", "包装真严实，汤全洒袋子里了"
]


def make_synthetic(n=4500):
    rows = []
    for _ in range(n * 4):
        d = random.choice(DISHES)
        p = random.random()
        if p < 0.45:
            c1 = random.choice(POS_CLAUSE)
            if random.random() < 0.4:
                c2 = random.choice(POS_CLAUSE)
                txt = random.choice(["点的{d}，{c1}，{c2}", "{d}{c1}，{c2}", "这次{d}{c1}"])
                txt = txt.format(d=d, c1=c1, c2=c2)
            else:
                txt = random.choice(["点的{d}，{c1}", "{d}{c1}", "没想到{d}{c1}"]).format(d=d, c1=c1)
            lab = 1
        elif p < 0.75:
            c1 = random.choice(NEG_CLAUSE)
            if random.random() < 0.4:
                c2 = random.choice(NEG_CLAUSE)
                txt = random.choice(["点的{d}，{c1}，{c2}", "{d}{c1}，{c2}", "这次的{d}{c1}"]).format(d=d, c1=c1, c2=c2)
            else:
                txt = random.choice(["点的{d}，{c1}", "{d}{c1}", "不会再点{d}了，{c1}"]).format(d=d, c1=c1)
            lab = 0
        elif p < 0.9:
            bad = random.choice(["咸", "柴", "腥", "腻", "齁", "干", "油"])
            txt = random.choice([
                "点的{d}，{a}，一点都不{bad}", "{d}看着普通，但吃起来{a}，也不{bad}",
                "{d}的{asp}很{a}，没有{bad}味"
            ]).format(d=d, a=random.choice(["好吃", "香", "鲜", "嫩", "清爽", "入味"]),
                      bad=bad, asp=random.choice(ASPECTS))
            lab = 1
        else:
            txt = "点的{d}，" + random.choice(SARC_CLAUSE)
            lab = 0
        rows.append([txt, lab])
    seen, out = set(), []
    for txt, lab in rows:
        if txt in seen:
            continue
        seen.add(txt)
        out.append((txt, lab))
        if len(out) >= n:
            break
    return out


def load_rows():
    for path in [os.path.join(BASE, "waimai_10k.csv"), os.path.join(BASE, "..", "_build", "waimai_10k.csv")]:
        if os.path.exists(path):
            rows = []
            with open(path, "r", encoding="utf-8") as f:
                rd = csv.reader(f); next(rd)
                for line in rd:
                    if len(line) >= 2 and line[0] in ("0", "1") and line[1].strip():
                        rows.append((int(line[0]), line[1].strip()))
            print("语料:", path, len(rows))
            return rows
    raise SystemExit("找不到 waimai_10k.csv")


def split(rows):
    idx = list(range(len(rows))); random.shuffle(idx)
    n = len(rows); a, b = int(n * 0.7), int(n * 0.15)
    return [rows[i] for i in idx[:a]], [rows[i] for i in idx[a:a + b]], [rows[i] for i in idx[a + b:]]


def main():
    rows = load_rows()
    tr, va, te = split(rows)
    x_tr, y_tr = [r[1] for r in tr], np.array([r[0] for r in tr], np.int32)
    x_va, y_va = [r[1] for r in va], np.array([r[0] for r in va], np.int32)
    x_te, y_te = [r[1] for r in te], np.array([r[0] for r in te], np.int32)

    syn = make_synthetic(4500)
    x_syn, y_syn = [r[0] for r in syn], np.array([r[1] for r in syn], np.int32)
    print("合成增强:", len(syn), "正/负:", int(y_syn.sum()), int(len(y_syn) - y_syn.sum()))

    D, max_n = 1 << 19, 4
    Xtr = build_matrix(x_tr, D, max_n)
    Xva = build_matrix(x_va, D, max_n)
    Xte = build_matrix(x_te, D, max_n)
    Xsyn = build_matrix(x_syn, D, max_n)
    sw_tr = np.ones(len(y_tr), np.float32)
    sw_syn = np.full(len(y_syn), 0.45, np.float32)

    # 用训练集+增强训练，验证集标定
    Xtune_f = np.concatenate([Xtr[0], Xsyn[0]])
    Xtune_v = np.concatenate([Xtr[1], Xsyn[1]])
    Xtune_s = np.concatenate([Xtr[2], Xsyn[2] + len(y_tr)])
    tune = None
    for ep, w0, b0 in train_once((Xtune_f, Xtune_v, Xtune_s), np.concatenate([y_tr, y_syn]),
                                 np.concatenate([sw_tr, sw_syn]), D, epochs=30):
        tune = (w0, b0)
    z_va = np.bincount(Xva[2], weights=tune[0][Xva[0]] * Xva[1], minlength=len(y_va)) + tune[1]
    T, nll = fit_temperature(z_va, y_va)
    thr = best_threshold(z_va, y_va)
    print("标定: T=%.2f thr=%.2f valAcc=%.4f" % (T, thr, evaluate(z_va, y_va, thr)["acc"]))

    # 最终：训练+验证+增强
    Xf = np.concatenate([Xtr[0], Xva[0], Xsyn[0]])
    Xv = np.concatenate([Xtr[1], Xva[1], Xsyn[1]])
    Xs = np.concatenate([Xtr[2], Xva[2] + len(y_tr), Xsyn[2] + len(y_tr) + len(y_va)])
    y_all = np.concatenate([y_tr, y_va, y_syn])
    sw_all = np.concatenate([sw_tr, np.ones(len(y_va), np.float32), sw_syn])
    final = None
    for ep, w, b in train_once((Xf, Xv, Xs), y_all, sw_all, D, epochs=35):
        final = (ep, w, b)
    w, b = final[1], final[2]

    z_te = np.bincount(Xte[2], weights=w[Xte[0]] * Xte[1], minlength=len(y_te)) + b
    m = evaluate(z_te, y_te, thr)
    p_te = sigmoid(z_te / T)
    lo, hi = 0.40, 0.60
    neu_rate = float(((p_te >= lo) & (p_te <= hi)).mean())

    scale = float(np.abs(w).max()) / 127.0
    q = np.clip(np.round(w / scale), -127, 127).astype(np.int8)
    wq = q.astype(np.float32) * scale
    zq = np.bincount(Xte[2], weights=wq[Xte[0]] * Xte[1], minlength=len(y_te)) + b
    mq = evaluate(zq, y_te, thr)
    print("测试集: acc=%.4f P=%.4f R=%.4f F1=%.4f | int8: acc=%.4f F1=%.4f | 中性带 %.2f%%"
          % (m["acc"], m["P"], m["R"], m["F1"], mq["acc"], mq["F1"], neu_rate * 100))

    model = {
        "name": "waimai-sentiment-chargram-lr-lex",
        "version": "2026.11.24",
        "D": D, "max_n": max_n, "scale": scale, "bias": b, "T": T, "threshold": thr,
        "neutral": [lo, hi],
        "features": "char 1..4gram signed hashing + lexicon-prior buckets (negation-aware)",
        "lexicon": LEX,
        "metrics": {
            "testAcc": round(mq["acc"], 4), "testF1": round(mq["F1"], 4),
            "testP": round(mq["P"], 4), "testR": round(mq["R"], 4),
            "valAcc": round(evaluate(z_va, y_va, thr)["acc"], 4),
            "neutralRate": round(neu_rate, 4),
            "nOriginal": len(rows), "nTrain": len(tr) + len(va), "nSyn": len(syn),
            "nTest": len(te), "temperature": T, "threshold": thr
        },
        "weights_b64": base64.b64encode(q.tobytes()).decode("ascii"),
        "sizeKB": round(len(q.tobytes()) / 1024, 1)
    }
    out = os.path.join(BASE, "sentiment_model.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, separators=(",", ":"))
    print("模型:", out, round(os.path.getsize(out) / 1024, 1), "KB")

    # 自建泛化集（外部未见句式）评估
    ext = os.path.join(BASE, "external_test.tsv")
    if os.path.exists(ext):
        ey, et = [], []
        for line in open(ext, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2:
                ey.append(int(p[0])); et.append(p[1])
        ey = np.array(ey)
        ez = []
        for t in et:
            feats = featurize(t, D, max_n)
            ez.append(sum(float(wq[i]) * v for i, v in feats) + b)
        ez = np.array(ez)
        me = evaluate(ez, ey, thr)
        print("外部自建集: acc=%.4f P=%.4f R=%.4f F1=%.4f" % (me["acc"], me["P"], me["R"], me["F1"]))
        model.setdefault("metrics", {})["externalAcc"] = round(me["acc"], 4)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(model, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()


