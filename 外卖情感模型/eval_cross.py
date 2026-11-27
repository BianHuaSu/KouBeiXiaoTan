# -*- coding: utf-8 -*-
"""跨领域检查：用酒店评论语料测外卖情感模型的迁移表现（仅作参考，不参与调参）。"""
import csv
import random
import sys

from predict import SentimentModel

random.seed(7)
rows = []
with open("chn.csv", "r", encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        t = (r.get("review") or "").strip()
        if t:
            rows.append((t, int(r["label"])))
pos = [x for x in rows if x[1] == 1]
neg = [x for x in rows if x[1] == 0]
k = min(1200, len(pos), len(neg))
sample = random.sample(pos, k) + random.sample(neg, k)

m = SentimentModel()
tp = tn = fp = fn_ = neu = 0
for text, y in sample:
    p = m.predict(text)["prob"]
    if 0.40 <= p <= 0.60:
        neu += 1
        if y == 1:
            fn_ += 1
        else:
            fp += 1
        continue
    pred = 1 if p > 0.5 else 0
    if pred == 1 and y == 1:
        tp += 1
    elif pred == 0 and y == 0:
        tn += 1
    elif pred == 1:
        fp += 1
    else:
        fn_ += 1

n = len(sample)
acc = (tp + tn) / n
print("跨领域(酒店评论) n=%d acc=%.4f neutral=%.2f%%  TP=%d TN=%d FP=%d FN=%d" % (n, acc, neu / n * 100, tp, tn, fp, fn_))
print("错例示例：")
shown = 0
for text, y in sample:
    p = m.predict(text)["prob"]
    pred = None if 0.40 <= p <= 0.60 else (1 if p > 0.5 else 0)
    if pred != y and shown < 8:
        print("  y=%s p=%.3f %s" % (y, p, text[:70]))
        shown += 1

