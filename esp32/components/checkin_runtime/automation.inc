/* Daily retry state is committed before network work: power loss never repeats an uncertain write. */
struct AutoState {std::string date;time_t next=0;bool stopped=false;};
AutoState read_auto(const std::string& sid){
    std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;
    need(nvs_open_from_partition("checkin","auto_plan",NVS_READWRITE,&handle)==ESP_OK,"auto_store_unavailable");
    char raw[192]={};size_t size=sizeof(raw);auto code=nvs_get_str(handle,account_key(sid).c_str(),raw,&size);nvs_close(handle);
    if(code==ESP_ERR_NVS_NOT_FOUND)return AutoState{};
    need(code==ESP_OK,"auto_store_invalid");Json value=json(raw);auto next=cJSON_GetObjectItem(value.get(),"next");
    need(cJSON_IsNumber(next),"auto_store_invalid");return {str(value.get(),"date"),time_t(next->valuedouble),cJSON_IsTrue(cJSON_GetObjectItem(value.get(),"stop"))!=0};
}
void save_auto(const std::string& sid,const AutoState& state){
    Json value(cJSON_CreateObject());cJSON_AddStringToObject(value.get(),"date",state.date.c_str());cJSON_AddNumberToObject(value.get(),"next",state.next);cJSON_AddBoolToObject(value.get(),"stop",state.stopped);std::string raw=dump(value.get());
    std::lock_guard<std::mutex> lock(storage);nvs_handle_t handle;
    need(nvs_open_from_partition("checkin","auto_plan",NVS_READWRITE,&handle)==ESP_OK,"auto_store_unavailable");
    auto code=nvs_set_str(handle,account_key(sid).c_str(),raw.c_str());if(code==ESP_OK)code=nvs_commit(handle);nvs_close(handle);need(code==ESP_OK,"auto_store_failed");
}
bool automatic_due(const AutoState& state,const std::string& date,time_t now){return state.date!=date||(!state.stopped&&now>=state.next);}
bool automatic_retryable(const cJSON *result){
    std::string state=str(result,"state");
    if(state=="outside_checkin_window"||state=="insufficient_heap")return true;
    auto code=cJSON_GetObjectItem(result,"code"),after=cJSON_GetObjectItem(result,"after"),message=cJSON_GetObjectItem(result,"msg");
    return state=="submission_rejected"&&cJSON_IsNumber(code)&&code->valueint==4006&&cJSON_IsString(after)&&std::string(after->valuestring)=="PENDING"&&cJSON_IsString(message)&&std::string(message->valuestring)=="当前不在打卡时间段内";
}
void run_automatic(cJSON *account,Json& config){
    std::string sid=str(account,"student_id"),date=day();time_t now=time(nullptr);
    AutoState state=read_auto(sid);if(!automatic_due(state,date,now))return;
    // Stop by default; ONLY an explicit safe rejection can reopen this daily plan.
    state={date,now+60,true};save_auto(sid,state);
    try{run_account(account,config,true,false,true);}
    catch(const Error& error){outcome_error(sid,error);event(error.what(),sid,error.code,"",error.school_message);}
    catch(...){event("automatic_result_unknown",sid);return;}
    Json result=read_outcome(sid);
    if(automatic_retryable(result.get())){state.next=std::max(state.next,time(nullptr)+60);state.stopped=false;save_auto(sid,state);event("automatic_retry_scheduled",sid);}
    else event("automatic_stopped_today",sid);
}
