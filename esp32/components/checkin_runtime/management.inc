/* Included inside the service namespace; contains no transport or account secrets. */
std::mutex management_lock;
checkin_service_listener management_listener=nullptr;
void *management_user=nullptr;
Job active_management={};
std::atomic<TaskHandle_t> management_task{nullptr};
struct Outcome {std::string state,before,after,message;int code=0;bool accepted=false;time_t at=0;};
std::mutex outcome_lock;
std::string outcome_account;
Outcome current_outcome;

std::string bounded_utf8(std::string text,size_t limit){
    if(text.size()<=limit)return text;
    size_t end=limit;while(end&&((unsigned char)text[end]&0xc0)==0x80)--end;
    text.resize(end);return text;
}
std::string sanitized_message(std::string text,const std::string& session,const std::string& ticket){
    for(const auto& secret:{session,ticket})if(!secret.empty()){size_t at;while((at=text.find(secret))!=std::string::npos)text.replace(at,secret.size(),"[redacted]");}
    std::string safe;size_t at=0;
    while(at<text.size()){
        unsigned char ch=text[at];
        bool token=(ch>='a'&&ch<='z')||(ch>='A'&&ch<='Z')||(ch>='0'&&ch<='9')||strchr("_./+=:-",ch);
        if(token){size_t end=at+1;while(end<text.size()){unsigned char c=text[end];if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||strchr("_./+=:-",c)))break;++end;}safe+=end-at>=24?"[redacted]":text.substr(at,end-at);at=end;}
        else{if(ch>=32&&ch!=127)safe.push_back(ch);++at;}
    }
    return bounded_utf8(safe,96);
}
std::string account_key(const std::string& sid){B digest=sha(bytes(sid));char key[16];snprintf(key,sizeof(key),"a%02x%02x%02x%02x",digest[0],digest[1],digest[2],digest[3]);return key;}
Json outcome_json(const Outcome& result){Json out(cJSON_CreateObject());cJSON_AddStringToObject(out.get(),"state",result.state.c_str());cJSON_AddNumberToObject(out.get(),"code",result.code);cJSON_AddStringToObject(out.get(),"msg",result.message.c_str());cJSON_AddNumberToObject(out.get(),"time",result.at);cJSON_AddStringToObject(out.get(),"before",result.before.c_str());cJSON_AddStringToObject(out.get(),"after",result.after.c_str());cJSON_AddBoolToObject(out.get(),"accepted",result.accepted);return out;}
void save_outcome(const std::string& sid){
    Outcome result;{std::lock_guard<std::mutex> lock(outcome_lock);if(outcome_account!=sid)return;result=current_outcome;}
    Json value=outcome_json(result);std::string raw=dump(value.get());
    std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;if(nvs_open_from_partition("checkin","results",NVS_READWRITE,&handle)!=ESP_OK)return;
    if(nvs_set_str(handle,account_key(sid).c_str(),raw.c_str())==ESP_OK)nvs_commit(handle);nvs_close(handle);
}
Json read_outcome(const std::string& sid){
    {std::lock_guard<std::mutex> lock(outcome_lock);if(outcome_account==sid&&!current_outcome.state.empty())return outcome_json(current_outcome);}
    std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;if(nvs_open_from_partition("checkin","results",NVS_READONLY,&handle)!=ESP_OK)return Json(cJSON_CreateObject());
    size_t n=0;std::string raw;auto key=account_key(sid);auto result=nvs_get_str(handle,key.c_str(),nullptr,&n);
    if(result==ESP_OK&&n>0&&n<1024){raw.resize(n);result=nvs_get_str(handle,key.c_str(),raw.data(),&n);}nvs_close(handle);
    if(result!=ESP_OK||raw.empty())return Json(cJSON_CreateObject());raw.resize(strlen(raw.c_str()));return json(raw);
}
void begin_outcome(const std::string& sid){std::lock_guard<std::mutex> lock(outcome_lock);outcome_account=sid;current_outcome=Outcome{};current_outcome.at=time(nullptr);}
void outcome_error(const std::string& sid,const Error& error){
    {std::lock_guard<std::mutex> lock(outcome_lock);if(outcome_account!=sid){outcome_account=sid;current_outcome=Outcome{};}current_outcome.state=error.what();current_outcome.code=error.code;current_outcome.message=error.school_message;current_outcome.at=time(nullptr);}
    save_outcome(sid);
}
bool terminal_outcome(const std::string& state){return state=="authorization_verified"||state=="already_recorded"||state=="checkin_confirmed"||state=="existing_record_only"||state=="submission_rejected"||state=="accepted_pending"||state=="result_unknown_no_retry"||state=="query_complete";}
void set_management_listener(checkin_service_listener listener,void *user){std::lock_guard<std::mutex> lock(management_lock);management_listener=listener;management_user=user;}
void send_management(const Job& job,const char *phase,bool ok,int code,const std::string& state,const cJSON *extra=nullptr){
    Json response(cJSON_CreateObject());cJSON_AddStringToObject(response.get(),"id",job.request);cJSON_AddStringToObject(response.get(),"op",job.operation);cJSON_AddStringToObject(response.get(),"phase",phase);cJSON_AddBoolToObject(response.get(),"ok",ok);cJSON_AddNumberToObject(response.get(),"code",code);cJSON_AddStringToObject(response.get(),"state",state.c_str());
    if(extra){const cJSON *item; cJSON_ArrayForEach(item,extra)if(item->string&&!cJSON_GetObjectItem(response.get(),item->string))cJSON_AddItemToObject(response.get(),item->string,cJSON_Duplicate(item,true));}
    std::string raw=dump(response.get());
    if(raw.size()>450){cJSON_DeleteItemFromObject(response.get(),"msg");auto last=cJSON_GetObjectItem(response.get(),"last");if(last)cJSON_DeleteItemFromObject(last,"msg");raw=dump(response.get());}
    if(raw.size()>450){cJSON_Delete(response.release());response.reset(cJSON_CreateObject());cJSON_AddStringToObject(response.get(),"id",job.request);cJSON_AddStringToObject(response.get(),"op",job.operation);cJSON_AddStringToObject(response.get(),"phase","done");cJSON_AddBoolToObject(response.get(),"ok",false);cJSON_AddStringToObject(response.get(),"state","response_too_large");raw=dump(response.get());}
    checkin_service_listener callback;void *user;{std::lock_guard<std::mutex> lock(management_lock);callback=management_listener;user=management_user;}if(callback)callback(raw.c_str(),user);
}
void management_event(const char *state,const std::string& account,int code,const std::string& record,const std::string& message){
    bool save=false;
    if(!account.empty()){
        std::lock_guard<std::mutex> lock(outcome_lock);
        if(outcome_account==account){current_outcome.state=state;current_outcome.at=time(nullptr);if(std::string(state)=="record_before")current_outcome.before=record;if(std::string(state)=="record_after")current_outcome.after=record;if(std::string(state)=="request_accepted"){current_outcome.accepted=true;current_outcome.code=0;}if(std::string(state)=="credential_recovered"){current_outcome.code=0;current_outcome.message.clear();}if(code!=0)current_outcome.code=code;if(!message.empty())current_outcome.message=message;save=terminal_outcome(state);}
    }
    if(save)save_outcome(account);
    if(management_task!=xTaskGetCurrentTaskHandle()||!active_management.request[0])return;
    Json extra(cJSON_CreateObject());if(!account.empty())cJSON_AddStringToObject(extra.get(),"sid",account.c_str());if(!record.empty())cJSON_AddStringToObject(extra.get(),"recordStatusCode",record.c_str());if(!message.empty())cJSON_AddStringToObject(extra.get(),"msg",message.c_str());
    send_management(active_management,"progress",code==0,code,state,extra.get());
}
int schedule_minute(const cJSON *config){auto value=cJSON_GetObjectItem(config,"scheduleMinute");if(cJSON_IsNumber(value)&&value->valuedouble==value->valueint&&value->valueint>=0&&value->valueint<1440)return value->valueint;return 1270;}
bool valid_request_id(const std::string& id){if(id.size()<8||id.size()>32)return false;for(unsigned char c:id)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')))return false;return true;}
void claim_management_request(const std::string& id){
    B digest=sha(bytes(id));char key[16];snprintf(key,sizeof(key),"r%02x%02x%02x%02x%02x%02x%02x",digest[0],digest[1],digest[2],digest[3],digest[4],digest[5],digest[6]);
    std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;need(nvs_open_from_partition("checkin","requests",NVS_READWRITE,&handle)==ESP_OK,"request_store_unavailable");
    char old[40]={};size_t n=sizeof(old);auto found=nvs_get_str(handle,key,old,&n);if(found!=ESP_ERR_NVS_NOT_FOUND){nvs_close(handle);throw Error(found==ESP_OK&&id==old?"duplicate_request":"request_id_collision");}
    auto result=nvs_set_str(handle,key,id.c_str());if(result==ESP_OK)result=nvs_commit(handle);nvs_close(handle);need(result==ESP_OK,"request_store_failed");
}
void management_status(const Job& job,const cJSON *config){
    wifi_ap_record_t ap;Json extra(cJSON_CreateObject());int minute=schedule_minute(config);std::unique_lock<std::mutex> execution_probe(execution,std::try_to_lock);
    cJSON_AddNumberToObject(extra.get(),"v",1);cJSON_AddNumberToObject(extra.get(),"time",time(nullptr));cJSON_AddBoolToObject(extra.get(),"timeSynced",clock_ready());cJSON_AddBoolToObject(extra.get(),"wifi",esp_wifi_sta_get_ap_info(&ap)==ESP_OK);cJSON_AddNumberToObject(extra.get(),"freeHeap",esp_get_free_heap_size());cJSON_AddNumberToObject(extra.get(),"largestBlock",heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));cJSON_AddBoolToObject(extra.get(),"enabled",cJSON_IsTrue(cJSON_GetObjectItem(config,"enabled")));cJSON_AddNumberToObject(extra.get(),"hour",minute/60);cJSON_AddNumberToObject(extra.get(),"minute",minute%60);cJSON_AddNumberToObject(extra.get(),"count",cJSON_GetArraySize(cJSON_GetObjectItem(config,"accounts")));cJSON_AddBoolToObject(extra.get(),"busy",!execution_probe.owns_lock());send_management(job,"done",true,0,"status",extra.get());
}
int plan_fields(const cJSON*,const cJSON*);
cJSON *resolve_account(cJSON*,int,const std::string& expected="");
bool account_enabled(const cJSON*);
int account_minute(const cJSON*,const cJSON*);
void expire_transfer();
void handle_transfer(const Job&,const cJSON*);
void mutate_account(const Job&,const cJSON*);
bool dispatch_management(const char *request){
    Job job={};
    try{
        need(request&&strlen(request)<=180,"request_size");Json value=json(request);std::string id=str(value.get(),"id"),op=str(value.get(),"op");need(valid_request_id(id),"request_id_invalid");
        need(op=="status"||op=="list"||op=="query"||op=="refresh"||op=="submit"||op=="schedule"||op=="edit"||op=="delete"||op=="put_begin"||op=="put_chunk"||op=="put_commit","unknown_command");strcpy(job.request,id.c_str());strcpy(job.operation,op.c_str());need(storage_ready&&jobs,"runtime_unavailable");
        expire_transfer();
        if(op=="put_begin"||op=="put_chunk"||op=="put_commit"){handle_transfer(job,value.get());return true;}
        if(op=="list"||op=="query"||op=="refresh"||op=="submit"||op=="edit"||op=="delete"){
            auto index=cJSON_GetObjectItem(value.get(),"a");need(cJSON_IsNumber(index)&&index->valuedouble==index->valueint&&index->valueint>=0&&index->valueint<4,"account_index_invalid");job.index=index->valueint;
            if(op!="list"){std::string sid=str(value.get(),"sid");need(sid.size()<sizeof(job.account),"account_length");strcpy(job.account,sid.c_str());}
        }
        if(op=="schedule"){
            auto enabled=cJSON_GetObjectItem(value.get(),"enabled"),hour=cJSON_GetObjectItem(value.get(),"hour"),minute=cJSON_GetObjectItem(value.get(),"minute");need(cJSON_IsBool(enabled),"schedule_invalid");job.plan_enabled=cJSON_IsTrue(enabled);job.plan_minute=plan_fields(hour,minute);
        }
        if(op=="status"||op=="list"){
            Json config=json(read_config());if(op=="status"){management_status(job,config.get());return true;}
            auto account=resolve_account(config.get(),job.index);auto point=cJSON_GetObjectItem(account,"location");std::string sid=str(account,"student_id");Json extra(cJSON_CreateObject());cJSON_AddNumberToObject(extra.get(),"a",job.index);cJSON_AddStringToObject(extra.get(),"sid",sid.c_str());cJSON_AddNumberToObject(extra.get(),"lat",cJSON_GetObjectItem(point,"latitude")->valuedouble);cJSON_AddNumberToObject(extra.get(),"lng",cJSON_GetObjectItem(point,"longitude")->valuedouble);cJSON_AddBoolToObject(extra.get(),"autoEnabled",account_enabled(account));int minute=account_minute(account,config.get());cJSON_AddNumberToObject(extra.get(),"hour",minute/60);cJSON_AddNumberToObject(extra.get(),"minute",minute%60);Json last=read_outcome(sid);cJSON_AddItemToObject(extra.get(),"last",last.release());send_management(job,"done",true,0,"account",extra.get());return true;
        }
        if(op=="edit"||op=="delete"){
            std::unique_lock<std::mutex> guard(execution,std::try_to_lock);need(guard.owns_lock(),"operation_busy");mutate_account(job,value.get());return true;
        }
        // Refresh rotates credentials too. Read-only polling does not wear Flash.
        if(op=="refresh"||op=="submit"||op=="schedule")claim_management_request(id);
        need(xQueueSend(jobs,&job,0)==pdTRUE,"job_busy");send_management(job,"accepted",true,0,"queued");return true;
    }catch(const Error& error){send_management(job,"done",false,error.code,error.what());return false;}
     catch(...){send_management(job,"done",false,0,"management_error");return false;}
}

void management_offline(const Job& job){send_management(job,"done",false,0,"wifi_or_clock_unavailable");}
void process_management_job(const Job& job,Json& config){
    active_management=job;management_task=xTaskGetCurrentTaskHandle();
    try{
        std::string op=job.operation;
        if(op!="schedule")need(clock_ready(),"clock_unsynchronized");
        if(op=="schedule"){
            auto enabled=cJSON_CreateBool(job.plan_enabled);if(cJSON_GetObjectItem(config.get(),"enabled"))cJSON_ReplaceItemInObject(config.get(),"enabled",enabled);else cJSON_AddItemToObject(config.get(),"enabled",enabled);
            auto minute=cJSON_CreateNumber(job.plan_minute);if(cJSON_GetObjectItem(config.get(),"scheduleMinute"))cJSON_ReplaceItemInObject(config.get(),"scheduleMinute",minute);else cJSON_AddItemToObject(config.get(),"scheduleMinute",minute);write_config(dump(config.get()));
            Json extra(cJSON_CreateObject());cJSON_AddBoolToObject(extra.get(),"enabled",job.plan_enabled);cJSON_AddNumberToObject(extra.get(),"hour",job.plan_minute/60);cJSON_AddNumberToObject(extra.get(),"minute",job.plan_minute%60);send_management(job,"done",true,0,"schedule_saved",extra.get());
        }else{
            auto account=resolve_account(config.get(),job.index,job.account);std::string sid=str(account,"student_id");
            try{
                if(op=="query"){
                    begin_outcome(sid);Json record=school("GET","/daily-checkin/api/student-checkin-record/today",str(account,"schoolSession"));std::string state=status(record);event("record_before",sid,0,state);event("record_after",sid,0,state);event("query_complete",sid);
                }else run_account(account,config,op=="submit",true);
            }catch(const Error& error){outcome_error(sid,error);throw;}
            Json last=read_outcome(sid);auto result_code=cJSON_GetObjectItem(last.get(),"code");int code=cJSON_IsNumber(result_code)?result_code->valueint:0;std::string state=str(last.get(),"state");Json extra(cJSON_CreateObject());cJSON_AddNumberToObject(extra.get(),"a",job.index);cJSON_AddStringToObject(extra.get(),"sid",sid.c_str());cJSON_AddStringToObject(extra.get(),"businessDate",day().c_str());for(auto key:{"msg","before","after","accepted"}){auto field=cJSON_GetObjectItem(last.get(),key);if(field)cJSON_AddItemToObject(extra.get(),key,cJSON_Duplicate(field,true));}auto after=cJSON_GetObjectItem(last.get(),"after");if(cJSON_IsString(after))cJSON_AddStringToObject(extra.get(),"recordStatusCode",after->valuestring);send_management(job,"done",op=="submit"?state=="checkin_confirmed":code==0,code,state,extra.get());
        }
    }catch(const Error& error){Json extra(cJSON_CreateObject());cJSON_AddNumberToObject(extra.get(),"a",job.index);if(!error.school_message.empty())cJSON_AddStringToObject(extra.get(),"msg",error.school_message.c_str());send_management(job,"done",false,error.code,error.what(),extra.get());}
     catch(const std::bad_alloc&){send_management(job,"done",false,0,"out_of_memory");}
     catch(...){send_management(job,"done",false,0,"management_error");}
    management_task=nullptr;active_management=Job{};
}
void secure_clear(B& value){volatile uint8_t *data=value.data();for(size_t i=0;i<value.size();++i)data[i]=0;B empty;value.swap(empty);}
void wipe_json(cJSON *value){if(!value)return;if(value->valuestring){volatile char *s=value->valuestring;size_t length=strlen(value->valuestring);for(size_t i=0;i<length;++i)s[i]=0;}for(auto item=value->child;item;item=item->next)wipe_json(item);}
struct SensitiveJson{Json value;explicit SensitiveJson(cJSON *raw):value(raw){}~SensitiveJson(){wipe_json(value.get());}};
struct Upload{std::string tag,sid;int index=-1;size_t length=0;int64_t started=0;B data,received;};
std::mutex upload_lock;
Upload upload;
void clear_upload(){secure_clear(upload.data);upload.received.clear();upload.tag.clear();upload.sid.clear();upload.length=0;upload.index=-1;upload.started=0;}
void expire_transfer(){std::lock_guard<std::mutex> lock(upload_lock);if(!upload.tag.empty()&&esp_timer_get_time()-upload.started>=120000000LL)clear_upload();}
int plan_fields(const cJSON *hour,const cJSON *minute){need(cJSON_IsNumber(hour)&&cJSON_IsNumber(minute)&&hour->valuedouble==hour->valueint&&minute->valuedouble==minute->valueint&&hour->valueint>=0&&hour->valueint<24&&minute->valueint>=0&&minute->valueint<60,"schedule_invalid");return hour->valueint*60+minute->valueint;}
bool account_enabled(const cJSON *account){auto enabled=cJSON_GetObjectItem(account,"enabled");return !enabled||cJSON_IsTrue(enabled);}
int account_minute(const cJSON *account,const cJSON *config){auto minute=cJSON_GetObjectItem(account,"scheduleMinute");if(!minute)return schedule_minute(config);need(cJSON_IsNumber(minute)&&minute->valuedouble==minute->valueint&&minute->valueint>=0&&minute->valueint<1440,"schedule_invalid");return minute->valueint;}
cJSON *resolve_account(cJSON *config,int index,const std::string& expected){auto account=cJSON_GetArrayItem(cJSON_GetObjectItem(config,"accounts"),index);need(account,"account_not_found");if(!expected.empty())need(str(account,"student_id")==expected,"account_changed");return account;}
void set_field(cJSON *object,const char *key,cJSON *value){if(cJSON_GetObjectItem(object,key))cJSON_ReplaceItemInObject(object,key,value);else cJSON_AddItemToObject(object,key,value);}
void require_fields(const cJSON *object,const std::set<std::string>& allowed){need(cJSON_IsObject(object),"account_package_invalid");const cJSON *item;cJSON_ArrayForEach(item,object)need(item->string&&allowed.count(item->string),"account_field_invalid");}
std::string request_key(const std::string& id){B digest=sha(bytes(id));char key[16];snprintf(key,sizeof(key),"r%02x%02x%02x%02x%02x%02x%02x",digest[0],digest[1],digest[2],digest[3],digest[4],digest[5],digest[6]);return key;}
bool request_recorded(const std::string& id){std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;if(nvs_open_from_partition("checkin","requests",NVS_READONLY,&handle)!=ESP_OK)return false;char previous[40]={};size_t n=sizeof(previous);auto result=nvs_get_str(handle,request_key(id).c_str(),previous,&n);nvs_close(handle);return result==ESP_OK&&id==previous;}
void write_config_sensitive(const cJSON *config){std::string raw=dump(config);try{write_config(raw);}catch(...){volatile char *p=raw.data();for(size_t i=0;i<raw.size();++i)p[i]=0;throw;}volatile char *p=raw.data();for(size_t i=0;i<raw.size();++i)p[i]=0;}
void check_location(double lat,double lng){need(std::isfinite(lat)&&std::isfinite(lng)&&fabs(lat)<=90&&fabs(lng)<=180,"location_invalid");}
void validate_package(cJSON *account,const std::string& sid){
    require_fields(account,{"student_id","schoolSession","wechat","location","enabled","scheduleMinute"});need(str(account,"student_id")==sid,"account_changed");need(sid.size()>=8&&sid.size()<=20&&sid.find_first_not_of("0123456789")==std::string::npos,"student_id");auto session=str(account,"schoolSession");need(!session.empty()&&session.size()<1024&&session.find_first_of("\r\n;\"\\")==std::string::npos,"session_invalid");
    auto credentials=cJSON_GetObjectItem(account,"wechat");require_fields(credentials,{"openid","access_token","refresh_token","expires_at"});for(auto key:{"openid","access_token","refresh_token"}){auto field=str(credentials,key);need(!field.empty()&&field.size()<2048&&field.find_first_of("\r\n;\"\\")==std::string::npos,"credential_invalid");}auto expires=cJSON_GetObjectItem(credentials,"expires_at");need(cJSON_IsNumber(expires)&&std::isfinite(expires->valuedouble)&&expires->valuedouble>0,"credential_expiry");
    auto point=cJSON_GetObjectItem(account,"location");require_fields(point,{"latitude","longitude","coordinate_system"});need(str(point,"coordinate_system")=="gcj02","coordinate_system");auto latitude=cJSON_GetObjectItem(point,"latitude"),longitude=cJSON_GetObjectItem(point,"longitude");need(cJSON_IsNumber(latitude)&&cJSON_IsNumber(longitude),"location_invalid");check_location(latitude->valuedouble,longitude->valuedouble);
    auto enabled=cJSON_GetObjectItem(account,"enabled");need(!enabled||cJSON_IsBool(enabled),"enabled_invalid");auto minute=cJSON_GetObjectItem(account,"scheduleMinute");need(!minute||(cJSON_IsNumber(minute)&&minute->valuedouble==minute->valueint&&minute->valueint>=0&&minute->valueint<1440),"schedule_invalid");
}
void mutate_account(const Job& job,const cJSON *request){
    need(!request_recorded(job.request),"duplicate_request");Json config=json(read_config());auto account=resolve_account(config.get(),job.index,job.account);std::string sid=str(account,"student_id");
    if(std::string(job.operation)=="delete"){
        require_fields(request,{"id","op","a","sid"});claim_management_request(job.request);cJSON_DeleteItemFromArray(cJSON_GetObjectItem(config.get(),"accounts"),job.index);write_config_sensitive(config.get());
        {std::lock_guard<std::mutex> lock(outcome_lock);if(outcome_account==sid){current_outcome=Outcome{};outcome_account.clear();}}
        {std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;if(nvs_open_from_partition("checkin","results",NVS_READWRITE,&handle)==ESP_OK){nvs_erase_key(handle,account_key(sid).c_str());nvs_commit(handle);nvs_close(handle);}}
        {std::lock_guard<std::mutex> lock(upload_lock);if(upload.sid==sid)clear_upload();}
        Json extra(cJSON_CreateObject());cJSON_AddStringToObject(extra.get(),"sid",sid.c_str());send_management(job,"done",true,0,"account_deleted",extra.get());return;
    }
    require_fields(request,{"id","op","a","sid","enabled","hour","minute","lat","lng"});
    bool changed=false;auto enabled=cJSON_GetObjectItem(request,"enabled");if(enabled){need(cJSON_IsBool(enabled),"enabled_invalid");set_field(account,"enabled",cJSON_CreateBool(cJSON_IsTrue(enabled)));changed=true;}
    auto hour=cJSON_GetObjectItem(request,"hour"),minute=cJSON_GetObjectItem(request,"minute");if(hour||minute){set_field(account,"scheduleMinute",cJSON_CreateNumber(plan_fields(hour,minute)));changed=true;}
    auto lat=cJSON_GetObjectItem(request,"lat"),lng=cJSON_GetObjectItem(request,"lng");if(lat||lng){need(cJSON_IsNumber(lat)&&cJSON_IsNumber(lng),"location_invalid");check_location(lat->valuedouble,lng->valuedouble);auto point=cJSON_GetObjectItem(account,"location");set_field(point,"latitude",cJSON_CreateNumber(lat->valuedouble));set_field(point,"longitude",cJSON_CreateNumber(lng->valuedouble));changed=true;}
    need(changed,"empty_update");claim_management_request(job.request);write_config_sensitive(config.get());Json extra(cJSON_CreateObject());cJSON_AddNumberToObject(extra.get(),"a",job.index);cJSON_AddStringToObject(extra.get(),"sid",sid.c_str());send_management(job,"done",true,0,"account_updated",extra.get());
}
void handle_transfer(const Job& job,const cJSON *request){
    std::string op=job.operation;
    if(op=="put_commit"&&request_recorded(job.request))throw Error("duplicate_request");
    std::unique_lock<std::mutex> execution_guard(execution,std::defer_lock);if(op=="put_commit")need(execution_guard.try_lock(),"operation_busy");
    std::lock_guard<std::mutex> lock(upload_lock);std::string tag=str(request,"t");need(valid_request_id(tag),"transfer_id_invalid");
    if(op=="put_begin"){
        auto length=cJSON_GetObjectItem(request,"len"),index=cJSON_GetObjectItem(request,"a");need(cJSON_IsNumber(length)&&length->valuedouble==length->valueint&&length->valueint>0&&length->valueint<=6000,"transfer_size_invalid");need(cJSON_IsNumber(index)&&index->valuedouble==index->valueint&&index->valueint>=-1&&index->valueint<4,"account_index_invalid");std::string sid=str(request,"sid");need(sid.size()>=8&&sid.size()<=20&&sid.find_first_not_of("0123456789")==std::string::npos,"student_id");
        if(!upload.tag.empty()){need(upload.tag==tag&&upload.sid==sid&&upload.index==index->valueint&&upload.length==size_t(length->valueint),"transfer_busy");}
        else{upload.tag=tag;upload.sid=sid;upload.index=index->valueint;upload.length=length->valueint;upload.started=esp_timer_get_time();upload.data.resize(upload.length);upload.received.resize((upload.length+63)/64);}
        send_management(job,"done",true,0,"transfer_ready");return;
    }
    need(upload.tag==tag&&!upload.data.empty(),"transfer_missing");
    if(op=="put_chunk"){
        auto sequence=cJSON_GetObjectItem(request,"n");need(cJSON_IsNumber(sequence)&&sequence->valuedouble==sequence->valueint&&sequence->valueint>=0&&size_t(sequence->valueint)<upload.received.size(),"chunk_index_invalid");std::string encoded=str(request,"b");need(encoded.size()<=88,"chunk_size_invalid");B decoded(64);size_t count=0;need(mbedtls_base64_decode(decoded.data(),decoded.size(),&count,(const unsigned char*)encoded.data(),encoded.size())==0,"chunk_encoding_invalid");size_t number=sequence->valueint,offset=number*64,expected=std::min(size_t(64),upload.length-offset);if(count!=expected){secure_clear(decoded);throw Error("chunk_size_invalid");}
        if(upload.received[number]){bool same=std::equal(decoded.begin(),decoded.begin()+count,upload.data.begin()+offset);secure_clear(decoded);if(!same){clear_upload();throw Error("chunk_conflict");}}
        else{std::copy(decoded.begin(),decoded.begin()+count,upload.data.begin()+offset);upload.received[number]=1;secure_clear(decoded);}
        send_management(job,"done",true,0,"chunk_saved");return;
    }
    try{
        need(std::all_of(upload.received.begin(),upload.received.end(),[](uint8_t flag){return flag!=0;}),"transfer_incomplete");std::string expected=str(request,"sha256");need(expected.size()==64&&expected.find_first_not_of("0123456789abcdef")==std::string::npos,"transfer_hash_invalid");B digest=sha(upload.data);char actual[65];for(size_t i=0;i<32;++i)snprintf(actual+i*2,3,"%02x",digest[i]);need(expected==actual,"transfer_hash_mismatch");
        SensitiveJson package(cJSON_ParseWithLength((const char*)upload.data.data(),upload.data.size()));need(package.value.get(),"account_package_invalid");validate_package(package.value.get(),upload.sid);
        Json config=json(read_config());auto accounts=cJSON_GetObjectItem(config.get(),"accounts");need(cJSON_IsArray(accounts),"account_config_invalid");int selected=upload.index;
        if(selected<0){need(cJSON_GetArraySize(accounts)<4,"account_limit");cJSON *existing;cJSON_ArrayForEach(existing,accounts)need(str(existing,"student_id")!=upload.sid,"account_exists");selected=cJSON_GetArraySize(accounts);set_field(package.value.get(),"enabled",cJSON_CreateBool(false));}
        else resolve_account(config.get(),selected,upload.sid);
        if(!cJSON_GetObjectItem(package.value.get(),"enabled"))set_field(package.value.get(),"enabled",cJSON_CreateBool(false));if(!cJSON_GetObjectItem(package.value.get(),"scheduleMinute"))set_field(package.value.get(),"scheduleMinute",cJSON_CreateNumber(1270));
        auto replacement=cJSON_Duplicate(package.value.get(),true);need(replacement,"account_package_invalid");if(upload.index<0)cJSON_AddItemToArray(accounts,replacement);else cJSON_ReplaceItemInArray(accounts,selected,replacement);
        std::set<std::string> identities;cJSON *item;cJSON_ArrayForEach(item,accounts)need(identities.insert(str(item,"student_id")).second,"duplicate_account");
        claim_management_request(job.request);write_config_sensitive(config.get());Json extra(cJSON_CreateObject());cJSON_AddNumberToObject(extra.get(),"a",selected);cJSON_AddStringToObject(extra.get(),"sid",upload.sid.c_str());clear_upload();send_management(job,"done",true,0,"account_saved",extra.get());
    }catch(...){clear_upload();throw;}
}
