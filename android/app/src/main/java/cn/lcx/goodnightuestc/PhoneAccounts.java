package cn.lcx.goodnightuestc;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.file.Files;
final class PhoneAccounts {
 private final Context context; private final WeChatAuth auth;
 private final String libraryFile,credentialPrefix;
 PhoneAccounts(Context c,WeChatAuth a){this(c,a,"phone-accounts.enc","wechat-account-");}
 PhoneAccounts(Context c,WeChatAuth a,String library,String prefix){context=c.getApplicationContext();auth=a;libraryFile=library;credentialPrefix=prefix;}
 JSONArray all() throws Exception {String raw=auth.readEncrypted(libraryFile);return raw.isEmpty()?new JSONArray():new JSONArray(raw);}
 void importPrivate() throws Exception {
  File f=new File(context.getFilesDir(),"private-account-import.json");if(!f.exists())return;
  try{
   if((context.getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE)==0 || f.length()>65536)throw new IOException("import_blocked");
   JSONArray rows=new JSONArray(new String(Files.readAllBytes(f.toPath()),java.nio.charset.StandardCharsets.UTF_8));
   if(rows.length()!=3)throw new IOException("import_count_invalid");
   for(int i=0;i<rows.length();i++){JSONObject p=rows.getJSONObject(i);if(!p.getString("session").matches("[A-Za-z0-9_-]{1,1024}"))throw new IOException("import_session_invalid");p.getJSONObject("credentials").getString("school_username");p.getJSONObject("point").getDouble("lat");}
   for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);auth.writeEncrypted(credentialPrefix+i+".enc",row.getJSONObject("credentials").toString());row.remove("credentials");}
   auth.writeEncrypted(libraryFile,rows.toString());context.getSharedPreferences("local",0).edit().putInt("account_index",0).commit();
   DiagnosticLog.add("private_import count=3");
  }finally{Files.deleteIfExists(f.toPath());}
 }
 synchronized int save(JSONObject candidate)throws Exception {
  String sid=candidate.getString("student_id");
  if(!sid.matches("[0-9A-Za-z_-]{1,64}"))throw new IOException("账号身份无效");
  String session=candidate.getString("session");
  if(!session.matches("[A-Za-z0-9_-]{1,1024}"))throw new IOException("学校会话无效");
  JSONObject credentials=candidate.getJSONObject("credentials");
  for(String k:new String[]{"openid","access_token","refresh_token"})if(credentials.optString(k).isEmpty())throw new IOException("微信授权不完整，请重新授权");
  JSONObject point=candidate.getJSONObject("point");Coordinates.from(point.getDouble("lat"),point.getDouble("lng"),"gcj02");
  JSONArray rows=all();int index=-1;
  for(int i=0;i<rows.length();i++)if(sid.equals(rows.getJSONObject(i).optString("student_id"))){index=i;break;}
  if(index<0){if(rows.length()>=20)throw new IOException("本机账号库已达20个账号上限");index=rows.length();}
  JSONObject metadata=new JSONObject(candidate.toString());metadata.remove("credentials");
  auth.writeEncrypted(credentialPrefix+index+".enc",credentials.toString());rows.put(index,metadata);
  auth.writeEncrypted(libraryFile,rows.toString());
  DiagnosticLog.add("account_saved index="+index);return index;
 }
 JSONObject select(int index)throws Exception {
  JSONObject row=all().getJSONObject(index);auth.useAccount(index);
  context.getSharedPreferences(libraryFile.equals("phone-accounts.enc")?"local":"instrumentation-library-state",0).edit().putInt("account_index",index).putString("point",row.getJSONObject("point").toString()).commit();return row;
 }
}
