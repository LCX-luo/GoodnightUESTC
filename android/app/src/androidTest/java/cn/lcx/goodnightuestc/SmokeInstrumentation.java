package cn.lcx.goodnightuestc;

import android.app.*;
import android.content.*;
import android.os.*;
import org.json.*;
import java.lang.reflect.*;
import java.io.IOException;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Device tests use fake school responses only. No actual school request can be sent. */
public class SmokeInstrumentation extends Instrumentation {
    private int assertions;
    private void check(boolean value,String name) {
        if(!value) throw new AssertionError(name);
        assertions++;
    }
    private interface Check { void run() throws Exception; }
    private void rejects(Check job,String name) throws Exception {
        try { job.run(); } catch(IOException|IllegalArgumentException expected) { assertions++; return; }
        throw new AssertionError(name);
    }
    @Override public void onCreate(Bundle args) { super.onCreate(args); start(); }
    static class FakeSchool extends SchoolClient {
        int posts=0,reads=0;
        boolean uncertain=false,failReadback=false;
        JSONObject payload;
        FakeSchool() { super("test-no-network"); }
        @Override String session() { return "synthetic-school-session"; }
        @Override synchronized Object get(String path) throws Exception {
            reads++;
            if(path.equals(TODAY)) {
                if(posts>0 && failReadback) throw new IOException("模拟回读失败");
                return new JSONObject().put("businessDate",day()).put("recordStatusCode",posts>0&&!uncertain?"CHECKED_IN":"PENDING")
                    .put("abnormalFlag",false).put("checkinTime",posts>0&&!uncertain?"22:00:00":"");
            }
            if(path.equals(SCHEDULE)) return new JSONObject().put("effective",true).put("studentCheckinStartOffsetMinute",0).put("studentCheckinEndOffsetMinute",1440);
            if(path.equals(FENCES)) { double[] c=Coordinates.gcj(30.6752,104.0975); return new JSONArray().put(new JSONObject().put("latitude",c[0]).put("longitude",c[1]).put("radiusMeter",2000)); }
            if(path.startsWith(REVERSE+"?")) return "模拟沙河地址（测试数据）";
            throw new AssertionError("unexpected endpoint");
        }
        @Override synchronized void post(JSONObject p) throws Exception { posts++; payload=p; if(uncertain) throw new IOException("模拟请求超时"); }
    }
    private void set(Object target,String field,Object value) throws Exception {
        Field f=MainActivity.class.getDeclaredField(field); f.setAccessible(true); f.set(target,value);
    }
    private String js(MainActivity activity,String script) throws Exception {
        Field field=MainActivity.class.getDeclaredField("web"); field.setAccessible(true);
        android.webkit.WebView web=(android.webkit.WebView)field.get(activity);
        AtomicReference<String> result=new AtomicReference<>(); CountDownLatch ready=new CountDownLatch(1);
        runOnMainSync(()->web.evaluateJavascript(script,value->{result.set(value); ready.countDown();}));
        if(!ready.await(5,TimeUnit.SECONDS)) throw new AssertionError("WebView callback timeout");
        return result.get();
    }
    @Override public void onStart() {
        Bundle result=new Bundle(); MainActivity activity=null; FakeSchool fake=null;
        try {
            double[] c=Coordinates.gcj(30.6752,104.0975);
            // Values compared with the desktop coordtransform reference as part of local validation.
            check(c[0]>30.672 && c[0]<30.674 && c[1]>104.099 && c[1]<104.101,"Shahe GCJ02");
            double[] unchanged=Coordinates.from(c[0],c[1],"gcj02");
            check(unchanged[0]==c[0] && unchanged[1]==c[1],"domestic map coordinates unchanged");
            check(Coordinates.gcj(3.86,73.66)[0]==3.86,"strict boundary");
            rejects(()->Coordinates.gcj(Double.NaN,104),"invalid point");
            check(Coordinates.distance(30,104,30,104)==0,"distance identity");
            rejects(()->SchoolClient.validate(new JSONObject().put("businessDate","2000-01-01").put("recordStatusCode","PENDING")),"wrong date");
            rejects(()->SchoolClient.validate(new JSONObject().put("businessDate",SchoolClient.day()).put("recordStatusCode","UNKNOWN")),"unknown status");
            rejects(()->SchoolClient.validate(new JSONObject().put("businessDate",SchoolClient.day()).put("recordStatusCode","CHECKED_IN").put("abnormalFlag",true)),"abnormal");
            rejects(()->SchoolClient.window(new JSONObject().put("effective",false)),"invalid schedule");
            rejects(()->SchoolClient.fence(c,new JSONArray()),"empty fence");
            check(!SchoolClient.confirmed(new JSONObject().put("businessDate",SchoolClient.day()).put("recordStatusCode","PENDING").put("abnormalFlag",false)),"pending unconfirmed");
            fake=new FakeSchool(); final FakeSchool f=fake;
            Intent intent=new Intent(getTargetContext(),MainActivity.class); intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity=(MainActivity)startActivitySync(intent);
            final MainActivity a=activity;
            set(a,"wechat",new WeChatAuth(getTargetContext(),(kind,value)->{}) {
                @Override String forSubmission(String session) { return "t".repeat(43); }
            });
            check(WeChatAuth.selfTest(getTargetContext()),"phone-local Python crypto and protocol import");
            SharedPreferences prefs=getTargetContext().getSharedPreferences("instrumentation-only",0); prefs.edit().clear().commit();
            set(a,"school",f); set(a,"state",prefs);
            for(int retry=0;retry<20 && !"true".equals(js(a,"typeof window.onNative==='function'"));retry++) Thread.sleep(200);
            check("true".equals(js(a,"typeof window.onNative==='function'")),"dashboard scripts loaded");
            check("true".equals(js(a,"tiles._url.includes('autonavi.com')")),"domestic tile source");
            check("true".equals(js(a,"document.getElementById('lat').parentNode.textContent.includes('GCJ-02')")),"GCJ02 label");
            check("true".equals(js(a,"point(30.672809764,104.100042314); document.getElementById('qingshuihe').click(); Math.abs(marker.getLatLng().lat-30.672809764)<1e-9")),"campus switch keeps selected point");
            check("true".equals(js(a,"map.fire('click',{latlng:L.latLng(30.6728,104.1000)}); document.getElementById('lat').value==='30.6728000'")),"map click selects GCJ02 point");
            check("true".equals(js(a,"map.scrollWheelZoom.enabled()")),"wheel zoom");
            Method precheck=MainActivity.class.getDeclaredMethod("precheck",double[].class); precheck.setAccessible(true);
            String address=(String)precheck.invoke(a,(Object)c);
            check(address.contains("模拟"),"readonly address"); check(f.posts==0,"readonly never POST"); check(f.reads==4,"four readonly endpoints");
            Method submit=MainActivity.class.getDeclaredMethod("submit",double[].class,String.class,String.class,long.class); submit.setAccessible(true);
            submit.invoke(a,c,address,SchoolClient.day(),SystemClock.elapsedRealtime());
            check(f.posts==1,"one explicit POST"); check("confirmed".equals(prefs.getString("attempt:"+SchoolClient.day(),"")),"readback confirmed");
            check(Math.abs(f.payload.getDouble("latitude")-c[0])<1e-12,"no double conversion");
            check("gcj02".equals(f.payload.getString("coordinateSystemCode")),"coordinate system");
            check(!f.payload.getBoolean("locationEnabled"),"no fabricated sensor claim");
            try { submit.invoke(a,c,address,SchoolClient.day(),SystemClock.elapsedRealtime()); } catch(InvocationTargetException expected) { check(expected.getCause() instanceof IOException,"duplicate rejected"); }
            check(f.posts==1,"no duplicate POST");
            prefs.edit().clear().commit(); f.uncertain=true; f.posts=0;
            submit.invoke(a,c,address,SchoolClient.day(),SystemClock.elapsedRealtime());
            check(f.posts==1,"timeout never retries POST"); check("uncertain".equals(prefs.getString("attempt:"+SchoolClient.day(),"")),"uncertain persisted");
            prefs.edit().clear().commit();
            result.putString("stream","PASS: "+assertions+" assertions; all school APIs mocked; no real attendance submitted.\n");
            finish(Activity.RESULT_OK,result);
        } catch(Throwable error) {
            result.putString("stream","FAIL: "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n"); finish(Activity.RESULT_CANCELED,result);
        } finally {
            if(fake!=null)fake.close();
            if(activity!=null) { MainActivity a=activity; runOnMainSync(a::finish); }
        }
    }
}
