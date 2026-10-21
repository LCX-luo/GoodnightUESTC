package cn.lcx.goodnightuestc;

import android.webkit.CookieManager;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;

/** Only the four read APIs and a single explicit POST are exposed. Never retries a POST. */
class SchoolClient {
    static final String ORIGIN="https://jzsz.uestc.edu.cn";
    static final String ENTRY=ORIGIN+"/daily-checkin/checkLogin?appId=294";
    static final String TODAY="/student-checkin-record/today";
    static final String SCHEDULE="/checkin-schedule/effective";
    static final String FENCES="/checkin-location/available-locations";
    static final String REVERSE="/map/reverse";
    static final String POST="/student-checkin-record/checkin";
    private Proxy route;
    private long routeAt;
    private final String agent;
    private final ExecutorService probes=Executors.newFixedThreadPool(2);
    SchoolClient(String agent) { this.agent=agent; }
    void close() { probes.shutdownNow(); }
    static LocalDateTime now() { return LocalDateTime.now(ZoneId.of("Asia/Shanghai")); }
    static String day() { return now().toLocalDate().toString(); }
    private Object request(String path, JSONObject payload, Proxy proxy) throws Exception {
        boolean post=payload!=null;
        String base=path.split("\\?",2)[0];
        if (post ? !POST.equals(base) : !Arrays.asList(TODAY,SCHEDULE,FENCES,REVERSE).contains(base))
            throw new IOException("未允许的接口");
        HttpURLConnection c=(HttpURLConnection)new URL(ORIGIN+"/daily-checkin/api"+path).openConnection(proxy);
        try {
            c.setConnectTimeout(4500); c.setReadTimeout(post?12000:6500);
            c.setInstanceFollowRedirects(false);
            c.setRequestMethod(post?"POST":"GET");
            c.setRequestProperty("Accept","application/json");
            c.setRequestProperty("Platform","h5");
            c.setRequestProperty("Origin",ORIGIN);
            c.setRequestProperty("Referer",ORIGIN+"/daily-checkin-h5/index.html?appId=294");
            c.setRequestProperty("User-Agent",agent);
            String cookies=CookieManager.getInstance().getCookie(ORIGIN);
            if (cookies!=null) c.setRequestProperty("Cookie",cookies);
            if(post) {
                byte[] bytes=payload.toString().getBytes(StandardCharsets.UTF_8);
                c.setDoOutput(true); c.setRequestProperty("Content-Type","application/json;charset=UTF-8");
                c.setFixedLengthStreamingMode(bytes.length);
                try(OutputStream out=c.getOutputStream()) { out.write(bytes); }
            }
            int status=c.getResponseCode();
            for(Map.Entry<String,List<String>> entry:c.getHeaderFields().entrySet())
                if("Set-Cookie".equalsIgnoreCase(entry.getKey()))
                    for(String value:entry.getValue()) CookieManager.getInstance().setCookie(ORIGIN,value);
            if(status>=300 && status<400 || status==401 || status==403) throw new IOException("请重新登录学校账号");
            if(status!=200) throw new IOException("学校接口返回 HTTP "+status);
            String body;
            try(InputStream in=c.getInputStream(); ByteArrayOutputStream out=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192]; int n;
                while((n=in.read(buffer))!=-1) { if(out.size()+n>1048576) throw new IOException("响应过大"); out.write(buffer,0,n); }
                body=out.toString("UTF-8");
            }
            JSONObject envelope;
            try { envelope=new JSONObject(body); } catch(JSONException ex) { throw new IOException("未收到学校 JSON 数据，请重新登录"); }
            if(!envelope.has("code") || envelope.optInt("code",-1)!=0) {
                // Do not echo upstream messages, which can contain account/session information.
                throw new IOException("学校未接受请求（代码 "+envelope.optInt("code",-1)+"），请检查登录或使用官方入口");
            }
            if(envelope.isNull("data")) throw new IOException("学校返回空数据");
            return envelope.get("data");
        } finally { c.disconnect(); }
    }
    private Proxy systemProxy() {
        try {
            for(Proxy p:ProxySelector.getDefault().select(URI.create(ORIGIN)))
                if(p!=null && p.type()!=Proxy.Type.DIRECT) return p;
        } catch(Exception ignored) { }
        return Proxy.NO_PROXY;
    }
    synchronized Object get(String path) throws Exception {
        Proxy system=systemProxy();
        if(route!=null && System.currentTimeMillis()-routeAt<120000) {
            try { return request(path,null,route); } catch(Exception ex) { route=null; }
        }
        if(system==Proxy.NO_PROXY) {
            Object result=request(path,null,Proxy.NO_PROXY); route=Proxy.NO_PROXY; routeAt=System.currentTimeMillis(); return result;
        }
        // Race only GET requests. Do not select a route by sending the attendance POST.
        CompletionService<Object[]> race=new ExecutorCompletionService<>(probes);
        Future<Object[]> direct=race.submit(()->new Object[]{Proxy.NO_PROXY,request(path,null,Proxy.NO_PROXY)});
        Future<Object[]> proxied=race.submit(()->{ Thread.sleep(150); return new Object[]{system,request(path,null,system)}; });
        Exception error=null;
        try {
            for(int i=0;i<2;i++) {
                try {
                    Object[] result=race.take().get(); route=(Proxy)result[0]; routeAt=System.currentTimeMillis(); return result[1];
                } catch(ExecutionException ex) { error=ex.getCause() instanceof Exception ? (Exception)ex.getCause():ex; }
            }
            throw error==null?new IOException("网络不可用"):error;
        } finally { direct.cancel(true); proxied.cancel(true); }
    }
    synchronized void post(JSONObject payload) throws Exception {
        if(route==null) throw new IOException("请先运行在线检查以确定网络连接");
        request(POST,payload,route); // Exactly one attempt, even on timeout or server rejection.
    }
    JSONObject today() throws Exception {
        JSONObject record=(JSONObject)get(TODAY); validate(record); return record;
    }
    static String validate(JSONObject r) throws Exception {
        if(!day().equals(r.optString("businessDate"))) throw new IOException("学校业务日期与北京时间不一致");
        String status=r.optString("recordStatusCode");
        if(!Arrays.asList("PENDING","CHECKED_IN","STUDENT_REPORTED","INSTRUCTOR_REPORTED","EXEMPT").contains(status))
            throw new IOException("学校返回未知记录状态");
        if(r.has("abnormalFlag") && !r.isNull("abnormalFlag") && !Boolean.FALSE.equals(r.get("abnormalFlag")))
            throw new IOException("学校记录异常，请查看官方入口");
        return status;
    }
    static boolean confirmed(JSONObject record) throws Exception {
        return "CHECKED_IN".equals(validate(record)) && Boolean.FALSE.equals(record.opt("abnormalFlag"))
            && !record.optString("checkinTime","").isEmpty();
    }
    static String window(JSONObject schedule) throws Exception {
        double s=schedule.optDouble("studentCheckinStartOffsetMinute",Double.NaN);
        double e=schedule.optDouble("studentCheckinEndOffsetMinute",Double.NaN);
        if(!Boolean.TRUE.equals(schedule.opt("effective")) || !Double.isFinite(s) || !Double.isFinite(e)
            || s!=Math.floor(s) || e!=Math.floor(e) || s<0 || s>=e || e>1440)
            throw new IOException("学校时段数据不可用");
        LocalDateTime t=now(); double minute=t.getHour()*60+t.getMinute()+t.getSecond()/60.;
        if(!(s<=minute && minute<e-2)) throw new IOException("当前不在学校签到时段内（结束前两分钟停止提交）");
        return String.format(Locale.ROOT,"%02d:%02d—%02d:%02d",(int)s/60,(int)s%60,(int)e/60,(int)e%60);
    }
    static void fence(double[] point,JSONArray fences) throws Exception {
        for(int i=0;i<fences.length();i++) {
            JSONObject f=fences.getJSONObject(i);
            double lat=f.optDouble("latitude",Double.NaN),lng=f.optDouble("longitude",Double.NaN),radius=f.optDouble("radiusMeter",Double.NaN);
            if(Double.isFinite(lat)&&Double.isFinite(lng)&&Double.isFinite(radius)&&Math.abs(lat)<=90&&Math.abs(lng)<=180&&radius>0
                && Coordinates.distance(point[0],point[1],lat,lng)<=radius) return;
        }
        throw new IOException("所选位置不在学校允许范围内");
    }
}
