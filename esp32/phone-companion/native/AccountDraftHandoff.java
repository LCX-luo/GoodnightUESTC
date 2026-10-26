package cn.lcx.goodnightuestc;

/** Process memory only. Activity results contain a random handle, never credentials. */
public final class AccountDraftHandoff {
    private static String key, value;
    private static long created;
    private AccountDraftHandoff() { }
    static synchronized String put(String bundle) {
        key=java.util.UUID.randomUUID().toString();value=bundle;
        created=android.os.SystemClock.elapsedRealtime();return key;
    }
    public static synchronized String take(String handle) {
        if(handle==null||!handle.equals(key)) return null;
        String result=android.os.SystemClock.elapsedRealtime()-created<120000?value:null;
        key=null;value=null;return result;
    }
}
