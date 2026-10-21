package cn.lcx.goodnightuestc;

import android.app.*;
import android.os.Bundle;
import android.net.Uri;
import android.view.*;
import android.webkit.*;
import android.widget.*;

/** Remote school pages never receive a JavaScript interface to native app code. */
public class LoginActivity extends Activity {
    private WebView web;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout=new LinearLayout(this); layout.setOrientation(LinearLayout.VERTICAL);
        layout.setOnApplyWindowInsetsListener((v,insets)->{ v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom()); return insets; });
        TextView note=new TextView(this); note.setText("在学校官方页面登录，并按提示完成验证。完成后点击下方按钮。学校登录页按设备网络设置连接。"); note.setPadding(20,12,20,12); layout.addView(note);
        web=new WebView(this); web.getSettings().setJavaScriptEnabled(true); web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false); web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.getSettings().setSaveFormData(false);
        CookieManager.getInstance().setAcceptCookie(true);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request) {
                Uri uri=request.getUrl(); String host=uri.getHost();
                boolean allowed="https".equals(uri.getScheme()) && host!=null && (host.equals("uestc.edu.cn")||host.endsWith(".uestc.edu.cn"));
                if(!allowed) Toast.makeText(LoginActivity.this,"仅允许打开学校 HTTPS 登录页面",Toast.LENGTH_SHORT).show();
                return !allowed;
            }
            @Override public void onReceivedSslError(WebView v,android.webkit.SslErrorHandler handler,android.net.http.SslError error) {
                handler.cancel(); Toast.makeText(LoginActivity.this,"学校证书验证失败，连接已停止",Toast.LENGTH_LONG).show();
            }
        });
        layout.addView(web,new LinearLayout.LayoutParams(-1,0,1));
        Button done=new Button(this); done.setText("完成登录，返回检查");
        done.setOnClickListener(v->{ CookieManager.getInstance().flush(); setResult(RESULT_OK); finish(); });
        LinearLayout buttons=new LinearLayout(this);
        Button back=new Button(this); back.setText("网页上一页"); back.setOnClickListener(v->{ if(web.canGoBack())web.goBack(); });
        buttons.addView(back,new LinearLayout.LayoutParams(0,-2,1)); buttons.addView(done,new LinearLayout.LayoutParams(0,-2,2));
        layout.addView(buttons); setContentView(layout); web.loadUrl(SchoolClient.ENTRY);
    }
    @Override public void onDestroy() { if(web!=null) { web.stopLoading(); web.destroy(); } super.onDestroy(); }
}
