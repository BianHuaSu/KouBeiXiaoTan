# -*- coding: utf-8 -*-
"""导出外部集逐条概率，供 Node 端做数值一致性比对。"""
import json

from predict import SentimentModel

m = SentimentModel()
rows = []
with open("external_test.tsv", "r", encoding="utf-8") as f:
    for line in f:
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 2 and parts[1].strip():
            rows.append([parts[1], round(m.predict(parts[1])["prob"], 6)])
with open("jscheck.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False)
print("rows", len(rows))
