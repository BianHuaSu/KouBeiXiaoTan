#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RapidOCR 封装：返回按阅读顺序排序的文字行。"""

from functools import lru_cache

from PIL import Image


@lru_cache(maxsize=1)
def get_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _box_metrics(box):
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def ocr_image(path, min_score=0.35):
    """OCR 一张图片，返回 [{text,x,y,w,h,score}]，按 y/x 排序。"""
    engine = get_engine()
    result, _ = engine(str(path))
    lines = []
    for item in result or []:
        try:
            box, text, score = item[0], item[1], float(item[2])
        except Exception:
            continue
        text = (text or "").strip()
        if not text or score < min_score:
            continue
        x, y, w, h = _box_metrics(box)
        lines.append({"text": text, "x": x, "y": y, "w": w, "h": h, "score": score})
    lines.sort(key=lambda z: (z["y"], z["x"]))
    return lines


def ocr_image_cropped(path, crop=None, min_score=0.35):
    """crop=(top,bottom,left,right) 为 0–1 比例；不传则原图。"""
    if not crop or not any(crop):
        return ocr_image(path, min_score=min_score)
    img = Image.open(path)
    w, h = img.size
    top, bottom, left, right = crop
    box = (int(w * left), int(h * top), int(w * (1 - right)), int(h * (1 - bottom)))
    tmp = path.with_name(path.stem + "_crop.png")
    img.crop(box).save(tmp)
    try:
        return ocr_image(tmp, min_score=min_score)
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
