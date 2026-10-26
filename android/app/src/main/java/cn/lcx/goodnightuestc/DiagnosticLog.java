package cn.lcx.goodnightuestc;
import android.content.Context;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;
/** Bounded per-operation history: three failures, twenty compact normal summaries. */
final class DiagnosticLog {
 private static File file;private static final List<Round> rounds=new ArrayList<>();
 private static Round active;private static String ambient="";private static String outcome;
 private static final int DETAIL=12000,ACTIVE=16000;
 private static final class Round {
  String id,op,status,body;Round(String i,String o,String s,String b){id=i;op=o;status=s;body=b;}
 }
 static synchronized void init(Context c) {
  File target=new File(c.getFilesDir(),"diagnostic-rounds.log");if(file!=null&&file.equals(target))return;
  file=target;rounds.clear();active=null;ambient="";
  try{
   if(file.exists()&&file.length()<=65536){
    Round item=null;
    for(String line:Files.readAllLines(file.toPath(),StandardCharsets.UTF_8)){
     if(line.startsWith("@round ")){String[] h=line.split(" ",4);if(h.length==4)item=new Round(h[1],h[2],h[3],"");}
     else if(line.equals("@end")){if(item!=null){if(item.op.equals("lifecycle"))ambient=tail(item.body,2048);else{if(item.status.equals("active"))item.status="interrupted";rounds.add(item);}item=null;}}
     else if(item!=null)item.body+=line+"\n";
    }
   }else{
    File legacy=new File(c.getFilesDir(),"diagnostics.log");
    if(legacy.exists()&&legacy.length()<=65536){String old=new String(Files.readAllBytes(legacy.toPath()),StandardCharsets.UTF_8);rounds.add(new Round("legacy","legacy","failure",tail(old,DETAIL)));persist();Files.deleteIfExists(legacy.toPath());}
   }
  }catch(Exception ignored){}
  trim();
 }
 private static String tail(String text,int limit){if(text.length()<=limit)return text;String cut=text.substring(text.length()-limit);int n=cut.indexOf('\n');return "truncated=older_events\n"+cut.substring(n+1);}
 static synchronized void begin(String op){
  if(!op.matches("[a-z_]{1,32}"))return;
  if(active!=null){active.status="interrupted";active.body=tail(active.body,DETAIL);rounds.add(active);}
  active=new Round(Long.toString(System.currentTimeMillis()),op,"active",ambient);ambient="";outcome=null;persist();
 }
 static synchronized void add(String event){
  if(file==null||event==null||event.length()>360||!event.matches("[a-zA-Z0-9_= .,:/()\\-]+"))return;
  String line=System.currentTimeMillis()+" "+event+"\n";
  if(active!=null)active.body=tail(active.body+line,ACTIVE);else ambient=tail(ambient+line,2048);
  persist();
 }
 static String reason(Throwable e){StringBuilder b=new StringBuilder();for(int i=0;e!=null&&i<4;i++,e=e.getCause()){if(i>0)b.append('_');b.append(e.getClass().getSimpleName().replaceAll("[^a-zA-Z0-9_]",""));}return b.toString();}
 static synchronized void outcome(String value){if(value.matches("[a-z_0-9]{1,64}"))outcome=value;}
 /** Mark only this round confirmed; earlier failures remain intact. */
 static synchronized void success(){outcome="confirmed";}
 static synchronized void finish(boolean completed){
  if(active==null)return;
  boolean normal=completed&&(!active.op.equals("submit")||"confirmed".equals(outcome)||"window_4006".equals(outcome));
  active.status=normal?"normal":"failure";
  if(normal)active.body="summary outcome="+(outcome==null?"completed":outcome)+" ms="+(System.currentTimeMillis()-Long.parseLong(active.id))+"\n";
  else active.body=tail(active.body+"outcome="+(outcome==null?"failed_or_unknown":outcome)+"\n",DETAIL);
  rounds.add(active);active=null;outcome=null;trim();persist();
 }
 private static void trim(){int failures=0,normal=0;for(int i=rounds.size()-1;i>=0;i--){Round r=rounds.get(i);if(r.status.equals("normal")){r.body=tail(r.body,256);if(++normal>20)rounds.remove(i);}else{r.body=tail(r.body,DETAIL);if(++failures>3)rounds.remove(i);}}}
 private static void append(StringBuilder b,Round r){b.append("@round ").append(r.id).append(' ').append(r.op).append(' ').append(r.status).append('\n').append(r.body).append("@end\n");}
 private static void persist(){
  if(file==null)return;trim();StringBuilder b=new StringBuilder();for(Round r:rounds)append(b,r);if(active!=null)append(b,active);if(!ambient.isEmpty())append(b,new Round("0","lifecycle","normal",ambient));
  try{android.util.AtomicFile out=new android.util.AtomicFile(file);FileOutputStream stream=out.startWrite();try{stream.write(b.toString().getBytes(StandardCharsets.UTF_8));out.finishWrite(stream);}catch(Exception e){out.failWrite(stream);}}catch(Exception ignored){}
 }
 static synchronized String copy(){
  StringBuilder b=new StringBuilder("GoodnightUESTC diagnostics v2 app=0.2.7 android="+android.os.Build.VERSION.SDK_INT+"\nRedacted: no credentials, URLs, identity or coordinates.\nRetention: latest 3 failures, 20 normal summaries, bounded 64KiB.\n");
  for(Round r:rounds)append(b,r);if(active!=null)append(b,active);b.append(ambient);return b.toString();
 }
}
