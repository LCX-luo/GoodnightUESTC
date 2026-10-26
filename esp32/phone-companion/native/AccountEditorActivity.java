package cn.lcx.goodnightuestc;

import android.app.*;
import android.content.*;
import android.os.*;
import android.webkit.*;
import android.widget.*;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

public class AccountEditorActivity extends Activity implements AuthSession.Screen {
    private static final String LOCAL="https://appassets.androidplatform.net/assets/";
    private WebView web;
    private boolean pageReady;
    private SchoolClient school;
    private WeChatAuth wechat;
    private ExecutorService worker;
    private AuthSession runtime;
    private AtomicBoolean busy;
    private android.content.SharedPreferences state;
    private final Handler main=new Handler(Looper.getMainLooper());
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        state=getSharedPreferences("local",MODE_PRIVATE);
        web=new WebView(this);
        FrameLayout root=new FrameLayout(this);
        root.addView(web,new FrameLayout.LayoutParams(-1,-1));
        root.setOnApplyWindowInsetsListener((v,insets)->{ v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom()); return insets; });
        WebSettings settings=web.getSettings(); settings.setJavaScriptEnabled(true); settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        runtime=AuthSession.get(this,settings.getUserAgentString());
        school=runtime.school; wechat=runtime.wechat; worker=runtime.worker; busy=runtime.busy;
        android.util.Log.i("GoodnightAuth","activity_created recreated="+(saved!=null));
        web.addJavascriptInterface(new Bridge(),"Android");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest r) {
                if(r.isForMainFrame() && "https".equals(r.getUrl().getScheme()) && "www.amap.com".equals(r.getUrl().getHost()))
                    try { startActivity(new Intent(Intent.ACTION_VIEW,r.getUrl())); } catch(ActivityNotFoundException ignored) { }
                return true;
            }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view,WebResourceRequest r) {
                String url=r.getUrl().toString();
                if(url.startsWith(LOCAL)) {
                    String path=url.substring(LOCAL.length());
                    if(path.contains("..")||path.contains("%")||path.contains("?")) return blocked();
                    try {
                        String type=path.endsWith(".html")?"text/html":path.endsWith(".js")?"application/javascript":path.endsWith(".css")?"text/css":"text/plain";
                        Map<String,String> headers=new HashMap<>();
                        headers.put("Content-Security-Policy","default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src https://wprd01.is.autonavi.com https://wprd02.is.autonavi.com https://wprd03.is.autonavi.com https://wprd04.is.autonavi.com data:; connect-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'");
                        headers.put("X-Content-Type-Options","nosniff");
                        return new WebResourceResponse(type,"UTF-8",200,"OK",headers,getAssets().open(path));
                    } catch(IOException ex) { return blocked(); }
                }
                String host=r.getUrl().getHost();
                if(host!=null && host.matches("wprd0[1-4]\\.is\\.autonavi\\.com") && "/appmaptile".equals(r.getUrl().getPath()) && "https".equals(r.getUrl().getScheme())&&!r.isForMainFrame()) return null;
                return blocked();
            }
            @Override public void onPageFinished(WebView view,String url) {
                if(url.equals(LOCAL+"index.html")) {
                    pageReady=true;
                    runtime.attach(AccountEditorActivity.this);
                    if(getIntent().hasExtra("latitude")&&getIntent().hasExtra("longitude")) {
                        try { emit("location",new JSONObject().put("lat",getIntent().getDoubleExtra("latitude",0))
                            .put("lng",getIntent().getDoubleExtra("longitude",0))); } catch(JSONException ignored) { }
                        return;
                    }
                    try {
                        JSONObject location=new JSONObject(state.getString("point","{\"lat\":30.6752,\"lng\":104.0975}"));
                        // v0.1.0 stored WGS84. Migrate that source once to the domestic GCJ02 map.
                        double[] p=Coordinates.from(location.getDouble("lat"),location.getDouble("lng"),location.optString("system","wgs84"));
                        location.put("lat",p[0]).put("lng",p[1]).put("system","gcj02");
                        state.edit().putString("point",location.toString()).apply(); emit("location",location);
                    }
                    catch(JSONException ignored) { }
                }
            }
        });
        setContentView(root); web.loadUrl(LOCAL+"index.html");
    }
    private WebResourceResponse blocked() {
        return new WebResourceResponse("text/plain","UTF-8",403,"Forbidden",Collections.emptyMap(),new ByteArrayInputStream(new byte[0]));
    }
    private void emit(String kind,Object value) {
        if(runtime!=null && !kind.equals("location")) { runtime.event(kind,value); return; }
        show(kind,value);
    }
    @Override public void show(String kind,Object value) {
        main.post(()->{
            if(isFinishing()||isDestroyed()) return;
            web.evaluateJavascript("window.onNative("+JSONObject.quote(kind)+","+(value instanceof JSONObject?value.toString():JSONObject.quote(String.valueOf(value)))+")",null);
        });
    }
    private void progress(String message) { emit("progress",message); }
    private void error(Exception ex) {
        String message=ex instanceof IOException && ex.getMessage()!=null && ex.getMessage().matches(".*[\\p{IsHan}].*")?ex.getMessage():"操作未完成，请检查网络并重新登录；可通过官方入口核对";
        emit("result",message);
    }
    private interface Job { void run() throws Exception; }
    private void run(Job job) {
        if(!busy.compareAndSet(false,true)) return;
        emit("busy","true");
        worker.execute(()->{ try { job.run(); } catch(Exception ex) { error(ex); } finally { busy.set(false); emit("busy","false"); } });
    }
    final class Bridge {
        @JavascriptInterface public void wechatAuthorize() {
            run(()->{ wechat.acquire(school.session(),true);emit("result","微信身份核对与取票成功，没有提交签到。可继续选择实际位置。 "); });
        }
        @JavascriptInterface public void wechatCancel() { wechat.cancel();emit("qrhide","");emit("wxstatus","已取消扫码授权，正在结束原等待任务；没有提交签到。"); }
        @JavascriptInterface public void wechatForget() {
            if(busy.get()) return;
            run(()->{ wechat.forget();emit("wxstatus","本机微信授权已清除，下次需要重新扫码。"); });
        }
        @JavascriptInterface public void login() {
            if(busy.get()) return;
            main.post(()->startActivityForResult(new Intent(AccountEditorActivity.this,LoginActivity.class),1));
        }
        @JavascriptInterface public void check() {
            run(()->{ progress("正在读取学校当天记录…"); JSONObject r=school.today(); emit("result","会话有效 · "+r.optString("businessDate")+" · "+r.optString("recordStatusCode")+"\n本次仅查询，没有提交签到。"); });
        }
        @JavascriptInterface public void prepare(double lat,double lng,boolean confirm) {
            if(!confirm) { check(); return; }
            run(()->exportAccount(lat,lng));
        }
        @JavascriptInterface public void logout() {
            if(busy.get()) return;
            main.post(()->new AlertDialog.Builder(AccountEditorActivity.this).setMessage("清除本应用保存的学校会话？提交防重复记录会保留。").setNegativeButton("取消",null)
                .setPositiveButton("清除",(d,w)->{ try { wechat.forget(); } catch(Exception ignored) { } CookieManager.getInstance().removeAllCookies(ok->{ CookieManager.getInstance().flush(); WebStorage.getInstance().deleteAllData(); web.clearCache(true); emit("result","学校会话和本地微信授权已清除"); }); }).show());
        }
    }
    private void exportAccount(double lat,double lng) throws Exception {
        double[] point=Coordinates.from(lat,lng,"gcj02");
        progress("正在核对学校账号与微信授权，随后只更新设备账号，不在手机直接签到…");
        String session=school.session();
        wechat.acquire(session,false);
        if(!session.equals(school.session())) throw new IOException("学校会话发生变化，请重新验证");
        JSONObject bundle=wechat.deviceAccount(session);
        String expected=getIntent().getStringExtra("expected_sid");
        if(expected!=null&&!expected.isEmpty()&&!expected.equals(bundle.getString("student_id")))
            throw new IOException("登录账号与待更新设备账号不同，已停止；不会替换其他账号");
        bundle.put("location",new JSONObject().put("latitude",point[0]).put("longitude",point[1]).put("coordinate_system","gcj02"));
        bundle.put("enabled",false).put("scheduleMinute",1270);
        String raw=bundle.toString();
        if(raw.getBytes(StandardCharsets.UTF_8).length>6000) throw new IOException("账号材料超过设备允许大小，未发送");
        main.post(()->{
            if(isFinishing()||isDestroyed()) return;
            new AlertDialog.Builder(this).setTitle("更新设备账号前确认")
                .setMessage("本次只更新设备账号，不在手机直接签到。学校账号："+bundle.optString("student_id")+
                    String.format(Locale.ROOT,"\nGCJ-02 %.7f, %.7f",point[0],point[1])+"\n返回后将经加密通道写入设备，收到设备确认后才保存成功。")
                .setNegativeButton("取消",(d,w)->emit("result","已取消传送；没有更新设备，也没有签到。"))
                .setPositiveButton("确认传给设备",(d,w)->{
                    Intent result=new Intent();result.putExtra("verified_account_handle",AccountDraftHandoff.put(raw));
                    setResult(RESULT_OK,result);finish();
                }).show();
        });
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==1 && result==RESULT_OK) new Bridge().check();
    }
    @Override protected void onStart() {
        super.onStart(); android.util.Log.i("GoodnightAuth","activity_started");
        if(pageReady && runtime!=null) runtime.attach(this);
    }
    @Override protected void onStop() {
        android.util.Log.i("GoodnightAuth","activity_stopped busy="+(busy!=null&&busy.get())); super.onStop();
    }
    @Override public void onDestroy() {
        // The process owns the task. Switching to WeChat or recreating this screen
        // must not invalidate its QR or start another authorization. Explicit cancel is separate.
        pageReady=false;
        if(runtime!=null) runtime.detach(this);
        android.util.Log.i("GoodnightAuth","activity_destroyed finishing="+isFinishing()+" changing="+isChangingConfigurations());
        if(web!=null) { web.removeJavascriptInterface("Android"); web.destroy(); }
        super.onDestroy();
    }
}
