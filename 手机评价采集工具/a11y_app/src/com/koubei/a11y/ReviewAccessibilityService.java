package com.koubei.a11y;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.accessibility.AccessibilityNodeInfo.RangeInfo;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedWriter;
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 只做一件事：把大众点评 / 美团 / 饿了么 / 京东当前窗口里有文字的节点，连同坐标和评分范围，持续吐到内部文件。
 *
 * 它不截图、不调用 uiautomator dump。事件触发后 120ms 抓一次；另外每 600ms 轮询一次，
 * 兼容美团这种不发 TYPE_VIEW_SCROLLED 的自绘列表；PC 端按 seq 组装并复用现有切条逻辑。
 */
public class ReviewAccessibilityService extends AccessibilityService {
    private static final String TAG = "KoubeiA11y";
    private static final Set<String> TARGET_PKGS = new HashSet<>(Arrays.asList(
            "com.dianping.v1",
            "com.sankuai.meituan",
            "com.sankuai.meituan.takeoutnew",
            "me.ele",
            "com.jingdong.app.mall",
            "com.taobao.taobao"
    ));
    private static final int MAX_NODES = 1200;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable poller = new Runnable() {
        @Override
        public void run() {
            // 有些 App（美团的自绘列表）不发 TYPE_VIEW_SCROLLED，
            // 固定 600ms 轮询当前窗口，保证滑动过程中也能读到新卡片。
            try {
                snapshot();
            } catch (Throwable t) {
                Log.e(TAG, "poll snapshot failed", t);
            } finally {
                handler.postDelayed(this, 600);
            }
        }
    };
    private boolean pending = false;
    private int seq = 0;
    private int lastHash = 0;
    private long lastAt = 0;
    private int width = 0;
    private int height = 0;
    private BufferedWriter writer = null;

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        width = getResources().getDisplayMetrics().widthPixels;
        height = getResources().getDisplayMetrics().heightPixels;
        try {
            File out = new File(getFilesDir(), "a11y_stream.jsonl");
            writer = new BufferedWriter(new OutputStreamWriter(
                    new FileOutputStream(out, false), StandardCharsets.UTF_8));
            JSONObject ready = new JSONObject();
            ready.put("type", "ready");
            ready.put("w", width);
            ready.put("h", height);
            appendLine(ready.toString());
        } catch (Exception e) {
            Log.e(TAG, "open stream failed", e);
        }
        Log.i(TAG, "READY|" + width + "|" + height);
        handler.removeCallbacks(poller);
        handler.postDelayed(poller, 250);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        if (event == null) {
            return;
        }
        CharSequence pkg = event.getPackageName();
        if (pkg != null && !TARGET_PKGS.contains(pkg.toString())) {
            return;
        }
        schedule(120);
    }

    @Override
    public void onInterrupt() {
        Log.i(TAG, "INTERRUPT");
    }

    @Override
    public void onDestroy() {
        Log.i(TAG, "DESTROY");
        handler.removeCallbacks(poller);
        try {
            if (writer != null) {
                writer.close();
                writer = null;
            }
        } catch (Exception ignored) {
        }
        super.onDestroy();
    }

    private void schedule(long delayMs) {
        if (pending) {
            return;
        }
        pending = true;
        handler.postDelayed(new Runnable() {
            @Override
            public void run() {
                pending = false;
                try {
                    snapshot();
                } catch (Throwable t) {
                    Log.e(TAG, "event snapshot failed", t);
                }
            }
        }, delayMs);
    }

    private void snapshot() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            return;
        }
        CharSequence pkg = root.getPackageName();
        if (pkg == null || !TARGET_PKGS.contains(pkg.toString())) {
            return;
        }
        String pkgName = pkg.toString();

        if (width <= 0 || height <= 0) {
            width = getResources().getDisplayMetrics().widthPixels;
            height = getResources().getDisplayMetrics().heightPixels;
        }

        List<NodeRec> recs = new ArrayList<>();
        ArrayDeque<AccessibilityNodeInfo> queue = new ArrayDeque<>();
        queue.add(root);
        int visited = 0;
        while (!queue.isEmpty() && visited < MAX_NODES) {
            AccessibilityNodeInfo node = queue.removeFirst();
            visited++;
            Rect r = new Rect();
            node.getBoundsInScreen(r);
            if (r.width() > 0 && r.height() > 0) {
                String text = clean(node.getText());
                String desc = clean(node.getContentDescription());
                String cls = node.getClassName() == null ? "" : node.getClassName().toString();
                RangeInfo range = node.getRangeInfo();
                String rangeText = "";
                if (range != null) {
                    rangeText = range.getMin() + "|" + range.getMax() + "|" + range.getCurrent();
                }
                boolean ratingLike = range != null
                        || cls.contains("RatingBar")
                        || text.contains("星")
                        || desc.contains("星")
                        || text.contains("评分")
                        || desc.contains("评分")
                        || text.toLowerCase().contains("rating")
                        || desc.toLowerCase().contains("rating");
                if (text.length() > 0 || ratingLike) {
                    recs.add(new NodeRec(
                            text,
                            desc,
                            cls,
                            "[" + r.left + "," + r.top + "][" + r.right + "," + r.bottom + "]",
                            node.isScrollable(),
                            node.isClickable(),
                            rangeText
                    ));
                }
            }
            int childCount = node.getChildCount();
            for (int i = 0; i < childCount; i++) {
                AccessibilityNodeInfo child = node.getChild(i);
                if (child != null) {
                    queue.add(child);
                }
            }
        }

        if (recs.isEmpty()) {
            return;
        }

        int hash = 1;
        for (NodeRec rec : recs) {
            hash = 31 * hash + rec.text.hashCode();
            hash = 31 * hash + rec.bounds.hashCode();
        }
        if (hash == lastHash) {
            return;
        }

        seq++;
        lastHash = hash;
        lastAt = System.currentTimeMillis();
        try {
            JSONArray arr = new JSONArray();
            for (NodeRec rec : recs) {
                JSONObject node = new JSONObject();
                node.put("t", rec.text);
                node.put("d", rec.desc);
                node.put("c", rec.cls);
                node.put("b", rec.bounds);
                node.put("s", rec.scrollable ? 1 : 0);
                node.put("k", rec.clickable ? 1 : 0);
                node.put("r", rec.range);
                arr.put(node);
            }
            JSONObject snap = new JSONObject();
            snap.put("type", "snap");
            snap.put("seq", seq);
            snap.put("pkg", pkgName);
            snap.put("w", width);
            snap.put("h", height);
            snap.put("nodes", arr);
            appendLine(snap.toString());
            Log.i(TAG, "SNAP|" + seq + "|" + recs.size());
        } catch (Exception e) {
            Log.e(TAG, "write snapshot failed", e);
        }
    }

    private synchronized void appendLine(String line) {
        if (writer == null) {
            return;
        }
        try {
            writer.write(line);
            writer.newLine();
            writer.flush();
        } catch (Exception e) {
            Log.e(TAG, "append failed", e);
        }
    }

    private static String clean(CharSequence value) {
        if (value == null) {
            return "";
        }
        String s = value.toString()
                .replace('\r', ' ')
                .replace('\n', ' ')
                .replace('\t', ' ')
                .replace('\u200b', ' ')
                .replace('\u00a0', ' ');
        s = s.replaceAll("\\s+", " ").trim();
        if (s.length() > 1000) {
            s = s.substring(0, 1000);
        }
        return s;
    }

    private static final class NodeRec {
        final String text;
        final String desc;
        final String cls;
        final String bounds;
        final boolean scrollable;
        final boolean clickable;
        final String range;

        NodeRec(String text, String desc, String cls, String bounds, boolean scrollable, boolean clickable, String range) {
            this.text = text;
            this.desc = desc;
            this.cls = cls;
            this.bounds = bounds;
            this.scrollable = scrollable;
            this.clickable = clickable;
            this.range = range;
        }
    }
}
