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
    private static final String ALIAS="goodnight-wechat-v1";
    WeChatAuth(Context context,Listener listener) { this.context=context.getApplicationContext();this.listener=listener; }
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
    void cancel() { cancelled.set(true);consume(); }
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
        cancelled.set(false);
        initialize(context);
        try {
            String raw=Python.getInstance().getModule("native_auth").callAttr("acquire",session,load(),new Callback(this),allowQr).toString();
            JSONObject result=new JSONObject(raw);
            if(cancelled.get()) throw new IOException("授权已取消，没有提交签到");
            String value=result.getString("ticket");
            if(!value.matches("[A-Za-z0-9_-]{43}")) throw new IOException("学校返回的票据格式无效");
            synchronized(this) { ticket=value;ticketAt=android.os.SystemClock.elapsedRealtime();sessionBinding=binding(session);username=result.getString("username"); }
            listener.event("wxstatus","微信授权成功 · "+username+" · 票据已取得，没有提交签到。");
            return value;
        } catch(Exception ex) {
            listener.event("qrhide","");
            String reason=String.valueOf(ex.getMessage());
            if(reason.contains("identity_mismatch")) throw new IOException("微信绑定账号与学校登录账号不同，已停止取票");
            if(reason.contains("authorization_required")) throw new IOException("请先点击微信授权并完成扫码");
            if(reason.contains("school_not_bound")) throw new IOException("请先在官方智慧学工小程序绑定本人学校账号");
            if(reason.contains("qr_expired")) throw new IOException("二维码已过期或被取消，请重新发起授权");
            if(reason.contains("cancelled")) throw new IOException("授权已取消，没有提交签到");
            if(reason.contains("wechat_credential_rejected")) throw new IOException("微信授权已失效，请清除微信授权后重新扫码");
            if(reason.contains("school_http_401")||reason.contains("school_http_403")) throw new IOException("学校会话失效，请重新登录学校账号");
            java.util.regex.Matcher code=java.util.regex.Pattern.compile("school_code_(\\d+)").matcher(reason);
            if(code.find()) throw new IOException("学校授权失败（代码 "+code.group(1)+"），没有提交签到");
            if(reason.contains("oauth_credentials_missing")) throw new IOException("微信已确认，但应用宝回调未返回凭据，请重新授权；未提交签到");
            if(reason.contains("qr_network_failed")) throw new IOException("二维码状态查询网络失败，请检查连接后重试；未提交签到");
            throw new IOException("微信授权未完成，请检查网络或重新扫码；没有提交签到");
        }
    }
    String forSubmission(String session) throws Exception {
        return acquire(session,false);
    }
    public static class Callback {
        private final WeChatAuth owner;
        public Callback(WeChatAuth owner) { this.owner=owner; }
        public boolean cancelled() { return owner.cancelled.get(); }
        public void progress(String message) { owner.listener.event("progress",message); }
        public void qr(String encoded) throws IOException {
            byte[] bytes=Base64.decode(encoded,Base64.DEFAULT);
            android.graphics.BitmapFactory.Options options=new android.graphics.BitmapFactory.Options();options.inJustDecodeBounds=true;
            android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.length,options);
            if(options.outWidth<=0||options.outHeight<=0||options.outWidth>2048||options.outHeight>2048) throw new IOException("二维码图片无效");
            owner.listener.event("qr",encoded);
        }
        public void credentials(String value) throws Exception { owner.save(value);owner.listener.event("qrhide",""); }
    }
}
