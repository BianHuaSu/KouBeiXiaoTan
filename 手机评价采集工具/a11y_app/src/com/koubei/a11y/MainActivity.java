package com.koubei.a11y;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 一个极简说明页：打开后能看到服务状态，并跳到系统无障碍设置。
 */
public class MainActivity extends Activity {
    private TextView status;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(24), dp(28), dp(24), dp(24));
        root.setBackgroundColor(Color.WHITE);

        TextView title = new TextView(this);
        title.setText("口碑小探 · 手机评价读取服务");
        title.setTextSize(22);
        title.setTextColor(Color.rgb(15, 23, 42));
        title.setGravity(Gravity.START);
        root.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        TextView desc = new TextView(this);
        desc.setText("这个服务只读取大众点评 / 美团 / 饿了么 / 京东 / 淘宝当前页面的文字、评分和坐标，不截图、不联网上传。\n\n"
                + "淘宝评价页是自绘 / WebView，没有无障碍文字节点；电脑端检测到淘宝会自动改用截图 OCR 现场识别，其他 App 仍走无障碍。\n\n"
                + "使用方法：\n"
                + "1. 点下面的按钮，进入系统无障碍设置；\n"
                + "2. 找到“口碑小探评价读取”，打开开关；\n"
                + "3. 回到任意外卖 App 的店铺评价页，保持页面在前台；\n"
                + "4. 在电脑端工具里选择“无障碍（连续读取）”开始采集。\n\n"
                + "如果系统提示“受限设置”，需要在应用信息里允许“受限设置”。");
        desc.setTextSize(15);
        desc.setTextColor(Color.rgb(51, 65, 85));
        desc.setLineSpacing(dp(3), 1.0f);
        LinearLayout.LayoutParams descLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        descLp.topMargin = dp(16);
        root.addView(desc, descLp);

        status = new TextView(this);
        status.setTextSize(16);
        status.setPadding(0, dp(18), 0, dp(12));
        root.addView(status);

        Button open = new Button(this);
        open.setText("打开系统无障碍设置");
        open.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS));
            }
        });
        root.addView(open, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        Button refresh = new Button(this);
        refresh.setText("刷新服务状态");
        refresh.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                refreshStatus();
            }
        });
        LinearLayout.LayoutParams refreshLp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        refreshLp.topMargin = dp(8);
        root.addView(refresh, refreshLp);

        setContentView(root);
        refreshStatus();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
    }

    private void refreshStatus() {
        String enabled = Settings.Secure.getString(
                getContentResolver(), Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
        String component = getPackageName() + "/" + ReviewAccessibilityService.class.getName();
        boolean on = !TextUtils.isEmpty(enabled) && enabled.contains(component);
        status.setText(on ? "状态：已开启，可以回电脑端开始采集" : "状态：未开启，请先在系统设置里打开");
        status.setTextColor(on ? Color.rgb(22, 163, 74) : Color.rgb(220, 38, 38));
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }
}
