// Host-only test harness: every OS, NVS, queue, school and crypto transport is fake.
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <deque>
#include <cmath>
#include <set>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>
#include "protocol.hpp"
#include "checkin_service.h"
using namespace wc;
namespace wc {
B bytes(const std::string& s){return B(s.begin(),s.end());}
B sha(const B& b){B out(32);size_t h=std::hash<std::string>{}(std::string(b.begin(),b.end()));for(size_t i=0;i<32;i++)out[i]=uint8_t(h>>((i%sizeof(h))*8));return out;}
Json json(const std::string& s){auto value=cJSON_Parse(s.c_str());if(!value)throw Error("json_invalid");return Json(value);}
std::string dump(const cJSON *v){char *raw=cJSON_PrintUnformatted(v);if(!raw)throw Error("json_failed");std::string out=raw;cJSON_free(raw);return out;}
std::string str(const cJSON *v,const char *key){auto field=cJSON_GetObjectItem(v,key);if(!cJSON_IsString(field))throw Error("field_invalid");return field->valuestring;}
}
using TaskHandle_t=void*;
using nvs_handle_t=int;
const int ESP_OK=0,ESP_ERR_NVS_NOT_FOUND=1,NVS_READONLY=0,NVS_READWRITE=1,MALLOC_CAP_8BIT=1,pdTRUE=1;
struct wifi_ap_record_t{};
std::mutex storage,execution;
std::atomic<bool> synchronized_clock{true};
bool storage_ready=true;
void *jobs=reinterpret_cast<void*>(1);
struct Job{char account[24];bool submit;bool all;char request[33];char operation[12];int index;bool plan_enabled;int plan_minute;};
std::map<std::string,std::string> fake_nvs;
std::map<int,std::string> namespaces;
int next_handle=1;
bool fail_commit=false,queue_full=false;
std::vector<Job> queued;
std::vector<std::string> messages,trace;
int fake_posts=0,refreshes=0;
std::deque<int> buffer_codes;
std::string config_text=R"({"enabled":false,"accounts":[{"student_id":"202300000001","schoolSession":"synthetic-private-session","wechat":{"openid":"synthetic-openid","access_token":"synthetic-private-access","refresh_token":"synthetic-private-refresh"},"location":{"latitude":30.67,"longitude":104.09}}]})";
TaskHandle_t xTaskGetCurrentTaskHandle(){return reinterpret_cast<void*>(1);}
int64_t esp_timer_get_time(){return 900000000LL;}
size_t esp_get_free_heap_size(){return 200000;}
size_t heap_caps_get_largest_free_block(int){return 120000;}
int esp_wifi_sta_get_ap_info(wifi_ap_record_t*){return ESP_OK;}
bool clock_ready(){return synchronized_clock.load();}
int nvs_open_from_partition(const char*,const char *ns,int,nvs_handle_t *handle){*handle=next_handle++;namespaces[*handle]=ns;return ESP_OK;}
void nvs_close(nvs_handle_t handle){namespaces.erase(handle);}
int nvs_get_str(nvs_handle_t handle,const char *key,char *out,size_t *n){auto found=fake_nvs.find(namespaces[handle]+"/"+key);if(found==fake_nvs.end())return ESP_ERR_NVS_NOT_FOUND;size_t required=found->second.size()+1;if(!out){*n=required;return ESP_OK;}if(*n<required)return 2;memcpy(out,found->second.c_str(),required);*n=required;return ESP_OK;}
int nvs_set_str(nvs_handle_t handle,const char *key,const char *value){fake_nvs[namespaces[handle]+"/"+key]=value;return ESP_OK;}
int nvs_commit(nvs_handle_t){return fail_commit?2:ESP_OK;}
int nvs_erase_key(nvs_handle_t handle,const char *key){fake_nvs.erase(namespaces[handle]+"/"+key);return ESP_OK;}
int mbedtls_base64_decode(unsigned char *out,size_t capacity,size_t *length,const unsigned char *input,size_t size){
 const std::string alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";unsigned bits=0,available=0;size_t count=0;
 for(size_t i=0;i<size;i++){if(input[i]=='=')break;auto position=alphabet.find(char(input[i]));if(position==std::string::npos)return -1;bits=(bits<<6)|unsigned(position);available+=6;if(available>=8){available-=8;if(count>=capacity)return -1;out[count++]=uint8_t(bits>>available);}}
 *length=count;return 0;
}
int xQueueSend(void*,const Job *job,int){if(queue_full)return 0;queued.push_back(*job);return pdTRUE;}
std::string read_config(){return config_text;}
void write_config(const std::string& value){trace.push_back("persist");config_text=value;}
std::string day(){return "2026-10-25";}
void management_event(const char*,const std::string&,int,const std::string&,const std::string&);
void begin_outcome(const std::string&);
void event(const char *state,const std::string& sid="",int code=0,const std::string& record="",const std::string& message=""){management_event(state,sid,code,record,message);}
Json school(const char*,const std::string&,const std::string&){return json(R"({"data":{"recordStatusCode":"PENDING"}})");}
std::string status(const Json& v){return str(cJSON_GetObjectItem(v.get(),"data"),"recordStatusCode");}
void run_account(cJSON *account,Json&,bool submit,bool,bool automatic_attempt=false){(void)automatic_attempt;auto sid=str(account,"student_id");begin_outcome(sid);event("record_before",sid,0,"PENDING");if(submit){++fake_posts;event("request_rejected",sid,4006,"","Outside the school window");event("record_after",sid,0,"PENDING");event("submission_rejected",sid,4006);}else event("authorization_verified",sid);}
#include "management.inc"
#include "automation.inc"
void refresh(cJSON*,bool force=false){assert(force);++refreshes;trace.push_back("refresh");}
std::string get_buffer(cJSON*){trace.push_back("get");assert(!buffer_codes.empty());int code=buffer_codes.front();buffer_codes.pop_front();if(code)throw Error("oauth_rejected",code,"safe public diagnostic");return "synthetic-buffer";}
#include "get_buffer_refresh.inc"
void collect(const char *message,void*){messages.emplace_back(message);}
Json last_message(){assert(!messages.empty());return json(messages.back());}
void expect(bool yes,const char *label){if(!yes){std::cerr<<"FAIL "<<label<<"\n";std::exit(1);}}

std::string b64(const std::string& raw){const char *alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";std::string out;unsigned bits=0,available=0;for(unsigned char byte:raw){bits=(bits<<8)|byte;available+=8;while(available>=6){available-=6;out.push_back(alphabet[(bits>>available)&63]);}}if(available)out.push_back(alphabet[(bits<<(6-available))&63]);while(out.size()%4)out.push_back('=');return out;}
std::string hash_hex(const std::string& raw){B value=sha(bytes(raw));char text[65];for(size_t i=0;i<32;i++)snprintf(text+i*2,3,"%02x",value[i]);return text;}
bool dispatch(const std::string& raw){expect(raw.size()+3<=180,"CI command fits original authenticated packet budget");return dispatch_management(raw.c_str());}
void upload_fixture(const std::string& tag,const std::string& package,const std::string& sid){
 std::string begin="{\"id\":\"begin0001\",\"op\":\"put_begin\",\"t\":\""+tag+"\",\"len\":"+std::to_string(package.size())+",\"a\":-1,\"sid\":\""+sid+"\"}";expect(dispatch(begin),"begin fixture upload");
 for(size_t n=0,offset=0;offset<package.size();++n,offset+=64){std::string chunk="{\"id\":\"piece0001\",\"op\":\"put_chunk\",\"t\":\""+tag+"\",\"n\":"+std::to_string(n)+",\"b\":\""+b64(package.substr(offset,64))+"\"}";expect(dispatch(chunk),"chunk fixture upload");if(n==0)expect(dispatch(chunk),"identical repeated chunk is idempotent");}
}
int main(){
 set_management_listener(collect,nullptr);
 expect(dispatch_management(R"({"id":"status0001","op":"status"})"),"status dispatch");auto response=last_message();expect(str(response.get(),"phase")=="done"&&cJSON_IsFalse(cJSON_GetObjectItem(response.get(),"enabled")),"status does not enable plan");expect(cJSON_GetObjectItem(response.get(),"hour")->valueint==21&&cJSON_GetObjectItem(response.get(),"minute")->valueint==10,"default 21:10");
 synchronized_clock=false;dispatch_management(R"({"id":"status0002","op":"status"})");response=last_message();expect(cJSON_IsFalse(cJSON_GetObjectItem(response.get(),"timeSynced")),"boot clock not trusted");synchronized_clock=true;
 dispatch_management(R"({"id":"listing001","op":"list","a":0})");expect(messages.back().find("synthetic-private")==std::string::npos&&messages.back().find("access_token")==std::string::npos,"list excludes all credentials");
 expect(dispatch_management(R"({"id":"submit0001","op":"submit","a":0,"sid":"202300000001"})"),"submit queued");expect(queued.size()==1&&fake_posts==0,"enqueue does not execute attendance");
 expect(!dispatch_management(R"({"id":"submit0001","op":"submit","a":0,"sid":"202300000001"})"),"duplicate rejected");expect(queued.size()==1&&str(last_message().get(),"state")=="duplicate_request","duplicate cannot enqueue again");
 auto config=json(config_text);process_management_job(queued[0],config);response=last_message();expect(fake_posts==1&&cJSON_GetObjectItem(response.get(),"code")->valueint==4006&&!cJSON_IsTrue(cJSON_GetObjectItem(response.get(),"ok")),"one backend rejection remains rejected");
 auto result=read_outcome("202300000001");expect(str(result.get(),"before")=="PENDING"&&str(result.get(),"after")=="PENDING"&&cJSON_GetObjectItem(result.get(),"code")->valueint==4006,"paired last result preserved");
 size_t before=queued.size();fail_commit=true;expect(!dispatch_management(R"({"id":"submit0002","op":"submit","a":0,"sid":"202300000001"})"),"failed durable claim rejects");expect(queued.size()==before,"no enqueue before durable commit");fail_commit=false;
 expect(dispatch_management(R"({"id":"schedule01","op":"schedule","enabled":true,"hour":22,"minute":7})"),"schedule queued");expect(!cJSON_IsTrue(cJSON_GetObjectItem(config.get(),"enabled")),"schedule waits worker");process_management_job(queued.back(),config);expect(schedule_minute(config.get())==1327&&cJSON_IsTrue(cJSON_GetObjectItem(config.get(),"enabled")),"plan persisted in fake NVS only");
 for(const auto& text:messages)expect(text.size()<=450,"all callback payloads fit packet budget");
 auto safe=sanitized_message("Safe session-secret value ABCDEFGHIJKLMNOPQRSTUVWXYZ token", "session-secret", "");expect(safe.find("session-secret")==std::string::npos&&safe.find("ABCDEFGHIJKLMNOPQRSTUVWXYZ")==std::string::npos,"messages remove exact secrets and long tokens");
 expect(bounded_utf8(u8"中文位置",5)==u8"中","UTF8 limit does not cut codepoint");

 dispatch(R"({"id":"listing002","op":"list","a":0})");expect(str(last_message().get(),"state")=="account","account plus last outcome fits response budget");
 const std::string package=R"({"student_id":"202300000002","schoolSession":"synthetic-private-new-session","wechat":{"openid":"synthetic-openid2","access_token":"synthetic-private-new-access","refresh_token":"synthetic-private-new-refresh","expires_at":2000000000},"location":{"latitude":30.68,"longitude":104.10,"coordinate_system":"gcj02"},"enabled":true,"scheduleMinute":1300})";
 upload_fixture("transfer0001",package,"202300000002");
 std::string commit="{\"id\":\"commit0001\",\"op\":\"put_commit\",\"t\":\"transfer0001\",\"sha256\":\""+hash_hex(package)+"\"}";
 synchronized_clock=false;expect(dispatch(commit),"local account commit works before SNTP");synchronized_clock=true;auto stored=json(config_text);auto saved=resolve_account(stored.get(),1,"202300000002");expect(!account_enabled(saved),"new account never auto-enabled by imported package");expect(str(saved,"schoolSession")=="synthetic-private-new-session"&&str(cJSON_GetObjectItem(saved,"wechat"),"access_token")=="synthetic-private-new-access","whole paired bundle committed without mixing");expect(upload.data.empty(),"upload RAM cleared after commit");
 expect(!dispatch(commit)&&str(last_message().get(),"state")=="duplicate_request","commit replay cannot mutate twice");
 synchronized_clock=false;
 expect(dispatch(R"({"id":"editing001","op":"edit","a":1,"sid":"202300000002","enabled":true,"hour":22,"minute":31,"lat":30.69,"lng":104.11})"),"local metadata edit works before SNTP");stored=json(config_text);saved=resolve_account(stored.get(),1,"202300000002");expect(account_enabled(saved)&&account_minute(saved,stored.get())==1351,"per-account enable and schedule updated");expect(str(cJSON_GetObjectItem(saved,"wechat"),"refresh_token")=="synthetic-private-new-refresh","metadata edit never mixes credentials");
 expect(!dispatch(R"({"id":"deleting01","op":"delete","a":1,"sid":"202300000001"})"),"stale account index protected by sid");stored=json(config_text);expect(cJSON_GetArraySize(cJSON_GetObjectItem(stored.get(),"accounts"))==2,"failed delete preserves config");
 expect(dispatch(R"({"id":"clocktest1","op":"submit","a":0,"sid":"202300000001"})"),"clock test request queued");int previous_posts=fake_posts;auto clock_config=json(config_text);process_management_job(queued.back(),clock_config);expect(fake_posts==previous_posts&&str(last_message().get(),"state")=="clock_unsynchronized","submit cannot execute before SNTP");
 expect(dispatch(R"({"id":"deleting02","op":"delete","a":1,"sid":"202300000002"})"),"local delete works before SNTP");stored=json(config_text);expect(cJSON_GetArraySize(cJSON_GetObjectItem(stored.get(),"accounts"))==1,"delete removes one account only");
 synchronized_clock=true;
 upload_fixture("transfer0002",package,"202300000002");std::string wrong="{\"id\":\"commit0002\",\"op\":\"put_commit\",\"t\":\"transfer0002\",\"sha256\":\""+std::string(64,'0')+"\"}";expect(!dispatch(wrong)&&upload.data.empty(),"hash mismatch clears sensitive transfer without saving");stored=json(config_text);expect(cJSON_GetArraySize(cJSON_GetObjectItem(stored.get(),"accounts"))==1,"bad package cannot partially replace config");
 expect(dispatch(R"({"id":"begin0003","op":"put_begin","t":"transfer0003","len":64,"a":-1,"sid":"202300000002"})"),"timeout fixture begin");upload.started=esp_timer_get_time()-121000000LL;expire_transfer();expect(upload.data.empty()&&upload.tag.empty(),"incomplete sensitive transfer expires after 120 seconds");
 for(const auto& message:messages){expect(message.find("synthetic-private")==std::string::npos,"no plaintext credential in any callback");expect(message.size()<=450,"CRUD responses fit packet budget");}
 auto account=cJSON_GetArrayItem(cJSON_GetObjectItem(config.get(),"accounts"),0);
 trace.clear();refreshes=0;buffer_codes={-101,0};expect(get_buffer_refresh(account,config)=="synthetic-buffer","mid-TTL buffer recovery");expect(refreshes==1&&trace==std::vector<std::string>({"get","refresh","persist","get"}),"rotate persisted before single buffer retry");
 trace.clear();refreshes=0;buffer_codes={-109};try{get_buffer_refresh(account,config);expect(false,"-109 must fail");}catch(const Error& error){expect(error.code==-109&&refreshes==0,"other errors never trigger refresh");}
 trace.clear();refreshes=0;buffer_codes={-101,-101};try{get_buffer_refresh(account,config);expect(false,"second rejection must fail");}catch(const Error& error){expect(error.code==-101&&refreshes==1&&buffer_codes.empty(),"no refresh loop");}
 auto safe_failure=json(R"({"state":"submission_rejected","code":4006,"after":"PENDING","msg":"当前不在打卡时间段内"})");
 expect(automatic_retryable(safe_failure.get()),"explicit outside-window rejection may retry with fresh ticket");
 auto uncertain=json(R"({"state":"result_unknown_no_retry","code":0,"after":"PENDING","msg":""})");expect(!automatic_retryable(uncertain.get()),"unknown write cannot retry");
 auto accepted=json(R"({"state":"accepted_pending","code":0,"after":"PENDING","msg":""})");expect(!automatic_retryable(accepted.get()),"accepted but unconfirmed write cannot retry");
 auto auth_bad=json(R"({"state":"oauth_rejected","code":-109,"after":"","msg":"RC_PARAMS_INVALID"})");expect(!automatic_retryable(auth_bad.get()),"invalid authorization stops daily plan");
 AutoState attempt{day(),time(nullptr)+60,true};save_auto("202300000001",attempt);auto reboot=read_auto("202300000001");
 expect(!automatic_due(reboot,day(),time(nullptr)+3600),"power loss preserves uncertain-attempt stop");
 expect(automatic_due(reboot,"2026-10-26",time(nullptr)),"next business day can run again");
 attempt.stopped=false;save_auto("202300000001",attempt);expect(!automatic_due(read_auto("202300000001"),day(),time(nullptr)),"60-second retry spacing persists across restart");
 expect(automatic_due(read_auto("202300000001"),day(),time(nullptr)+61),"safe retry becomes due after interval");
 auto plan=json(R"({"scheduleMinute":1270,"scheduleEndMinute":1275})");expect(account_end(plan.get(),config.get())==1275,"per-account end window read");
 try{auto bad=json(R"({"scheduleMinute":1270,"scheduleEndMinute":1269})");account_end(bad.get(),config.get());expect(false,"bad end accepted");}catch(const Error&){}
 std::cout<<"PASS: host management invariants; all storage, crypto, school, Wi-Fi and queues mocked; no network/device writes.\n";
}
