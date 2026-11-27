# -*- coding: utf-8 -*-
"""把 sentiment_model.json 内联进一个手机端单文件 HTML（零依赖、零网络）。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "外卖情感模型-手机版.html")

with open(os.path.join(BASE, "sentiment_model.json"), "r", encoding="utf-8") as f:
    model = json.load(f)
met = model["metrics"]
model_json = json.dumps(model, ensure_ascii=False, separators=(",", ":"))
size_kb = os.path.getsize(os.path.join(BASE, "sentiment_model.json")) / 1024

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#FBF6EC">
<title>外卖情感模型 · 手机离线版</title>
<style>
:root{
  --bg:#FBF6EC; --paper:#FFFDF7; --ink:#1A1611; --muted:#6E6255;
  --line:#E6D9C5; --accent:#E4572E; --green:#2F7A5B; --red:#C2453B;
  --amber:#B7791F; --shadow:0 18px 40px -28px rgba(58,42,24,.45);
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0;background:var(--bg);color:var(--ink)}
body{
  font-family:"PingFang SC","HarmonyOS Sans SC","Source Han Sans SC","Microsoft YaHei",system-ui,-apple-system,sans-serif;
  line-height:1.65;-webkit-font-smoothing:antialiased;
  background-image:radial-gradient(1200px 600px at 80% -10%, #F6E7D2 0%, transparent 60%),
                   radial-gradient(900px 500px at -10% 30%, #F2EADB 0%, transparent 55%);
}
.shell{max-width:720px;margin:0 auto;padding:28px 18px calc(40px + env(safe-area-inset-bottom))}
.hero{padding:8px 4px 22px}
.kicker{display:flex;align-items:center;gap:8px;font-size:12px;letter-spacing:.14em;color:var(--accent);font-weight:600;text-transform:uppercase}
.kicker i{width:18px;height:2px;background:var(--accent);display:block}
h1{font-size:clamp(26px,7.4vw,38px);line-height:1.22;margin:12px 0 10px;letter-spacing:-.02em}
h1 em{font-style:normal;color:var(--accent)}
.sub{color:var(--muted);font-size:14.5px;max-width:34em;margin:0}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.badge{font-size:12px;padding:5px 10px;border:1px solid var(--line);border-radius:999px;background:rgba(255,253,247,.7);color:#4B4033}
.badge b{font-weight:600;color:var(--ink)}
.badge.green{border-color:#CCE0D5;background:#F1F8F4;color:var(--green)}
.card{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px;box-shadow:var(--shadow);margin-bottom:16px}
.card-head{display:flex;align-items:baseline;gap:10px;margin-bottom:12px}
.no{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--accent);border:1px solid #F0C6B4;background:#FDF1EA;border-radius:6px;padding:1px 6px}
h2{font-size:17px;margin:0;letter-spacing:-.01em}
.card-head .hint{margin-left:auto;font-size:11.5px;color:var(--muted)}
textarea{width:100%;border:1px solid var(--line);border-radius:12px;background:#FFFCF6;color:var(--ink);
  padding:13px 14px;font:inherit;font-size:16px;line-height:1.7;resize:vertical;min-height:96px;outline:none}
textarea:focus{border-color:#E9B49E;box-shadow:0 0 0 3px rgba(228,87,46,.10)}
textarea::placeholder{color:#A99C8B}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 14px}
.chip{font-size:12.5px;padding:7px 11px;border-radius:999px;border:1px dashed #DCCDB8;background:#FFF9EF;color:#5D5041;cursor:pointer}
.chip:active{transform:scale(.98)}
.actions{display:flex;align-items:center;gap:10px}
button{border:0;border-radius:10px;font:inherit;font-size:15px;cursor:pointer}
.primary{background:var(--ink);color:#FFF8EC;padding:11px 20px;font-weight:600;box-shadow:0 8px 18px -12px rgba(26,22,17,.8)}
.primary:active{background:#332A20}
.ghost{background:transparent;color:var(--muted);padding:11px 8px;border:1px solid transparent}
.ghost:hover{color:var(--ink)}
.ms{margin-left:auto;font-family:ui-monospace,Menlo,monospace;font-size:11px;color:#9C8F7F}
.hidden{display:none}
/* 结果 */
.result{padding:20px 18px 16px;position:relative;overflow:hidden}
.result:before{content:"";position:absolute;inset:0 auto 0 0;width:4px;background:var(--muted)}
.result.pos:before{background:var(--green)} .result.neg:before{background:var(--red)} .result.neu:before{background:var(--amber)}
.verdict{display:flex;align-items:flex-end;justify-content:space-between;gap:14px}
.v-label{font-size:34px;font-weight:700;letter-spacing:-.03em;line-height:1.1}
.pos .v-label{color:var(--green)} .neg .v-label{color:var(--red)} .neu .v-label{color:var(--amber)}
.v-label small{display:block;font-size:11px;font-weight:500;letter-spacing:.12em;color:#9C8F7F;margin-top:4px}
.v-prob{text-align:right;font-family:ui-monospace,Menlo,monospace}
.v-prob span{font-size:26px;font-weight:600}
.v-prob small{display:block;font-size:10.5px;color:#9C8F7F;letter-spacing:.08em}
.gauge{position:relative;height:12px;border-radius:999px;margin:18px 0 6px;
  background:linear-gradient(90deg,#E5A79F 0%,#E9C3A8 34%,#DCD2C3 50%,#A9C9B7 66%,#7DB49A 100%)}
.band{position:absolute;left:40%;width:20%;top:-3px;bottom:-3px;border-left:1px dashed rgba(26,22,17,.28);border-right:1px dashed rgba(26,22,17,.28);background:rgba(255,255,255,.25)}
.marker{position:absolute;top:-7px;width:4px;height:26px;background:var(--ink);border-radius:3px;transform:translateX(-50%);transition:left .35s cubic-bezier(.2,.8,.3,1)}
.ticks{display:flex;justify-content:space-between;font-family:ui-monospace,Menlo,monospace;font-size:10px;color:#A99C8B;margin-top:2px}
.why-label{font-size:12px;color:var(--muted);margin:16px 0 6px;display:flex;align-items:center;gap:6px}
.frags{display:flex;flex-wrap:wrap;gap:6px}
.frag{font-size:12.5px;border-radius:8px;padding:4px 8px;background:#F7F1E5;border:1px solid #EADFCD;font-family:ui-monospace,"PingFang SC",monospace}
.frag.p{color:var(--green);background:#F0F7F3;border-color:#D3E5DA}
.frag.n{color:var(--red);background:#FBEFEC;border-color:#EFCFC8}
.frag b{font-weight:600}
.lex{margin-top:10px;font-size:12px;color:var(--muted);line-height:1.9}
.lex .w{display:inline-block;margin-right:6px;padding:1px 7px;border-radius:6px;background:#F4ECDD;color:#5D5041}
.lex .w.p{color:var(--green);background:#EDF5F0}
.lex .w.n{color:var(--red);background:#F9EAE6}
.privacy{margin-top:12px;font-size:11px;color:#A2947F}
/* 批量 */
details.card summary{list-style:none;display:flex;align-items:center;gap:10px;cursor:pointer}
details.card summary::-webkit-details-marker{display:none}
summary h2{font-size:16px}
summary .arrow{margin-left:auto;font-size:12px;color:var(--muted)}
details[open] summary .arrow{transform:rotate(180deg)}
.batch-body{padding-top:14px}
.batch-body textarea{min-height:80px;font-size:14px}
.batch-meta{display:flex;align-items:center;gap:10px;margin-top:10px}
.batch-sum{margin-top:12px;font-size:12.5px;color:var(--muted)}
.batch-sum b{color:var(--ink)}
.rows{margin-top:8px;border-top:1px solid var(--line)}
.row{display:grid;grid-template-columns:1fr 64px 48px;gap:8px;align-items:center;padding:9px 2px;border-bottom:1px solid #F0E6D6;font-size:12.5px}
.row .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#3D342A}
.row .l{text-align:center;font-weight:600;border-radius:6px;padding:2px 0;font-size:11.5px}
.row .p{text-align:right;font-family:ui-monospace,Menlo,monospace;color:#8B7D6B}
.row .l.pos{color:var(--green);background:#EFF6F1}
.row .l.neg{color:var(--red);background:#FAECE8}
.row .l.neu{color:var(--amber);background:#FBF1DD}
/* 模型卡 */
.stats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:6px}
.stat{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:#FFFCF5}
.stat .k{font-size:10.5px;letter-spacing:.08em;color:#9C8F7F;text-transform:uppercase}
.stat .v{font-family:ui-monospace,Menlo,monospace;font-size:20px;font-weight:600;letter-spacing:-.02em;margin-top:2px}
.stat .v small{font-size:11px;font-weight:400;color:var(--muted)}
.note{margin-top:14px;font-size:12.5px;color:var(--muted)}
.note ul{margin:8px 0 0;padding-left:18px}
.note li{margin:4px 0}
footer{text-align:center;color:#A2947F;font-size:11px;padding:10px 0 0;line-height:1.9}
@media (min-width:640px){
  .shell{padding-top:46px}
  .stats{grid-template-columns:repeat(4,1fr)}
}
</style>
</head>
<body>
<main class="shell">

<header class="hero">
  <div class="kicker"><i></i>口碑小探 · 情感引擎</div>
  <h1>一个能在手机上<br><em>离线跑</em>的外卖情感模型</h1>
  <p class="sub">字符 n-gram + 情感词典先验的逻辑回归，模型 __SIZE__ KB，推理全在本页 JavaScript 里完成：不联网、不上传、不调用云端大模型。</p>
  <div class="badges">
    <span class="badge green">● 本地推理</span>
    <span class="badge"><b id="szBadge">__SIZE__ KB</b> int8 模型</span>
    <span class="badge"><b>0</b> 网络请求</span>
    <span class="badge">语料测试 <b>__ACC__%</b></span>
  </div>
</header>

<section class="card input">
  <div class="card-head"><span class="no">01</span><h2>输入一条评价</h2><span class="hint">口语 / 错别字也行</span></div>
  <textarea id="ta" placeholder="例如：这家麻辣烫太咸了，菜也少，不会再来"></textarea>
  <div class="chips" id="chips"></div>
  <div class="actions">
    <button class="primary" id="run">分析这条评价</button>
    <button class="ghost" id="clear">清空</button>
    <span class="ms" id="ms"></span>
  </div>
</section>

<section class="card result hidden" id="result">
  <div class="verdict">
    <div class="v-label" id="vLabel">负向<small>NEGATIVE</small></div>
    <div class="v-prob"><span id="vProb">0.12</span><small>正向概率 p</small></div>
  </div>
  <div class="gauge"><div class="band"></div><div class="marker" id="marker" style="left:12%"></div></div>
  <div class="ticks"><span>0</span><span>0.40 中性</span><span>0.60</span><span>1</span></div>
  <div class="why-label">模型重点参考的片段 <span style="color:#B3A592">（+ 拉正向 / − 拉负向）</span></div>
  <div class="frags" id="vWhy"></div>
  <div class="lex" id="vLex"></div>
  <div class="privacy">这条文本没有离开你的手机。</div>
</section>

<details class="card batch">
  <summary><span class="no">02</span><h2>批量测一批</h2><span class="arrow">⌄</span></summary>
  <div class="batch-body">
    <textarea id="batchTa" placeholder="每行一条评价，最多 80 条。可把 CSV 里的一列直接粘进来。"></textarea>
    <div class="batch-meta"><button class="primary" id="batchRun">批量分析</button><span class="ms" id="batchMs"></span></div>
    <div class="batch-sum" id="batchSum"></div>
    <div class="rows" id="batchRows"></div>
  </div>
</details>

<section class="card modelcard">
  <div class="card-head"><span class="no">03</span><h2>模型卡</h2><span class="hint">离线训练 · 端侧推理</span></div>
  <div class="stats">
    <div class="stat"><div class="k">训练语料</div><div class="v">__N__<small> 条</small></div></div>
    <div class="stat"><div class="k">合成增强</div><div class="v">__NSYN__<small> 条</small></div></div>
    <div class="stat"><div class="k">测试准确率</div><div class="v">__ACC__<small>%</small></div></div>
    <div class="stat"><div class="k">F1</div><div class="v">__F1__<small>%</small></div></div>
  </div>
  <div class="note">
    特征：中文单字到四字组合，FNV-1a 哈希到 2<sup>19</sup> 桶（带符号），再加情感词典计数桶；分类器为 L2 正则逻辑回归；导出时 int8 量化。
    <ul>
      <li>数据来自公开外卖评论语料（__N__ 条），另加 __NSYN__ 条模板合成句，专门补“筋道、弹牙、炖得烂、不齁”这类语料里少见但真实存在的表达。</li>
      <li>它只懂外卖短评。换到酒店长评论这类跨领域文本，实测只有约 69%，说明它是“专用小模型”而不是通用情感模型。</li>
      <li>反讽、双重否定、整段褒贬混写仍是弱项，长评论建议拆成单条观点再判断。</li>
    </ul>
  </div>
</section>

<footer>口碑小探 · 外卖评价智能分析 Agent<br>模型与推理均在本文件内 · 无外部依赖</footer>
</main>

<script>
/* ====== 模型权重（由 train_sentiment.py 训练后内联） ====== */
const M = __MODEL__;

/* ====== 推理实现：与 Python 端逐字节对齐 ====== */
const enc = new TextEncoder();
const MASK = M.D - 1;
const RAW = Uint8Array.from(atob(M.weights_b64), c => c.charCodeAt(0));
const wCache = new Float32Array(M.D);
for (let i = 0; i < M.D; i++) {
  const v = RAW[i];
  wCache[i] = (v > 127 ? v - 256 : v) * M.scale;
}
function norm(t) {
  return String(t).replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, "").toLowerCase();
}
function fnv(str) {
  let h = 2166136261 >>> 0;
  const b = enc.encode(str);
  for (let i = 0; i < b.length; i++) {
    h = (h ^ b[i]) >>> 0;
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}
const NEG_CHARS = ["不", "没", "无", "别", "未"];
const NON_NEG = ["不仅", "不但", "不只", "不光"];
function isNegated(pre) {
  if (NON_NEG.some(x => pre.endsWith(x))) return false;
  return NEG_CHARS.some(x => pre.includes(x));
}
function lexCounts(s) {
  let pos = 0, neg = 0;
  const scan = (words, sign) => {
    for (const w of words) {
      let start = 0;
      while (true) {
        const i = s.indexOf(w, start);
        if (i < 0) break;
        const pre = s.slice(Math.max(0, i - 4), i);
        let now = isNegated(pre) ? -sign : sign;
        if (now > 0) pos++; else neg++;
        start = i + w.length;
      }
    }
  };
  scan(M.lexicon.pos, 1);
  scan(M.lexicon.neg, -1);
  return [pos, neg];
}
function lexHits(s) {
  const hits = [];
  for (const [words, tag] of [[M.lexicon.pos, "p"], [M.lexicon.neg, "n"]]) {
    for (const w of words) {
      if (!s.includes(w)) continue;
      const i = s.indexOf(w);
      const pre = s.slice(Math.max(0, i - 4), i);
      const flipped = isNegated(pre);
      hits.push({ w, tag: flipped ? (tag === "p" ? "n" : "p") : tag, flipped, len: w.length });
    }
  }
  return hits.sort((a, b) => b.len - a.len).slice(0, 12);
}
function featurize(text) {
  const s = norm(text);
  const grams = [];
  for (let n = 1; n <= M.max_n; n++) {
    for (let i = 0; i + n <= s.length; i++) {
      const g = s.slice(i, i + n);
      const h = fnv(n + ":" + g);
      grams.push({ g, h, sign: ((h >>> 31) & 1) ? -1 : 1, w: wCache[h & MASK] });
    }
  }
  const [pos, neg] = lexCounts(s);
  const bucket = Math.max(-8, Math.min(8, pos - neg));
  for (const tok of ["LB:" + bucket, "LP:" + Math.min(pos, 4), "LN:" + Math.min(neg, 4)]) {
    const h = fnv(tok);
    grams.push({ g: tok, h, sign: 1, w: wCache[h & MASK] });
  }
  return { s, grams, pos, neg };
}
function predict(text) {
  const f = featurize(text);
  let z = M.bias;
  for (const it of f.grams) z += it.sign * it.w;
  const p = 1 / (1 + Math.exp(-z / M.T));
  const label = p > M.neutral[1] ? "正" : (p < M.neutral[0] ? "负" : "中性");
  return { p, z, label, f };
}
function topFrags(f, k = 8) {
  const map = new Map();
  for (const it of f.grams) {
    if (it.g.startsWith("L") && it.g.includes(":")) continue;
    if (it.g.length < 2) continue;
    map.set(it.g, (map.get(it.g) || 0) + it.sign * it.w);
  }
  return [...map.entries()]
    .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .slice(0, k)
    .map(([g, v]) => ({ g, v }));
}

/* ====== 渲染 ====== */
const $ = id => document.getElementById(id);
const EXAMPLES = [
  "这家麻辣烫太咸了，菜也少，不会再来",
  "鸡肉炖得烂，汤汁拌饭能干三碗，下次还点",
  "五星好评，鸡肉嫩到咬不动，汤鲜到像白开水",
  "味道中规中矩，不算踩雷，价格也合适"
];
function esc(s) { return String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

function render(text) {
  const t0 = performance.now();
  const r = predict(text);
  const dt = Math.max(1, Math.round(performance.now() - t0));
  $("result").className = "card result " + (r.label === "正" ? "pos" : r.label === "负" ? "neg" : "neu");
  $("vLabel").innerHTML = r.label + "向<small>" + (r.label === "正" ? "POSITIVE" : r.label === "负" ? "NEGATIVE" : "NEUTRAL") + "</small>";
  $("vProb").textContent = r.p.toFixed(3);
  $("marker").style.left = (r.p * 100).toFixed(1) + "%";
  const frags = topFrags(r.f, 8);
  $("vWhy").innerHTML = frags.map(x =>
    '<span class="frag ' + (x.v >= 0 ? "p" : "n") + '">' + esc(x.g) + ' <b>' + (x.v >= 0 ? "+" : "") + x.v.toFixed(2) + "</b></span>"
  ).join("");
  const hits = lexHits(r.f.s);
  $("vLex").innerHTML = hits.length
    ? "命中情感词典：" + hits.map(h => '<span class="w ' + h.tag + '">' + esc(h.w) + (h.flipped ? "（被否定）" : "") + "</span>").join("")
    : "情感词典没有命中，完全靠字符组合判断。";
  $("ms").textContent = dt + " ms · 本机";
  if (!text.trim()) $("result").classList.add("hidden");
}

$("chips").innerHTML = EXAMPLES.map((t, i) => '<button class="chip" data-i="' + i + '">' + esc(t.length > 16 ? t.slice(0, 16) + "…" : t) + "</button>").join("");
$("chips").addEventListener("click", e => {
  const b = e.target.closest(".chip");
  if (!b) return;
  $("ta").value = EXAMPLES[+b.dataset.i];
  render($("ta").value);
});
$("run").addEventListener("click", () => {
  const t = $("ta").value.trim();
  if (!t) { $("ta").focus(); return; }
  render(t);
});
$("clear").addEventListener("click", () => {
  $("ta").value = ""; $("result").classList.add("hidden"); $("ms").textContent = ""; $("ta").focus();
});

/* 批量 */
$("batchRun").addEventListener("click", () => {
  const lines = $("batchTa").value.split(/\r?\n/).map(s => s.trim()).filter(s => s.length >= 2).slice(0, 80);
  if (!lines.length) { $("batchTa").focus(); return; }
  const t0 = performance.now();
  const out = lines.map(t => ({ t, r: predict(t) }));
  const dt = Math.round(performance.now() - t0);
  const c = { 正: 0, 负: 0, 中性: 0 };
  out.forEach(o => c[o.r.label]++);
  $("batchSum").innerHTML = "共 <b>" + out.length + "</b> 条：正向 <b>" + c.正 + "</b> · 负向 <b>" + c.负 + "</b> · 中性 <b>" + c.中性 + "</b> ｜ 负向占比 <b>" + (c.负 / out.length * 100).toFixed(1) + "%</b>";
  $("batchRows").innerHTML = out.map((o, i) =>
    '<div class="row"><div class="t">' + (i + 1) + ". " + esc(o.t) + '</div><div class="l ' + (o.r.label === "正" ? "pos" : o.r.label === "负" ? "neg" : "neu") + '">' + o.r.label + '</div><div class="p">' + o.r.p.toFixed(2) + "</div></div>"
  ).join("");
  $("batchMs").textContent = dt + " ms / " + out.length + " 条";
});

/* 支持 ?t=文本 直接出结果 */
const q = new URLSearchParams(location.search).get("t");
if (q) { $("ta").value = q; render(q); }
</script>
</body>
</html>
"""

html = (HTML
        .replace("__MODEL__", model_json)
        .replace("__ACC__", "%.1f" % (met["testAcc"] * 100))
        .replace("__F1__", "%.1f" % (met["testF1"] * 100))
        .replace("__N__", "{:,}".format(met.get("nOriginal", 11987)))
        .replace("__NSYN__", "{:,}".format(met.get("nSyn", 4500)))
        .replace("__SIZE__", "%.0f" % size_kb))
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print(OUT, "%.1f KB" % (os.path.getsize(OUT) / 1024))
