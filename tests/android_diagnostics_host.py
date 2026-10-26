"""Run the actual Java diagnostic store on a host JVM with minimal Android I/O stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class DiagnosticsHost(unittest.TestCase):
    def test_round_retention_and_restart(self):
        java_home = Path(os.environ.get('JAVA_HOME', 'C:/Program Files/Android/Android Studio/jbr'))
        javac = shutil.which('javac') or str(java_home / 'bin/javac.exe')
        java = shutil.which('java') or str(java_home / 'bin/java.exe')
        with tempfile.TemporaryDirectory(prefix='gn-diagnostics-') as directory:
            root=Path(directory)
            sources={
                'android/content/Context.java': 'package android.content; public class Context {private java.io.File f; public Context(java.io.File v){f=v;} public java.io.File getFilesDir(){return f;}}',
                'android/os/Build.java': 'package android.os; public class Build {public static class VERSION {public static int SDK_INT=36;}}',
                'android/util/AtomicFile.java': 'package android.util; public class AtomicFile {private java.io.File f; public AtomicFile(java.io.File v){f=v;} public java.io.FileOutputStream startWrite()throws Exception{return new java.io.FileOutputStream(f);}public void finishWrite(java.io.FileOutputStream s)throws Exception{s.close();}public void failWrite(java.io.FileOutputStream s)throws Exception{s.close();}}',
                'cn/lcx/goodnightuestc/DiagnosticLog.java': (ROOT/'android/app/src/main/java/cn/lcx/goodnightuestc/DiagnosticLog.java').read_text('utf-8'),
                'cn/lcx/goodnightuestc/DiagnosticsHarness.java': r'''package cn.lcx.goodnightuestc;
import java.io.*;
public class DiagnosticsHarness {
 static int checks;
 static void check(boolean value,String label){if(!value)throw new AssertionError(label);checks++;}
 public static void main(String[] args)throws Exception {
  File dir=new File(args[0]);dir.mkdirs();android.content.Context context=new android.content.Context(dir);DiagnosticLog.init(context);
  DiagnosticLog.begin("authorize");DiagnosticLog.add("first_failure_marker");DiagnosticLog.finish(false);
  DiagnosticLog.begin("submit");DiagnosticLog.add("success_verbose_marker");DiagnosticLog.success();DiagnosticLog.finish(true);
  check(DiagnosticLog.copy().contains("first_failure_marker"),"success preserves older failure");
  check(!DiagnosticLog.copy().contains("success_verbose_marker"),"normal detail removed");
  check(DiagnosticLog.copy().contains("outcome=confirmed"),"confirmed summary retained");
  DiagnosticLog.begin("submit");DiagnosticLog.add("window_verbose_marker");DiagnosticLog.outcome("window_4006");DiagnosticLog.finish(true);
  check(!DiagnosticLog.copy().contains("window_verbose_marker"),"window refusal compressed");
  check(DiagnosticLog.copy().contains("outcome=window_4006"),"window summary retained");
  DiagnosticLog.begin("submit");DiagnosticLog.add("unknown_result_marker");DiagnosticLog.finish(true);
  check(DiagnosticLog.copy().contains("unknown_result_marker"),"unknown submission preserves detail even without thrown exception");
  for(int n=0;n<6;n++){DiagnosticLog.begin("authorize");DiagnosticLog.add("failure_number="+n);for(int i=0;i<100;i++)DiagnosticLog.add("index="+i+" padding="+"x".repeat(180));DiagnosticLog.add("last_failure_number="+n);DiagnosticLog.finish(false);}
  String all=DiagnosticLog.copy();check(!all.contains("last_failure_number=2"),"only latest three failure rounds");check(all.contains("last_failure_number=3")&&all.contains("last_failure_number=5"),"latest failures retained");
  for(int n=0;n<30;n++){DiagnosticLog.begin("query");DiagnosticLog.add("query_detail="+n);DiagnosticLog.finish(true);}
  all=DiagnosticLog.copy();check(all.split(" query normal",-1).length-1==20,"twenty normal summaries");
  DiagnosticLog.begin("authorize");for(int i=0;i<200;i++)DiagnosticLog.add("active_index="+i+" padding="+"y".repeat(180));
  DiagnosticLog.add("https://secret.example/?token=secret_value");
  check(!DiagnosticLog.copy().contains("secret_value"),"unfiltered URL rejected");
  check(DiagnosticLog.copy().getBytes(java.nio.charset.StandardCharsets.UTF_8).length<65536,"copy bounded");
  check(new File(dir,"diagnostic-rounds.log").length()<65536,"disk bounded");
  java.lang.reflect.Field field=DiagnosticLog.class.getDeclaredField("file");field.setAccessible(true);field.set(null,null);DiagnosticLog.init(context);
  check(DiagnosticLog.copy().contains("authorize interrupted"),"unfinished round retained after restart");
  check(DiagnosticLog.copy().getBytes(java.nio.charset.StandardCharsets.UTF_8).length<65536,"restart remains bounded");
  System.out.println("PASS: "+checks+" real Java log-store assertions; no phone or network access.");
 }
}'''
            }
            files=[]
            for name,text in sources.items():
                target=root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,'utf-8');files.append(str(target))
            subprocess.run([javac,'-encoding','UTF-8','-d',str(root),*files],check=True,capture_output=True)
            result=subprocess.run([java,'-cp',str(root),'cn.lcx.goodnightuestc.DiagnosticsHarness',str(root/'data')],check=True,capture_output=True,text=True)
            print(result.stdout.strip())

if __name__=='__main__':unittest.main()
