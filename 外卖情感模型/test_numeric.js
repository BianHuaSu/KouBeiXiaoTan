// 数值一致性：页面 JS 推理 vs Python 概率
const fs = require("fs");
const page = fs.readFileSync("外卖情感模型-手机版.html", "utf8");
const src = page.match(/<script>([\s\S]*)<\/script>/)[1].split("/* ====== 渲染 ====== */")[0];
const { predict } = new Function(src + "\nreturn { predict };")();
const rows = JSON.parse(fs.readFileSync("jscheck.json", "utf8"));
let max = 0, bad = 0;
for (const [t, p] of rows) {
  const q = predict(t).p;
  const d = Math.abs(q - p);
  if (d > max) max = d;
  if (d > 0.005) { bad++; console.log("DIFF", p, q.toFixed(6), t.slice(0, 30)); }
}
console.log("n=" + rows.length + " maxAbsDiff=" + max.toExponential(4) + " bad=" + bad);
