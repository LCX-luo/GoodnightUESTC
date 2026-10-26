#include "secure_channel.h"
#include "sdkconfig.h"
#include "cJSON.h"
#include "esp_random.h"
#include "mbedtls/gcm.h"
#include "mbedtls/base64.h"
#include "mbedtls/md.h"
#include "mbedtls/platform_util.h"
#include "nvs.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>

#define COMMAND_AAD "goodnight-management-command-v1"
#define STATUS_AAD "goodnight-management-status-v1"
static unsigned char encryption_key[32],signing_key[32];
static uint32_t expected_sequence;
static nvs_handle_t counter_store;
static int digit(char c){if(c>='0'&&c<='9')return c-'0';if(c>='a'&&c<='f')return c-'a'+10;if(c>='A'&&c<='F')return c-'A'+10;return -1;}
static bool key_parse(const char *hex,unsigned char *out){
    if(strlen(hex)!=64)return false;
    for(int i=0;i<32;i++){int a=digit(hex[2*i]),b=digit(hex[2*i+1]);if(a<0||b<0)return false;out[i]=(a<<4)|b;}
    unsigned char combined=0;for(int i=0;i<32;i++)combined|=out[i];return combined!=0;
}
bool gn_secure_init(void){
    if(!key_parse(CONFIG_GN_ENCRYPTION_KEY,encryption_key)||!key_parse(CONFIG_GN_SIGNING_KEY,signing_key))return false;
    if(nvs_open("gn_transport",NVS_READWRITE,&counter_store)!=ESP_OK)return false;
    esp_err_t result=nvs_get_u32(counter_store,"next_seq",&expected_sequence);
    return result==ESP_OK||result==ESP_ERR_NVS_NOT_FOUND;
}
bool gn_secure_pack(const char *kind,const char *payload,char *out,size_t capacity){
    bool ok=false;cJSON *body=cJSON_Parse(payload),*wrapper=cJSON_CreateObject();char *plain=NULL;
    if(!body||!wrapper)goto finish;
    cJSON_AddStringToObject(wrapper,"kind",kind);cJSON_AddItemToObject(wrapper,"payload",body);body=NULL;
    plain=cJSON_PrintUnformatted(wrapper);if(!plain||strlen(plain)>650)goto finish;
    size_t length=strlen(plain),encoded_length=0;unsigned char packet[700];char encoded[960];esp_fill_random(packet,12);
    mbedtls_gcm_context cipher;mbedtls_gcm_init(&cipher);
    int result=mbedtls_gcm_setkey(&cipher,MBEDTLS_CIPHER_ID_AES,encryption_key,256);
    if(!result)result=mbedtls_gcm_crypt_and_tag(&cipher,MBEDTLS_GCM_ENCRYPT,length,packet,12,(const unsigned char*)STATUS_AAD,strlen(STATUS_AAD),(unsigned char*)plain,packet+12,16,packet+12+length);
    mbedtls_gcm_free(&cipher);if(result)goto finish;
    if(mbedtls_base64_encode((unsigned char*)encoded,sizeof(encoded)-1,&encoded_length,packet,length+28))goto finish;
    encoded[encoded_length]=0;int count=snprintf(out,capacity,"{\"v\":1,\"type\":\"%s\",\"data\":\"%s\"}",kind,encoded);
    ok=count>0&&(size_t)count<capacity;
finish:
    if(plain){mbedtls_platform_zeroize(plain,strlen(plain));cJSON_free(plain);}cJSON_Delete(body);cJSON_Delete(wrapper);return ok;
}
bool gn_secure_unpack(const char *envelope,size_t size,char *command,size_t capacity,bool *sequence_ok,uint32_t *next_seq){
    bool ok=false;*sequence_ok=false;*next_seq=expected_sequence;
    cJSON *outer=cJSON_ParseWithLength(envelope,size),*inner=NULL;unsigned char packet[768],plain[768];size_t length=0;
    if(!outer)goto finish;
    cJSON *version=cJSON_GetObjectItem(outer,"v"),*type=cJSON_GetObjectItem(outer,"type"),*data=cJSON_GetObjectItem(outer,"data");
    if(!cJSON_IsNumber(version)||version->valuedouble!=1||!cJSON_IsString(type)||strcmp(type->valuestring,"command")||!cJSON_IsString(data))goto finish;
    if(mbedtls_base64_decode(packet,sizeof(packet),&length,(unsigned char*)data->valuestring,strlen(data->valuestring))||length<28)goto finish;
    size_t clear_length=length-28;mbedtls_gcm_context cipher;mbedtls_gcm_init(&cipher);
    int result=mbedtls_gcm_setkey(&cipher,MBEDTLS_CIPHER_ID_AES,encryption_key,256);
    if(!result)result=mbedtls_gcm_auth_decrypt(&cipher,clear_length,packet,12,(unsigned char*)COMMAND_AAD,strlen(COMMAND_AAD),packet+length-16,16,packet+12,plain);
    mbedtls_gcm_free(&cipher);if(result)goto finish;
    inner=cJSON_ParseWithLength((char*)plain,clear_length);if(!inner)goto finish;
    cJSON *seq=cJSON_GetObjectItem(inner,"seq"),*body=cJSON_GetObjectItem(inner,"body"),*signature=cJSON_GetObjectItem(inner,"sig");
    if(!cJSON_IsNumber(seq)||seq->valuedouble<0||seq->valuedouble>=UINT32_MAX||seq->valuedouble!=(double)(uint32_t)seq->valuedouble||!cJSON_IsString(body)||strlen(body->valuestring)>180||strlen(body->valuestring)>=capacity||!cJSON_IsString(signature)||strlen(signature->valuestring)!=64)goto finish;
    uint32_t received=(uint32_t)seq->valuedouble;char signed_data[208];unsigned char digest[32];
    int count=snprintf(signed_data,sizeof(signed_data),"%lu:%s",(unsigned long)received,body->valuestring);
    if(count<0||(size_t)count>=sizeof(signed_data))goto finish;
    if(mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),signing_key,32,(unsigned char*)signed_data,count,digest))goto finish;
    unsigned int mismatch=0;for(int i=0;i<32;i++){int a=digit(signature->valuestring[2*i]),b=digit(signature->valuestring[2*i+1]);if(a<0||b<0)goto finish;mismatch|=digest[i]^(unsigned char)((a<<4)|b);}
    if(mismatch)goto finish;
    ok=true;if(received<expected_sequence||(uint64_t)received>(uint64_t)expected_sequence+5)goto finish;
    uint32_t next=received+1;
    if(nvs_set_u32(counter_store,"next_seq",next)!=ESP_OK||nvs_commit(counter_store)!=ESP_OK){ok=false;goto finish;}
    expected_sequence=next;*next_seq=next;*sequence_ok=true;memcpy(command,body->valuestring,strlen(body->valuestring)+1);
finish:
    mbedtls_platform_zeroize(plain,sizeof(plain));mbedtls_platform_zeroize(packet,sizeof(packet));cJSON_Delete(inner);cJSON_Delete(outer);return ok;
}
