package cn.lcx.goodnightuestc;

import android.content.Context;
import android.util.Log;
import java.lang.ref.WeakReference;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** A single process-owned task. Activity recreation must never cancel a scanned QR. */
final class AuthSession {
    interface Screen { void show(String kind, Object value); }
    private static AuthSession instance;
    final ExecutorService worker = Executors.newSingleThreadExecutor();
    final AtomicBoolean busy = new AtomicBoolean(false);
    final WeChatAuth wechat;
    final SchoolClient school;
    private WeakReference<Screen> screen = new WeakReference<>(null);
    private final Map<String,Object> snapshot = new LinkedHashMap<>();
    static synchronized AuthSession get(Context context, String userAgent) {
        if (instance == null) instance = new AuthSession(context.getApplicationContext(), userAgent);
        return instance;
    }
    private AuthSession(Context context, String userAgent) {
        school = new SchoolClient(userAgent);
        wechat = new WeChatAuth(context, this::event);
        snapshot.put("busy", "false");
        if (context.getSharedPreferences("auth-runtime",0).getBoolean("in_progress",false)) {
            snapshot.put("result","上次授权时应用进程被系统结束，原等待任务已中断。请重新显示二维码并确认；没有自动提交签到。");
            context.getSharedPreferences("auth-runtime",0).edit().putBoolean("in_progress",false).apply();
            Log.i("GoodnightAuth","previous_process_interrupted");
        }
    }
    synchronized void attach(Screen target) {
        screen = new WeakReference<>(target);
        // Busy first: its UI handler clears a finished QR. Replay the actual QR last.
        target.show("busy", String.valueOf(busy.get()));
        if (snapshot.containsKey("qr")) target.show("qr", snapshot.get("qr"));
        if (snapshot.containsKey("wxstatus")) target.show("wxstatus", snapshot.get("wxstatus"));
        for (Map.Entry<String,Object> item : snapshot.entrySet())
            if (!item.getKey().equals("busy") && !item.getKey().equals("qr") && !item.getKey().equals("wxstatus"))
                target.show(item.getKey(), item.getValue());
        Log.i("GoodnightAuth", "screen_attached busy=" + busy.get());
    }
    synchronized void detach(Screen target) {
        if (screen.get() == target) screen.clear();
        Log.i("GoodnightAuth", "screen_detached busy=" + busy.get());
    }
    private static boolean authProgress(String value) {
        switch (value) {
            case "正在核对学校登录身份…":
            case "已识别二维码，请在微信确认授权，然后返回本应用。":
            case "微信已确认，正在接收授权凭据…":
            case "正在刷新微信授权…":
            case "正在申请微信 code 并建立小程序会话…":
            case "账号一致，正在申请本次操作票据…":
                return true;
            default: return false;
        }
    }
    synchronized void event(String kind, Object value) {
        if (kind.equals("qrhide") || kind.equals("busy") && "false".equals(value)) snapshot.remove("qr");
        if (kind.equals("qr") || kind.equals("wxstatus") || kind.equals("busy")) snapshot.put(kind,value);
        boolean updateAuthStatus = false;
        if (kind.equals("qr")) {
            snapshot.put("wxstatus","请用绑定账号的本人微信摄像头扫码，并在微信确认授权。");
            updateAuthStatus = true;
        } else if (kind.equals("progress") && authProgress(String.valueOf(value))) {
            snapshot.put("wxstatus",value);
            updateAuthStatus = true;
        }
        if (kind.equals("progress") || kind.equals("result")) {
            snapshot.remove("progress"); snapshot.remove("result"); snapshot.put(kind,value);
        }
        Screen target = screen.get();
        if (target != null) {
            target.show(kind,value);
            if (updateAuthStatus) target.show("wxstatus",snapshot.get("wxstatus"));
        }
        // QR, identity, URLs, cookies and server payloads are deliberately never logged.
        Log.i("GoodnightAuth", "event=" + kind + " busy=" + busy.get());
    }
}
