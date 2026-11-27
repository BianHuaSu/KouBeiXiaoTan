#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把手机截图/录屏抽帧批量 OCR，导出评论 CSV。

用法：
  python ocr_collect.py --input "截图文件夹"
  python ocr_collect.py --input "截图文件夹" --mode card
"""

import argparse
import sys
from pathlib import Path

from common import CollectStats, make_out_dir, parse_screen, write_outputs
from ocr_core import ocr_image_cropped

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def log(msg):
    print(msg, flush=True)


def collect_images(input_path):
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"找不到：{p}")
    if p.is_file():
        return [p]
    return sorted([x for x in p.iterdir() if x.suffix.lower() in IMAGE_EXTS], key=lambda x: x.name)


def parse_crop(text):
    if not text:
        return None
    parts = [float(x.strip()) for x in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop 需要四个比例：top,bottom,left,right")
    return tuple(max(0.0, min(0.5, x)) for x in parts)


def main():
    ap = argparse.ArgumentParser(description="手机截图 OCR 导入")
    ap.add_argument("--input", required=True, help="截图文件或文件夹")
    ap.add_argument("--out", help="输出目录；默认 output/时间_OCR采集")
    ap.add_argument("--mode", choices=["screen", "card"], default="screen",
                    help="screen=一屏多条；card=一张图一条")
    ap.add_argument("--crop", default="0,0,0,0", help="裁剪比例 top,bottom,left,right，如 0.04,0.02,0,0")
    ap.add_argument("--min-score", type=float, default=0.35, help="OCR 置信度下限")
    args = ap.parse_args()

    try:
        crop = parse_crop(args.crop)
    except ValueError as e:
        log(str(e))
        sys.exit(2)

    images = collect_images(args.input)
    if not images:
        log("没有找到图片（支持 png/jpg/jpeg/webp/bmp）。")
        sys.exit(3)

    out_dir = Path(args.out) if args.out else make_out_dir("OCR采集")
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "ocr_raw.txt"
    all_rows = []
    stats = CollectStats()
    raw_blocks = []

    log(f"共 {len(images)} 张图片，OCR 模型首次加载可能需要几秒……")
    for idx, img in enumerate(images, 1):
        try:
            lines = ocr_image_cropped(img, crop, args.min_score)
        except Exception as e:
            log(f"[{idx}/{len(images)}] {img.name} OCR 失败：{e}")
            continue
        rows = parse_screen(lines, args.mode, stats=stats)
        for r in rows:
            r["source"] = "ocr"
            r["page"] = img.name
        all_rows.extend(rows)
        raw_blocks.append(f"===== {img.name} =====")
        raw_blocks.extend([x["text"] for x in lines])
        log(f"[{idx}/{len(images)}] {img.name}：识别 {len(lines)} 行，提取 {len(rows)} 条")
        if idx % 10 == 0:
            write_outputs(all_rows, out_dir, "ocr", make_page=False, stats=stats)

    raw_path.write_text("\n".join(raw_blocks), encoding="utf-8")
    full, demo, page = write_outputs(all_rows, out_dir, "ocr", shop_name="手机截图 OCR", stats=stats)
    if stats.dropped:
        detail = " · ".join(f"{k} {v}" for k, v in stats.reasons().most_common())
        log(f"完成：原始 {len(all_rows) + stats.dropped} 条 · 有效 {len(all_rows)} 条 · "
            f"过滤 {stats.dropped} 条（{detail}）")
    else:
        log(f"完成，共 {len(all_rows)} 条")
    log(f"完整数据：{full}")
    log(f"Demo 上传用：{demo}")
    if page:
        log(f"预载分析页：{page}")
    log(f"OCR 原始文本：{raw_path}")


if __name__ == "__main__":
    main()
