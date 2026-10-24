package cn.lcx.goodnightuestc;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import org.json.JSONObject;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;

/** Phone-local Python protocol bridge. Never exposes tokens to the WebView. */
public class WeChatAuth {
    public interface Listener { void event(String kind,String value); }
    private final Context context;
    private final Listener listener;
    private final AtomicBoolean cancelled=new AtomicBoolean(false);
    private String ticket,sessionBinding,username;
    private long ticketAt;
    private volatile String diagnosticPhase="idle";
    private static final String ALIAS="goodnight-wechat-v1";
    WeChatAuth(Context context,Listener listener) { this.context=context.getApplicationContext();this.listener=listener; }
    /** Bounded private diagnostic trail: only fixed protocol stages and reasons. */
    private synchronized void diagnostic(String event) {
        if(!event.matches("(?:phase=[a-z_]+|qr_retry reason=[a-z_0-9]+|authorization_started allowQr=(?:true|false) cached=(?:true|false)|authorization_failed phase=[a-z_]+ reason=[a-z_0-9]+|authorization_ticket_acquired|oauth_credentials_received|authorization_cancelled_explicitly)")) return;
        android.util.Log.i("GoodnightAuth",event);
        try {
            File target=new File(context.getFilesDir(),"auth-diagnostics.log");
            java.util.List<String> lines=target.exists()&&target.length()<=16384
                ?new java.util.ArrayList<>(Files.readAllLines(target.toPath(),java.nio.charset.StandardCharsets.UTF_8))
                :new java.util.ArrayList<>();
            lines.add(System.currentTimeMillis()+" "+event);
            while(lines.size()>64) lines.remove(0);
            File pending=new File(context.getFilesDir(),"auth-diagnostics.new");
            Files.write(pending.toPath(),lines,java.nio.charset.StandardCharsets.UTF_8);
            Files.move(pending.toPath(),target.toPath(),StandardCopyOption.REPLACE_EXISTING);
        } catch(Exception ignored) { /* Diagnostics must never interrupt authorization. */ }
    }
    static String diagnosticReason(String reason) {
        for(String name:new String[]{"identity_mismatch","authorization_required","school_not_bound","qr_expired","cancelled","wechat_credential_rejected","oauth_credentials_missing","qr_network_failed","qr_unavailable","qr_status_unrecognized","qr_tls_certificate","qr_tls_failed","qr_network_timeout","qr_remote_disconnected","qr_incomplete_read","qr_bad_status_line","qr_connection_failed","qr_dns_failed","qr_response_encoding"})
            if(reason.contains(name)) return name;
        java.util.regex.Matcher http=java.util.regex.Pattern.compile("\\bqr_http_([1-5]\\d{2})\\b").matcher(reason);
        if(http.find()) return "qr_http_"+http.group(1);
        java.util.regex.Matcher python=java.util.regex.Pattern.compile("\\bpython_failure_([a-z][a-z0-9_]{0,80})\\b").matcher(reason);
        if(python.find()) return "python_failure_"+python.group(1);
        // PyException includes Python's class name. Extract only a known fixed
        // class identifier; never record its message, URL, or traceback.
        for(String[] type:new String[][]{{"SSLCertVerificationError","python_tls_certificate"},{"SSLError","python_tls_failed"},{"RemoteDisconnected","python_remote_disconnected"},{"IncompleteRead","python_incomplete_read"},{"BadStatusLine","python_bad_status_line"},{"ConnectionResetError","python_connection_reset"},{"ConnectionAbortedError","python_connection_aborted"},{"UnicodeDecodeError","python_response_encoding"},{"TimeoutError","python_timeout"}})
            if(java.util.regex.Pattern.compile("\\b"+type[0]+"\\b").matcher(reason).find()) return type[1];
        return "other";
    }
    private File file() { return new File(context.getFilesDir(),"wechat.enc"); }
    private synchronized javax.crypto.SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(ALIAS)) {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (javax.crypto.SecretKey)store.getKey(ALIAS,null);
    }
    private synchronized String load() throws Exception {
        if(!file().exists()) return "";
        byte[] bytes=Files.readAllBytes(file().toPath());
        if(bytes.length<29) throw new IOException("微信授权存储损坏，请清除微信授权后重试");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,bytes,0,12));
        c.updateAAD(ALIAS.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return new String(c.doFinal(bytes,12,bytes.length-12),java.nio.charset.StandardCharsets.UTF_8);
    }
    private synchronized void save(String value) throws Exception {
        if(cancelled.get()) throw new IOException("授权已取消");
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,key());
        c.updateAAD(ALIAS.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        File temp=new File(context.getFilesDir(),"wechat.new");
        try(FileOutputStream out=new FileOutputStream(temp)) {
            out.write(c.getIV());out.write(c.doFinal(value.getBytes(java.nio.charset.StandardCharsets.UTF_8)));out.getFD().sync();
        }
        Files.move(temp.toPath(),file().toPath(),StandardCopyOption.REPLACE_EXISTING);
    }
    static String binding(String session) throws Exception {
        return Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(session.getBytes(java.nio.charset.StandardCharsets.UTF_8)),Base64.NO_WRAP);
    }
    synchronized void consume() { ticket=null;ticketAt=0; }
    void cancel() { diagnostic("authorization_cancelled_explicitly"); cancelled.set(true);consume(); }
    synchronized void forget() throws Exception {
        cancel();Files.deleteIfExists(file().toPath());
    }
    private static void initialize(Context context) {
        synchronized(WeChatAuth.class) { if(!Python.isStarted()) Python.start(new AndroidPlatform(context)); }
    }
    public static boolean selfTest(Context context) {
        initialize(context);return Python.getInstance().getModule("native_auth").callAttr("self_test").toBoolean();
    }
    String acquire(String session,boolean allowQr) throws Exception {
        cancelled.set(false); consume(); diagnosticPhase="starting";
        diagnostic("authorization_started allowQr="+allowQr+" cached="+file().exists());
        initialize(context);
        context.getSharedPreferences("auth-runtime",0).edit().putBoolean("in_progress",true).commit();
        try {
            String raw=Python.getInstance().getModule("native_auth").callAttr("acquire",session,load(),new Callback(this),allowQr).toString();
            JSONObject result=new JSONObject(raw);
            if(cancelled.get()) throw new IOException("授权已取消，没有提交签到");
            String value=result.getString("ticket");
            if(!value.matches("[A-Za-z0-9_-]{43}")) throw new IOException("学校返回的票据格式无效");
            synchronized(this) { ticket=value;ticketAt=android.os.SystemClock.elapsedRealtime();sessionBinding=binding(session);username=result.getString("username"); }
            diagnostic("authorization_ticket_acquired");
            listener.event("wxstatus","微信授权成功 · "+username+" · 票据已取得，没有提交签到。");
            return value;
        } catch(Exception ex) {
            listener.event("qrhide","");
            String reason=String.valueOf(ex.getMessage());
            // Only known fixed identifiers are logged, never Python traceback/request data.
            String safeReason=diagnosticReason(reason);
            if(safeReason.equals("other")) {
                String kind=ex.getClass().getSimpleName().toLowerCase(java.util.Locale.ROOT);
                safeReason="java_failure_"+(kind.matches("[a-z][a-z0-9_]{0,63}")?kind:"unknown");
            }
            diagnostic("authorization_failed phase="+diagnosticPhase+" reason="+safeReason);
            if(reason.contains("identity_mismatch")) throw failure("微信绑定账号与学校登录账号不同，已停止取票");
            if(reason.contains("authorization_required")) throw failure("请先点击微信授权并完成扫码");
            if(reason.contains("school_not_bound")) throw failure("请先在官方智慧学工小程序绑定本人学校账号");
            if(reason.contains("qr_expired")) throw failure("二维码已过期或被取消，请重新发起授权");
            if(reason.contains("cancelled")) throw failure("授权已取消，没有提交签到");
            if(reason.contains("wechat_credential_rejected")) throw failure("微信授权已失效，请清除微信授权后重新扫码");
            if(reason.contains("school_http_401")||reason.contains("school_http_403")) throw failure("学校会话失效，请重新登录学校账号");
            java.util.regex.Matcher code=java.util.regex.Pattern.compile("school_code_(\\d+)").matcher(reason);
            if(code.find()) throw failure("学校授权失败（代码 "+code.group(1)+"），没有提交签到");
            if(reason.contains("oauth_credentials_missing")) throw failure("微信已确认，但应用宝回调未返回凭据，请重新授权；未提交签到");
            if(reason.contains("qr_network_failed")) throw failure("二维码状态查询网络失败，请检查连接后重试；未提交签到");
            java.util.regex.Matcher qrHttp=java.util.regex.Pattern.compile("\\bqr_http_([1-5]\\d{2})\\b").matcher(reason);
            if(qrHttp.find()) throw failure("微信二维码状态接口返回 HTTP "+qrHttp.group(1)+"，已停止等待；没有提交签到");
            if(safeReason.contains("tls_certificate")) throw failure("微信连接的 TLS 证书验证失败，已停止授权；没有忽略证书验证或提交签到");
            if(safeReason.startsWith("qr_")||safeReason.startsWith("python_")) throw failure("微信二维码状态连接未完成（"+safeReason+"），已停止等待；没有提交签到");
            throw failure("微信授权未完成，请检查网络或重新扫码；没有提交签到");
        } finally {
            context.getSharedPreferences("auth-runtime",0).edit().putBoolean("in_progress",false).commit();
        }
    }
    private IOException failure(String message) {
        listener.event("wxstatus",message);
        return new IOException(message);
    }
    String forSubmission(String session) throws Exception {
        return acquire(session,false);
    }
    public static class Callback {
        private final WeChatAuth owner;
        public Callback(WeChatAuth owner) { this.owner=owner; }
        public boolean cancelled() { return owner.cancelled.get(); }
        public void progress(String message) {
            switch(message) {
                case "正在核对学校登录身份…": owner.diagnosticPhase="school_identity"; break;
                case "已识别二维码，请在微信确认授权，然后返回本应用。": owner.diagnosticPhase="qr_scanned"; break;
                case "微信已确认，正在接收授权凭据…": owner.diagnosticPhase="oauth_callback"; break;
                case "正在刷新微信授权…": owner.diagnosticPhase="credential_refresh"; break;
                case "正在申请微信 code 并建立小程序会话…": owner.diagnosticPhase="mini_session"; break;
                case "账号一致，正在申请本次操作票据…": owner.diagnosticPhase="school_ticket"; break;
                case "二维码状态连接中断，正在重连；请保留原二维码，不要重复授权。": owner.diagnosticPhase="qr_reconnecting"; break;
                default: break;
            }
            owner.diagnostic("phase="+owner.diagnosticPhase);
            owner.listener.event("progress",message);
        }
        public void diagnostic(String reason) {
            if(reason.matches("qr_poll_(?:pending|scanned|authorized)")) owner.diagnostic("phase="+reason);
            else if(reason.matches("qr_(?:network_timeout|remote_disconnected|incomplete_read|bad_status_line|connection_failed|dns_failed|http_5\\d{2})")) owner.diagnostic("qr_retry reason="+reason);
        }
        public void qr(String encoded) throws IOException {
            byte[] bytes=Base64.decode(encoded,Base64.DEFAULT);
            android.graphics.BitmapFactory.Options options=new android.graphics.BitmapFactory.Options();options.inJustDecodeBounds=true;
            android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
            if(options.outWidth<=0||options.outHeight<=0||options.outWidth>2048||options.outHeight>2048) throw new IOException("二维码图片无效");
            owner.diagnosticPhase="qr_waiting"; owner.diagnostic("phase=qr_waiting");
            owner.listener.event("qr",encoded);
        }
        public void credentials(String value) throws Exception { owner.diagnosticPhase="credentials_received"; owner.diagnostic("oauth_credentials_received"); owner.save(value);owner.listener.event("qrhide",""); }
    }
}
