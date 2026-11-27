// 校验：直接抽取页面里的 JS 推理代码，在 Node 里复算，确认与 Python 端一致。
const fs = require("fs");
const path = require("path");

const page = fs.readFileSync(path.join(__dirname, "外卖情感模型-手机版.html"), "utf8");
const m = page.match(/<script>([\s\S]*)<\/script>/);
if (!m) throw new Error("script not found");
const src = m[1].split("/* ====== 渲染 ====== */")[0];
const { predict } = new Function(src + "\nreturn { predict };")( );

const lines = fs.readFileSync(path.join(__dirname, "external_test.tsv"), "utf8").trim().split(/\r?\n/).slice(1);
let ok = 0, n = 0, neu = 0;
const rows = [];
for (const line of lines) {
  const [label, text] = line.split("\t");
  if (!text) continue;
  const r = predict(text);
  n++;
  if (r.label === "中性") neu++;
  const pred = r.label === "正" ? "1" : r.label === "负" ? "0" : "?";
  if (pred === label.trim()) ok++;
  rows.push(pred + "\t" + r.p.toFixed(4) + "\t" + text);
}
console.log("n=" + n + " acc=" + (ok / n * 100).toFixed(2) + "% neutral=" + neu);
console.log(rows.slice(0, 5).join("\n"));
