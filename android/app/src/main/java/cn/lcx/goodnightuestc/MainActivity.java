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

public class MainActivity extends Activity implements AuthSession.Screen {
    private static final String LOCAL="https://appassets.androidplatform.net/assets/";
    private WebView web;
    private boolean pageReady;
    private SchoolClient school;
    private PhoneAccounts accounts;
    private WeChatAuth wechat;
    private ExecutorService worker;
    private AuthSession runtime;
    private AtomicBoolean busy;
    private android.content.SharedPreferences state;
    private final Handler main=new Handler(Looper.getMainLooper());
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        DiagnosticLog.init(this); DiagnosticLog.add("activity_create recreated="+(saved!=null));
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
        accounts=new PhoneAccounts(this,wechat);
        try{if(!busy.get()){accounts.importPrivate();int index=state.getInt("account_index",-1);if(index>=0){JSONObject row=accounts.select(index);school.setSession(row.getString("session"));}}}
        catch(Exception e){DiagnosticLog.add("account_load_failed type="+DiagnosticLog.reason(e));}

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
                    runtime.attach(MainActivity.this);
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
        DiagnosticLog.add("operation_error type="+DiagnosticLog.reason(ex));
        emit("result",message);
    }
    private interface Job { void run() throws Exception; }
    private void run(Job job) {run("operation",job);}
    private void run(String operation,Job job) {
        if(!busy.compareAndSet(false,true)) return;
        emit("busy","true");
        worker.execute(()->{DiagnosticLog.begin(operation);boolean completed=false;try { job.run();completed=true; } catch(Exception ex) { error(ex); } finally {DiagnosticLog.finish(completed);busy.set(false); emit("busy","false"); } });
    }
    final class Bridge {
        @JavascriptInterface public void copyLogs(){main.post(()->{android.content.ClipboardManager clipboard=(android.content.ClipboardManager)getSystemService(CLIPBOARD_SERVICE);clipboard.setPrimaryClip(ClipData.newPlainText("诊断日志",DiagnosticLog.copy()));Toast.makeText(MainActivity.this,"已复制脱敏日志",Toast.LENGTH_SHORT).show();});}
        @JavascriptInterface public void accounts(){if(busy.get())return;main.post(()->{try{JSONArray rows=accounts.all();String[] labels=new String[rows.length()];for(int i=0;i<rows.length();i++)labels[i]=rows.getJSONObject(i).getString("name");if(labels.length==0){Toast.makeText(MainActivity.this,"账号库为空，请先登录并完成一次签到",Toast.LENGTH_SHORT).show();return;}new AlertDialog.Builder(MainActivity.this).setTitle("选择本机账号").setItems(labels,(d,n)->{try{runtime.pendingAccount=null;emit("saveaccount","false");JSONObject row=accounts.select(n);school.setSession(row.getString("session"));emit("location",row.getJSONObject("point"));emit("wxstatus","已切换账号，尚未验证授权");emit("result","当前账号："+row.getString("name"));DiagnosticLog.add("account_selected index="+n);}catch(Exception e){error(e);}}).show();}catch(Exception e){error(e);}});}

        @JavascriptInterface public void saveAccount(){
            run(()->{
                JSONObject candidate=runtime.pendingAccount;
                if(candidate==null)throw new IOException("请先完成一次签到，再保存账号");
                int index=accounts.save(candidate);JSONObject row=accounts.select(index);school.setSession(row.getString("session"));
                runtime.pendingAccount=null;emit("saveaccount","false");emit("result","账号已加入或更新至本机加密账号库，下次可直接选择。授权过期时仍需重新登录。");
            });
        }
        @JavascriptInterface public void wechatAuthorize() {
            run("authorize",()->{ wechat.acquire(school.session(),true);emit("result","微信身份核对与取票成功，没有提交签到。可继续选择实际位置。 "); });
        }
        @JavascriptInterface public void wechatCancel() { wechat.cancel();emit("qrhide","");emit("wxstatus","已取消扫码授权，正在结束原等待任务；没有提交签到。"); }
        @JavascriptInterface public void wechatForget() {
            if(busy.get()) return;
            run(()->{ runtime.pendingAccount=null;emit("saveaccount","false");wechat.forget();emit("wxstatus","本机微信授权已清除，下次需要重新扫码。"); });
        }
        @JavascriptInterface public void login() {
            if(busy.get()) return;
            runtime.pendingAccount=null;emit("saveaccount","false");school.setSession(null);wechat.useAccount(-1);state.edit().remove("account_index").apply();
            main.post(()->startActivityForResult(new Intent(MainActivity.this,LoginActivity.class),1));
        }
        @JavascriptInterface public void check() {
            run("query",()->{ progress("正在读取学校当天记录…"); JSONObject r=school.today(); emit("result","会话有效 · "+r.optString("businessDate")+" · "+r.optString("recordStatusCode")+"\n本次仅查询，没有提交签到。"); });
        }
        @JavascriptInterface public void prepare(double lat,double lng,boolean confirm) {
            run(()->{
                double[] point=Coordinates.from(lat,lng,"gcj02");
                JSONObject location=new JSONObject().put("lat",lat).put("lng",lng).put("system","gcj02");
                if(!state.edit().putString("point",location.toString()).commit()) throw new IOException("位置无法保存");
                String day=SchoolClient.day();
                String address=confirm?"所选实际位置":precheck(point);
                if(!day.equals(SchoolClient.day())) throw new IOException("日期已变化，请重新检查");
                if(!confirm) { emit("result","只读预检查通过 · "+day+"\n"+address+"\nGCJ-02 "+point[0]+", "+point[1]+"\n没有提交签到。"); return; }
                long prepared=SystemClock.elapsedRealtime();
                main.post(()->showConfirmation(point,address,day,prepared));
            });
        }
        @JavascriptInterface public void logout() {
            if(busy.get()) return;
            main.post(()->new AlertDialog.Builder(MainActivity.this).setMessage("清除本应用保存的学校会话？提交防重复记录会保留。").setNegativeButton("取消",null)
                .setPositiveButton("清除",(d,w)->{ runtime.pendingAccount=null;emit("saveaccount","false");school.setSession(null);state.edit().remove("account_index").apply();try { wechat.forget(); } catch(Exception ignored) { } CookieManager.getInstance().removeAllCookies(ok->{ CookieManager.getInstance().flush(); WebStorage.getInstance().deleteAllData(); web.clearCache(true); emit("result","学校会话和本地微信授权已清除"); }); }).show());
        }
    }
    private String precheck(double[] point) throws Exception {
        progress("正在读取学校当天记录…");
        if(!"PENDING".equals(SchoolClient.validate(school.today()))) throw new IOException("当天已有签到、报告或免签记录，请查看学校官方入口");
        progress("正在检查允许的位置范围…"); SchoolClient.fence(point,(JSONArray)school.get(SchoolClient.FENCES));
        progress("正在检查学校签到时段…"); SchoolClient.window((JSONObject)school.get(SchoolClient.SCHEDULE));
        progress("正在查询学校确认地址…");
        Object result=school.get(SchoolClient.REVERSE+"?lat="+point[0]+"&lng="+point[1]);
        String address="";
        if(result instanceof String) address=(String)result;
        if(result instanceof JSONObject) {
            JSONObject r=(JSONObject)result;
            for(String key:Arrays.asList("address","reverseGeocode","formattedAddress"))
                if(r.opt(key) instanceof String && !r.optString(key).trim().isEmpty()) { address=r.optString(key); break; }
        }
        if(address.trim().isEmpty()||address.length()>2000) throw new IOException("学校未返回有效地址");
        return address;
    }
    private void showConfirmation(double[] point,String address,String day,long prepared) {
        if(isFinishing()||isDestroyed()) return;
        LinearLayout content=new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL); content.setPadding(40,16,40,16);
        TextView text=new TextView(this); text.setText(day+"\n"+address+String.format(Locale.ROOT,"\nGCJ-02 %.7f, %.7f",point[0],point[1])+"\n确认后将提交真实签到记录。请遵守学校规定。"); content.addView(text);
        CheckBox actual=new CheckBox(this); actual.setText("我本人实际在此位置，已核对信息"); content.addView(actual);
        AlertDialog dialog=new AlertDialog.Builder(this).setTitle("确认签到").setView(content).setNegativeButton("取消",null).setPositiveButton("确认提交",null).create();
        dialog.setOnShowListener(d->{
            android.widget.Button button=dialog.getButton(AlertDialog.BUTTON_POSITIVE); button.setEnabled(false);
            actual.setOnCheckedChangeListener((v,checked)->button.setEnabled(checked));
            button.setOnClickListener(v->{
                if(busy.get()) return;
                dialog.dismiss();
                run("submit",()->submit(point,address,day,prepared));
            });
        }); dialog.show();
    }
    private void submit(double[] point,String address,String day,long prepared) throws Exception {
        if(!day.equals(SchoolClient.day())||SystemClock.elapsedRealtime()-prepared>120000) throw new IOException("确认已过期，请重新预检查");
        runtime.pendingAccount=null;emit("saveaccount","false");
        progress("正在核对并获取本次微信操作授权…");
        String beforeSession=school.session();
        String operationTicket=wechat.forSubmission(beforeSession);
        if(!beforeSession.equals(school.session())) throw new IOException("学校账号发生变化，请重新预检查");
        if(!day.equals(SchoolClient.day())||SystemClock.elapsedRealtime()-prepared>120000) throw new IOException("确认已过期，请重新预检查");
        JSONObject payload=new JSONObject().put("latitude",point[0]).put("longitude",point[1]).put("reverseGeocode",address)
            .put("coordinateSystemCode","gcj02").put("accuracy",0).put("locationDurationMs",0).put("networkTypeCode","unknown")
            .put("locationEnabled",false).put("locationAuthorized","").put("locationAccuracy","").put("errorMessage","")
            .put("clientTime",SchoolClient.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")))
            .put("userAgent",WebSettings.getDefaultUserAgent(this));
        progress("正在提交一次签到请求…");
        String rejection=""; boolean accepted=false;
        try { school.setOperationTicket(operationTicket);school.post(payload);accepted=true; }
        catch(Exception ex) { DiagnosticLog.add("submit_exception type="+DiagnosticLog.reason(ex));rejection=ex instanceof IOException&&ex.getMessage()!=null?ex.getMessage():"请求结果未知，请查询学校记录"; }
        finally { wechat.consume(); }
        String recordStatus="查询失败"; boolean verified=false;
        try { JSONObject record=school.today();recordStatus=record.optString("recordStatusCode");verified=accepted&&SchoolClient.confirmed(record); } catch(Exception ignored) { }
        if(verified) {
            DiagnosticLog.success();
            try {
                JSONObject location=new JSONObject().put("lat",point[0]).put("lng",point[1]).put("system","gcj02");
                runtime.pendingAccount=wechat.libraryAccount(beforeSession,location);emit("saveaccount","true");
            }catch(Exception e){DiagnosticLog.outcome("library_offer_failed");DiagnosticLog.add("library_offer_failed type="+DiagnosticLog.reason(e));}
        } else {DiagnosticLog.add("submission_finished verified=false");if(Integer.valueOf(4006).equals(school.lastSubmissionCode())&&"PENDING".equals(recordStatus))DiagnosticLog.outcome("window_4006");}
        emit("result","本次发送一次签到请求。\n"+(rejection.isEmpty()?"学校接受请求（代码 0）":rejection)+"\n当天记录："+recordStatus+"。已有记录不代表本次票据有效；不自动重发。");
    }

    @Override protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(request==1 && result==RESULT_OK) new Bridge().check();
    }
    @Override protected void onStart() {
        super.onStart(); DiagnosticLog.add("activity_start"); android.util.Log.i("GoodnightAuth","activity_started");
        if(pageReady && runtime!=null) runtime.attach(this);
    }
    @Override protected void onStop() {
        DiagnosticLog.add("activity_stop busy="+(busy!=null&&busy.get()));
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
