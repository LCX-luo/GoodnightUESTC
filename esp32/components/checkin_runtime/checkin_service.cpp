#include "checkin_service.h"
#include "protocol.hpp"
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <mutex>
#include <set>
#include <atomic>
#include <sys/time.h>
#include "esp_log.h"
#include "esp_system.h"
#include "esp_random.h"
#include "esp_heap_caps.h"
#include "esp_wifi.h"
#include "esp_sntp.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "mbedtls/md5.h"
#include "mbedtls/base64.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

namespace {
using namespace wc;
const char *TAG="goodnight";
std::mutex storage;
std::mutex execution;
QueueHandle_t jobs=nullptr;
bool storage_ready=false;
struct Job { char account[24];bool submit;bool all;char request[33];char operation[12];int index;bool plan_enabled;int plan_minute; };
std::atomic<bool> time_synchronized{false};
void on_time_sync(struct timeval*){time_synchronized.store(true);}
bool clock_ready(){return time_synchronized.load()&&time(nullptr)>1700000000;}
void management_event(const char*,const std::string&,int,const std::string&,const std::string&);
void begin_outcome(const std::string&);
void outcome_error(const std::string&,const Error&);
std::string sanitized_message(std::string text,const std::string& session="",const std::string& ticket="");
std::string day(){time_t now=time(nullptr);struct tm t;localtime_r(&now,&t);char s[12];strftime(s,sizeof(s),"%Y-%m-%d",&t);return s;}
void event(const char *state,const std::string& account="",int code=0,const std::string& record_status="",const std::string& message=""){management_event(state,account,code,record_status,message);Json out(cJSON_CreateObject());cJSON_AddStringToObject(out.get(),"state",state);cJSON_AddStringToObject(out.get(),"account",account.c_str());if(!record_status.empty())cJSON_AddStringToObject(out.get(),"recordStatus",record_status.c_str());if(!message.empty())cJSON_AddStringToObject(out.get(),"msg",message.c_str());cJSON_AddNumberToObject(out.get(),"code",code);cJSON_AddNumberToObject(out.get(),"epoch",time(nullptr));cJSON_AddNumberToObject(out.get(),"stackFree",uxTaskGetStackHighWaterMark(nullptr));cJSON_AddNumberToObject(out.get(),"heap",esp_get_free_heap_size());cJSON_AddNumberToObject(out.get(),"largestBlock",heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));printf("GN1 %s\n",dump(out.get()).c_str());fflush(stdout);}
std::string read_config(){std::lock_guard<std::mutex> lock(storage);need(storage_ready,"storage_unavailable");nvs_handle_t handle;need(nvs_open_from_partition("checkin","goodnight",NVS_READWRITE,&handle)==ESP_OK,"nvs_open");size_t n=0;auto status=nvs_get_blob(handle,"profiles",nullptr,&n);if(status==ESP_ERR_NVS_NOT_FOUND){nvs_close(handle);return "{\"version\":1,\"enabled\":false,\"accounts\":[]}";}need(status==ESP_OK&&n&&n<20000,"nvs_size");std::string value(n,'\0');status=nvs_get_blob(handle,"profiles",value.data(),&n);nvs_close(handle);need(status==ESP_OK,"nvs_read");return value;}
void write_config(const std::string& value){std::lock_guard<std::mutex> lock(storage);need(storage_ready&&value.size()<20000,"config_limit");nvs_handle_t handle;need(nvs_open_from_partition("checkin","goodnight",NVS_READWRITE,&handle)==ESP_OK,"nvs_open");auto status=nvs_set_blob(handle,"profiles",value.data(),value.size());if(status==ESP_OK)status=nvs_commit(handle);nvs_close(handle);need(status==ESP_OK,"nvs_commit");}
bool claim(const std::string& account,const std::string& date){std::lock_guard<std::mutex> lock(storage);B digest=sha(bytes(account));char key[16];snprintf(key,sizeof(key),"d%02x%02x%02x%02x",digest[0],digest[1],digest[2],digest[3]);nvs_handle_t handle;need(nvs_open_from_partition("checkin","attempts",NVS_READWRITE,&handle)==ESP_OK,"claim_open");char previous[16]={};size_t size=sizeof(previous);auto status=nvs_get_str(handle,key,previous,&size);if(status==ESP_OK&&previous==date){nvs_close(handle);return false;}status=nvs_set_str(handle,key,date.c_str());if(status==ESP_OK)status=nvs_commit(handle);nvs_close(handle);need(status==ESP_OK,"claim_commit");return true;}
Json school(const char *method,const std::string& path,const std::string& session,const cJSON *body=nullptr,const std::string& ticket=""){need(path.rfind("/daily-checkin/api/",0)==0||path.rfind("/platform-app/api/auth/",0)==0,"school_path");need(session.find_first_of("\r\n;\"\\")==std::string::npos,"session_header");std::map<std::string,std::string> headers={{"Accept","application/json"},{"Platform",path.rfind("/platform-app/",0)==0?"mp-weixin":"h5"},{"Content-Type","application/json"}};if(!session.empty())headers["Cookie"]="SESSION="+session;if(!ticket.empty())headers["X-Checkin-Ticket"]=ticket;Http response=https("https://jzsz.uestc.edu.cn"+path,method,body?dump(body):"",headers);need(response.status==200,"school_http");Json result=json(response.body);auto code=cJSON_GetObjectItem(result.get(),"code"),ok=cJSON_GetObjectItem(result.get(),"ok");bool success=path.rfind("/platform-app/",0)==0?cJSON_IsTrue(ok):(cJSON_IsNumber(code)&&code->valueint==0&&!cJSON_IsFalse(ok));if(!success){int value=cJSON_IsNumber(code)?code->valueint:-1;auto raw_message=cJSON_GetObjectItem(result.get(),"msg");std::string message=cJSON_IsString(raw_message)?sanitized_message(raw_message->valuestring,session,ticket):"";event("school_rejected","",value,"",message);throw Error("school_business",value,message);}return result;}
const cJSON *data(const Json& j){auto p=cJSON_GetObjectItem(j.get(),"data");need(p&&!cJSON_IsNull(p),"school_data");return p;}
Json signed_request(const std::string& operation,const cJSON *body,const cJSON *credentials,bool cookies){std::string raw=dump(body);struct timeval timestamp_value;gettimeofday(&timestamp_value,nullptr);std::string timestamp=std::to_string(int64_t(timestamp_value.tv_sec)*1000+timestamp_value.tv_usec/1000),nonce=std::to_string(esp_random()%10000);std::string source=raw+timestamp+"wgrdg373hy26ww2"+nonce;unsigned char digest[16];need(mbedtls_md5((const unsigned char*)source.data(),source.size(),digest)==0,"oauth_signature");char signature[33];for(int i=0;i<16;i++)snprintf(signature+i*2,3,"%02x",digest[i]);std::map<std::string,std::string> headers={{"Accept","application/json"},{"Content-Type","application/json"},{"Ual-Access-Businessid","pc_yyb_auth"},{"Ual-Access-Timestamp",timestamp},{"Ual-Access-Nonce",nonce},{"Ual-Access-Signature",signature}};if(cookies){std::string openid=str(credentials,"openid"),access=str(credentials,"access_token"),refresh=str(credentials,"refresh_token");need((openid+access+refresh).find_first_of("\r\n;\"\\")==std::string::npos,"oauth_cookie");headers["Cookie"]="openid="+openid+"; accesstoken="+access+"; refreshtoken="+refresh;}Http response=https("https://yybadaccess.3g.qq.com/pc_yyb_auth/"+operation,"POST",raw,headers);need(response.status==200,"oauth_http");Json value=json(response.body);auto code=cJSON_GetObjectItem(value.get(),"code");if(!cJSON_IsNumber(code)||code->valueint!=0){auto message=cJSON_GetObjectItem(value.get(),"msg");if(!cJSON_IsString(message))message=cJSON_GetObjectItem(value.get(),"message");throw Error("oauth_rejected",cJSON_IsNumber(code)?code->valueint:-1,cJSON_IsString(message)?sanitized_message(message->valuestring):"");}return value;}
void refresh(cJSON *credentials,bool force=false){auto expires=cJSON_GetObjectItem(credentials,"expires_at");need(cJSON_IsNumber(expires),"credential_expiry");if(!force&&expires->valuedouble>time(nullptr)+60)return;Json body(cJSON_CreateObject());auto info=cJSON_AddObjectToObject(body.get(),"userInfo");cJSON_AddStringToObject(info,"openId",str(credentials,"openid").c_str());cJSON_AddStringToObject(info,"refreshToken",str(credentials,"refresh_token").c_str());cJSON_AddStringToObject(info,"accessToken",str(credentials,"access_token").c_str());cJSON_AddStringToObject(info,"loginType","WX");Json response=signed_request("pcyyb_refresh_token_auth",body.get(),credentials,false);auto user=cJSON_GetObjectItem(response.get(),"user_info");std::string access=str(user,"access_token");auto seconds=cJSON_GetObjectItem(user,"expires_in");int expiry=cJSON_IsString(seconds)?atoi(seconds->valuestring):cJSON_IsNumber(seconds)?seconds->valueint:7200;need(expiry>0,"refresh_expiry");cJSON_ReplaceItemInObject(credentials,"access_token",cJSON_CreateString(access.c_str()));auto token=cJSON_GetObjectItem(user,"refresh_token");if(cJSON_IsString(token)&&strlen(token->valuestring))cJSON_ReplaceItemInObject(credentials,"refresh_token",cJSON_CreateString(token->valuestring));cJSON_SetNumberValue(expires,time(nullptr)+expiry);}
std::string get_buffer(cJSON *credentials){Json body(cJSON_CreateObject());auto ext=cJSON_AddObjectToObject(body.get(),"extInfo"),list=cJSON_AddObjectToObject(ext,"listS");for(auto key:{"unionid","user_id","access_token"}){auto item=cJSON_AddObjectToObject(list,key),values=cJSON_AddArrayToObject(item,"value");cJSON_AddItemToArray(values,cJSON_CreateString(str(credentials,strcmp(key,"access_token")==0?"access_token":"openid").c_str()));}auto ints=cJSON_AddObjectToObject(ext,"listI"),item=cJSON_AddObjectToObject(ints,"user_type"),values=cJSON_AddArrayToObject(item,"value");cJSON_AddItemToArray(values,cJSON_CreateNumber(0));Json response=signed_request("pcyyb_get_wx_login_buffer_auth",body.get(),credentials,true);auto result=cJSON_GetObjectItem(cJSON_GetObjectItem(cJSON_GetObjectItem(response.get(),"ext_info"),"list_s"),"login_buffer");auto buffer=cJSON_GetArrayItem(cJSON_GetObjectItem(result,"value"),0);need(cJSON_IsString(buffer)&&strlen(buffer->valuestring)>0,"login_buffer_missing");return buffer->valuestring;}
std::string get_buffer_refresh(cJSON *account,Json& configuration){
    auto credentials=cJSON_GetObjectItem(account,"wechat");
    try{return get_buffer(credentials);}
    catch(const Error& error){
        if(std::string(error.what())!="oauth_rejected"||error.code!=-101)throw;
        // A still-in-TTL token can be invalidated elsewhere. One refresh only,
        // and persist rotated credentials BEFORE requesting a second buffer.
        event("refreshing_rejected_credential",str(account,"student_id"),error.code,"",error.school_message);
        refresh(credentials,true);write_config(dump(configuration.get()));
        std::string buffer=get_buffer(credentials);event("credential_recovered",str(account,"student_id"));return buffer;
    }
}
std::string bootstrap_session(cJSON *account,Json& configuration){
    std::string sid=str(account,"student_id");auto credentials=cJSON_GetObjectItem(account,"wechat");
    refresh(credentials);write_config(dump(configuration.get()));event("wechat_login_code",sid);
    std::string first=login_code(get_buffer_refresh(account,configuration),"wxaa78bf2905f01cee");
    Json body(cJSON_CreateObject());cJSON_AddStringToObject(body.get(),"code",first.c_str());cJSON_AddStringToObject(body.get(),"sn","");
    Json binding=school("POST","/platform-app/api/auth/check-bind","",body.get());auto bound=data(binding);
    need(cJSON_IsTrue(cJSON_GetObjectItem(bound,"bind")),"school_not_bound");std::string session=str(bound,"sessionId");
    Json identity=school("GET","/platform-app/api/auth/user-info",session);auto mini=cJSON_GetObjectItem(data(identity),"userData");
    need(str(mini,"username")==sid,"wechat_identity_mismatch");
    cJSON_ReplaceItemInObject(account,"schoolSession",cJSON_CreateString(session.c_str()));write_config(dump(configuration.get()));
    event("school_session_ready",sid);return session;
}
std::string get_ticket(cJSON *account,Json& configuration){
    std::string sid=str(account,"student_id"),session=str(account,"schoolSession");event("wechat_ticket_code",sid);
    std::string second=login_code(get_buffer_refresh(account,configuration),"wxaa78bf2905f01cee");
    Json body(cJSON_CreateObject());cJSON_AddStringToObject(body.get(),"code",second.c_str());
    Json response=school("POST","/platform-app/api/auth/checkin-ticket",session,body.get());std::string ticket=str(data(response),"ticket");
    need(ticket.size()==43&&ticket.find_first_not_of("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")==std::string::npos,"ticket_format");
    event("ticket_ready",sid);return ticket;
}
void window(const cJSON *schedule){auto effective=cJSON_GetObjectItem(schedule,"effective"),start=cJSON_GetObjectItem(schedule,"studentCheckinStartOffsetMinute"),end=cJSON_GetObjectItem(schedule,"studentCheckinEndOffsetMinute");need(cJSON_IsTrue(effective)&&cJSON_IsNumber(start)&&cJSON_IsNumber(end),"schedule_fields");time_t now=time(nullptr);struct tm local;localtime_r(&now,&local);double minute=local.tm_hour*60+local.tm_min+local.tm_sec/60.;need(start->valuedouble>=0&&start->valuedouble<end->valuedouble&&end->valuedouble<=1440,"schedule_range");need(minute>=start->valuedouble&&minute<end->valuedouble-2,"outside_checkin_window");}
void fence(const cJSON *point,const cJSON *locations){auto la=cJSON_GetObjectItem(point,"latitude"),lo=cJSON_GetObjectItem(point,"longitude");need(cJSON_IsNumber(la)&&cJSON_IsNumber(lo)&&std::isfinite(la->valuedouble)&&std::isfinite(lo->valuedouble)&&fabs(la->valuedouble)<=90&&fabs(lo->valuedouble)<=180,"location_fields");const double pi=3.14159265358979323846;cJSON *item;cJSON_ArrayForEach(item,locations){auto lat=cJSON_GetObjectItem(item,"latitude"),lng=cJSON_GetObjectItem(item,"longitude"),radius=cJSON_GetObjectItem(item,"radiusMeter");if(!cJSON_IsNumber(lat)||!cJSON_IsNumber(lng)||!cJSON_IsNumber(radius)||radius->valuedouble<=0)continue;double dlat=(lat->valuedouble-la->valuedouble)*pi/180,dlng=(lng->valuedouble-lo->valuedouble)*pi/180;double a=pow(sin(dlat/2),2)+cos(lat->valuedouble*pi/180)*cos(la->valuedouble*pi/180)*pow(sin(dlng/2),2);double distance=6371000*2*asin(sqrt(std::min(1.,a)));if(distance<=radius->valuedouble)return;}throw Error("outside_allowed_location");}
std::string status(const Json& response){const cJSON *record=data(response);need(str(record,"businessDate")==day(),"business_date");auto abnormal=cJSON_GetObjectItem(record,"abnormalFlag");need(!abnormal||cJSON_IsNull(abnormal)||cJSON_IsFalse(abnormal),"abnormal_record");return str(record,"recordStatusCode");}
void run_account(cJSON *account,Json& config,bool submit,bool probe,bool automatic_attempt=false){std::string sid=str(account,"student_id"),session=str(account,"schoolSession");begin_outcome(sid);event("starting",sid);need(clock_ready(),"clock_unsynchronized");need(esp_get_free_heap_size()>110000&&heap_caps_get_largest_free_block(MALLOC_CAP_8BIT)>50000,"insufficient_heap");session=bootstrap_session(account,config);std::string initial;try{Json before=school("GET","/daily-checkin/api/student-checkin-record/today",session);initial=status(before);event("record_before",sid,0,initial);}catch(const Error&){if(!probe)throw;event("precheck_unavailable",sid);}if(initial!="PENDING"&&!probe){event("already_recorded",sid);return;}std::string ticket=get_ticket(account,config);if(!submit){event("authorization_verified",sid);return;}Json schedule;auto point=cJSON_GetObjectItem(account,"location");if(!probe){schedule=school("GET","/daily-checkin/api/checkin-schedule/effective",session);window(data(schedule));Json locations=school("GET","/daily-checkin/api/checkin-location/available-locations",session);fence(point,data(locations));}double lat=cJSON_GetObjectItem(point,"latitude")->valuedouble,lng=cJSON_GetObjectItem(point,"longitude")->valuedouble;char query[160];snprintf(query,sizeof(query),"/daily-checkin/api/map/reverse?lat=%.8f&lng=%.8f",lat,lng);Json reverse=school("GET",query,session);auto address=data(reverse);std::string text;if(cJSON_IsString(address))text=address->valuestring;else for(auto key:{"address","reverseGeocode","formattedAddress"}){auto v=cJSON_GetObjectItem(address,key);if(cJSON_IsString(v)&&strlen(v->valuestring)){text=v->valuestring;break;}}need(!text.empty()&&text.size()<2000,"reverse_address");if(!probe){Json current=school("GET","/daily-checkin/api/student-checkin-record/today",session);if(status(current)!="PENDING"){event("already_recorded",sid);return;}}if(!probe)window(data(schedule));Json body(cJSON_CreateObject());cJSON_AddNumberToObject(body.get(),"latitude",lat);cJSON_AddNumberToObject(body.get(),"longitude",lng);cJSON_AddStringToObject(body.get(),"reverseGeocode",text.c_str());cJSON_AddStringToObject(body.get(),"coordinateSystemCode","gcj02");cJSON_AddNumberToObject(body.get(),"accuracy",0);cJSON_AddNumberToObject(body.get(),"locationDurationMs",0);cJSON_AddStringToObject(body.get(),"networkTypeCode","unknown");cJSON_AddBoolToObject(body.get(),"locationEnabled",false);for(auto key:{"locationAuthorized","locationAccuracy","errorMessage"})cJSON_AddStringToObject(body.get(),key,"");time_t now=time(nullptr);struct tm local;localtime_r(&now,&local);char clock[32];strftime(clock,sizeof(clock),"%Y-%m-%d %H:%M:%S",&local);cJSON_AddStringToObject(body.get(),"clientTime",clock);cJSON_AddStringToObject(body.get(),"userAgent","GoodnightUESTC ESP32/0.1");if(!probe&&!automatic_attempt)need(claim(sid,day()),"prior_attempt_today");int submitted_code=0;bool accepted=false;event("submitting_once",sid);try{Json submission=school("POST","/daily-checkin/api/student-checkin-record/checkin",session,body.get(),ticket);accepted=true;auto msg=cJSON_GetObjectItem(submission.get(),"msg");event("request_accepted",sid,0,"",cJSON_IsString(msg)?sanitized_message(msg->valuestring,session,ticket):"");}catch(const Error& ex){submitted_code=ex.code;event("request_rejected",sid,ex.code,"",ex.school_message);}for(int i=0;i<3;i++){if(i)vTaskDelay(pdMS_TO_TICKS(2000));try{Json record=school("GET","/daily-checkin/api/student-checkin-record/today",session);std::string after=status(record);event("record_after",sid,0,after);if(after=="CHECKED_IN"){event(initial=="CHECKED_IN"||!accepted?"existing_record_only":"checkin_confirmed",sid,submitted_code);return;}}catch(const Error&){}}event(submitted_code!=0?"submission_rejected":accepted?"accepted_pending":"result_unknown_no_retry",sid,submitted_code);}
void validate(const cJSON *config){auto list=cJSON_GetObjectItem(config,"accounts");need(cJSON_IsArray(list)&&cJSON_GetArraySize(list)>0&&cJSON_GetArraySize(list)<=4,"account_count");cJSON *account;cJSON_ArrayForEach(account,list){std::string sid=str(account,"student_id"),session=str(account,"schoolSession");need(sid.size()>=8&&sid.size()<=20&&sid.find_first_not_of("0123456789")==std::string::npos,"student_id");need(session.size()>0&&session.size()<1024,"session_size");auto credentials=cJSON_GetObjectItem(account,"wechat");for(auto key:{"openid","access_token","refresh_token"})need(str(credentials,key).size()<2048,"credential_size");auto point=cJSON_GetObjectItem(account,"location");need(str(point,"coordinate_system")=="gcj02","coordinate_system");need(cJSON_IsNumber(cJSON_GetObjectItem(point,"latitude"))&&cJSON_IsNumber(cJSON_GetObjectItem(point,"longitude")),"location_missing");}}
#include "management.inc"
#include "automation.inc"

void serial_task(void*){std::string line;for(;;){int ch=getchar();if(ch==EOF){clearerr(stdin);vTaskDelay(pdMS_TO_TICKS(20));continue;}if(ch=='\r')continue;if(ch!='\n'){if(line.size()<30000)line.push_back(ch);else line.clear();continue;}if(line.rfind("GN1 ",0)!=0){line.clear();continue;}try{std::string encoded=line.substr(4);size_t n=0;mbedtls_base64_decode(nullptr,0,&n,(const unsigned char*)encoded.data(),encoded.size());need(n>0&&n<20000,"serial_size");B decoded(n);need(mbedtls_base64_decode(decoded.data(),decoded.size(),&n,(const unsigned char*)encoded.data(),encoded.size())==0,"serial_encoding");Json request=json(std::string(decoded.begin(),decoded.begin()+n));std::string op=str(request.get(),"op");if(op=="manage"){auto body=cJSON_GetObjectItem(request.get(),"request");need(cJSON_IsObject(body),"management_request");dispatch_management(dump(body).c_str());}else if(op=="status"){Json config=json(read_config());event(cJSON_IsTrue(cJSON_GetObjectItem(config.get(),"enabled"))?"schedule_enabled":"schedule_disabled");}else if(op=="import"){std::unique_lock<std::mutex> guard(execution,std::try_to_lock);need(guard.owns_lock(),"operation_busy");auto value=cJSON_GetObjectItem(request.get(),"config");validate(value);write_config(dump(value));event("profiles_saved");}else if(op=="probe"||op=="batch"){Job job={};job.all=op=="batch";std::string sid;if(!job.all){sid=str(request.get(),"account");need(sid.size()<sizeof(job.account),"account_length");strcpy(job.account,sid.c_str());}job.submit=cJSON_IsTrue(cJSON_GetObjectItem(request.get(),"submit"));need(xQueueSend(jobs,&job,0)==pdTRUE,"job_busy");event(job.all?"batch_queued":"probe_queued",sid);}else throw Error("unknown_command");}catch(const Error& ex){event(ex.what(),"",ex.code);}catch(...){event("serial_error");}line.clear();}}
void worker(void*){setenv("TZ","CST-8",1);tzset();esp_sntp_set_time_sync_notification_cb(on_time_sync);if(esp_sntp_get_sync_status()==SNTP_SYNC_STATUS_COMPLETED&&time(nullptr)>1700000000)time_synchronized.store(true);if(!esp_sntp_enabled()){esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);esp_sntp_setservername(0,"ntp.aliyun.com");esp_sntp_setservername(1,"ntp.tencent.com");esp_sntp_init();}event("runtime_started");try{need(self_test(),"self_test_failed");event("native_self_test_passed");}catch(const Error& ex){event(ex.what(),"",ex.code);vTaskDelete(nullptr);return;}for(;;){expire_transfer();Job job={};bool manual=xQueueReceive(jobs,&job,pdMS_TO_TICKS(15000))==pdTRUE;wifi_ap_record_t ap;if((esp_wifi_sta_get_ap_info(&ap)!=ESP_OK||!clock_ready())&&!(job.request[0]&&strcmp(job.operation,"schedule")==0)){if(manual){event("wifi_or_clock_unavailable");if(job.request[0])management_offline(job);if(job.all)event("batch_completed");}continue;}try{std::unique_lock<std::mutex> guard(execution,std::try_to_lock);need(guard.owns_lock(),"operation_busy");Json config=json(read_config());auto accounts=cJSON_GetObjectItem(config.get(),"accounts");if(manual){
    if(job.request[0]){process_management_job(job,config);}
    else if(job.all){
        std::set<std::string> attempted;
        cJSON *account;
        cJSON_ArrayForEach(account,accounts){
            std::string sid;
            try{
                sid=str(account,"student_id");
                if(!attempted.insert(sid).second){event("duplicate_account_skipped",sid);continue;}
                run_account(account,config,job.submit,true);
            }catch(const Error& ex){outcome_error(sid,ex);event(ex.what(),sid,ex.code,"",ex.school_message);}
             catch(const std::bad_alloc&){event("out_of_memory",sid);}
             catch(...){event("runtime_error",sid);}
            if(account->next)vTaskDelay(pdMS_TO_TICKS(25000));
        }
    }else{
        cJSON *account;bool found=false;
        cJSON_ArrayForEach(account,accounts)if(str(account,"student_id")==job.account){found=true;run_account(account,config,job.submit,true);break;}
        need(found,"account_not_found");
    }
}else if(cJSON_IsTrue(cJSON_GetObjectItem(config.get(),"enabled"))){
    time_t now=time(nullptr);struct tm local;localtime_r(&now,&local);int minute=local.tm_hour*60+local.tm_min;
    cJSON *account;cJSON_ArrayForEach(account,accounts){
        std::string sid=str(account,"student_id");
        if(!account_enabled(account)||minute<account_minute(account,config.get())||minute>=account_end(account,config.get()))continue;
        run_automatic(account,config);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}}catch(const Error& ex){if(manual&&job.account[0])outcome_error(job.account,ex);if(manual&&job.request[0])send_management(job,"done",false,ex.code,ex.what());event(ex.what(),"",ex.code,"",ex.school_message);}catch(const std::bad_alloc&){if(manual&&job.request[0])send_management(job,"done",false,0,"out_of_memory");event("out_of_memory");}catch(...){event("runtime_error");}if(manual&&job.all)event("batch_completed");}}
}
extern "C" void checkin_service_set_listener(checkin_service_listener listener,void *user){set_management_listener(listener,user);}
extern "C" bool checkin_service_handle_request(const char *request){return dispatch_management(request);}
extern "C" void checkin_service_start(void){if(jobs)return;auto status=nvs_flash_init_partition("checkin");if(status!=ESP_OK){ESP_LOGE(TAG,"Check-in partition unavailable; other tasks unaffected (%d)",int(status));return;}storage_ready=true;jobs=xQueueCreate(2,sizeof(Job));if(!jobs){ESP_LOGE(TAG,"Check-in queue allocation failed; other tasks continue");return;}BaseType_t a=xTaskCreate(worker,"checkin",16384,nullptr,3,nullptr);BaseType_t b=xTaskCreate(serial_task,"checkin_usb",6144,nullptr,2,nullptr);if(a!=pdPASS||b!=pdPASS)ESP_LOGE(TAG,"Check-in task allocation failed; other tasks continue");}
