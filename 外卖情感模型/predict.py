# -*- coding: utf-8 -*-
"""
加载 sentiment_model.json，做单条 / 批量推理。
用法：
  python predict.py "这家麻辣烫太咸了，菜也少"
  python predict.py --file eval.tsv
"""
import base64
import json
import os
import re
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))


def fnv1a32(s: str) -> int:
    h = 2166136261
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def norm(t: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", str(t)).lower()


class SentimentModel:
    def __init__(self, path=None):
        path = path or os.path.join(BASE, "sentiment_model.json")
        with open(path, "r", encoding="utf-8") as f:
            m = json.load(f)
        self.D = m["D"]
        self.max_n = m["max_n"]
        self.scale = m["scale"]
        self.bias = m["bias"]
        self.T = m["T"]
        self.thr = m["threshold"]
        self.neutral = m["neutral"]
        self.lex = m["lexicon"]
        self.w = np.frombuffer(base64.b64decode(m["weights_b64"]), dtype=np.int8).astype(np.float32) * self.scale
        self.metrics = m["metrics"]

    def lex_counts(self, s):
        pos = neg = 0
        for words, sign in ((self.lex["pos"], 1), (self.lex["neg"], -1)):
            for w in words:
                start = 0
                while True:
                    i = s.find(w, start)
                    if i < 0:
                        break
                    pre = s[max(0, i - 4):i]
                    flip = any(ch in pre for ch in ("不", "没", "无", "别", "未"))
                    if any(pre.endswith(x) for x in ("不仅", "不但", "不只", "不光")):
                        flip = False
                    now = -sign if flip else sign
                    if now > 0:
                        pos += 1
                    else:
                        neg += 1
                    start = i + len(w)
        return pos, neg

    def features(self, text):
        s = norm(text)
        out = []
        mask = self.D - 1
        for n in range(1, self.max_n + 1):
            for i in range(0, len(s) - n + 1):
                h = fnv1a32(str(n) + ":" + s[i:i + n])
                out.append((h & mask, -1.0 if (h >> 31) & 1 else 1.0))
        pos, neg = self.lex_counts(s)
        bucket = max(-8, min(8, pos - neg))
        for token in ("LB:%d" % bucket, "LP:%d" % min(pos, 4), "LN:%d" % min(neg, 4)):
            h = fnv1a32(token)
            out.append((h & mask, 1.0))
        return out

    def logit(self, text):
        f = self.features(text)
        if not f:
            return 0.0
        idx = np.fromiter((x[0] for x in f), dtype=np.int32)
        val = np.fromiter((x[1] for x in f), dtype=np.float32)
        return float((self.w[idx] * val).sum() + self.bias)

    def predict(self, text):
        z = self.logit(text)
        p = 1.0 / (1.0 + np.exp(-z / self.T))
        lo, hi = self.neutral
        label = "正" if p > hi else ("负" if p < lo else "中性")
        return {"label": label, "prob": round(float(p), 4), "logit": round(z, 3)}

    def top_features(self, text, k=6):
        s = norm(text)
        contrib = {}
        for n in range(1, self.max_n + 1):
            for i in range(0, len(s) - n + 1):
                g = s[i:i + n]
                h = fnv1a32(str(n) + ":" + g)
                sign = -1.0 if (h >> 31) & 1 else 1.0
                wv = self.w[h & (self.D - 1)] * sign
                if len(g) >= 2:
                    contrib[g] = contrib.get(g, 0.0) + float(wv)
        items = sorted(contrib.items(), key=lambda x: abs(x[1]), reverse=True)[:k]
        return [{"词": w_, "贡献": round(v, 3)} for w_, v in items]


def eval_file(model, path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            rows.append((int(parts[0]), parts[1]))
    y = np.array([r[0] for r in rows])
    p = np.array([1.0 / (1.0 + np.exp(-model.logit(r[1]) / model.T)) for r in rows])
    pred = (p > model.neutral[1]).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    fp = int(((pred == 1) & (y == 0)).sum()); fn = int(((pred == 0) & (y == 1)).sum())
    acc = (tp + tn) / len(y)
    prec = tp / max(1, tp + fp); rec = tp / max(1, tp + fn)
    f1 = 2 * prec * rec / max(1e-9, prec + rec)
    print(f"{path}: n={len(y)} acc={acc:.4f} P={prec:.4f} R={rec:.4f} F1={f1:.4f} (中性带不计入正类)")
    for lab, txt in rows:
        r = model.predict(txt)
        if (r["label"] == "正") != (lab == 1):
            print("  错例:", lab, r, txt[:50])
    return {"acc": acc, "P": prec, "R": rec, "F1": f1, "n": len(y)}


if __name__ == "__main__":
    m = SentimentModel()
    print("模型:", m.metrics)
    if len(sys.argv) >= 3 and sys.argv[1] == "--file":
        eval_file(m, sys.argv[2])
    else:
        texts = sys.argv[1:] or ["这家麻辣烫太咸了，菜也少，不会再来"]
        for t in texts:
            print(t, "->", m.predict(t), m.top_features(t, 5))


