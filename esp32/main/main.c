#include "sdkconfig.h"
#include "checkin_service.h"
#include "management_channel.h"
#include "secure_channel.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_crt_bundle.h"
#include "mqtt_client.h"
#include "nvs_flash.h"
#include <stdio.h>
#include <string.h>

static const char *TAG="goodnight";
static esp_mqtt_client_handle_t client;
static char command_topic[160],status_topic[160];
static bool channel_ready;
static bool publish_status(const char *kind,const char *json){
    char encrypted[1100];if(!client||!gn_secure_pack(kind,json,encrypted,sizeof(encrypted)))return false;
    return esp_mqtt_client_enqueue(client,status_topic,encrypted,0,1,0,true)>=0;
}
static bool send_management_event(const char *json,void *context){(void)context;return publish_status("ci",json);}
static void mqtt_event(void *argument,esp_event_base_t base,int32_t id,void *event_data){
    (void)argument;(void)base;esp_mqtt_event_handle_t event=event_data;
    static char envelope[1024];static size_t received,total;
    if(id==MQTT_EVENT_CONNECTED){esp_mqtt_client_subscribe(client,command_topic,1);ESP_LOGI(TAG,"message channel connected");return;}
    if(id==MQTT_EVENT_DISCONNECTED){ESP_LOGW(TAG,"message channel disconnected");return;}
    if(id!=MQTT_EVENT_DATA)return;
    if(event->current_data_offset==0){
        received=total=0;
        if(event->topic_len!=(int)strlen(command_topic)||memcmp(event->topic,command_topic,event->topic_len)||event->total_data_len<=0||event->total_data_len>=(int)sizeof(envelope))return;
        total=event->total_data_len;
    }
    if(!total||event->current_data_offset!=(int)received||event->data_len<0||received+event->data_len>total){received=total=0;return;}
    memcpy(envelope+received,event->data,event->data_len);received+=event->data_len;if(received!=total)return;
    char command[181]={0},ack[96];bool sequence_ok=false;uint32_t next=0;
    bool valid=gn_secure_unpack(envelope,total,command,sizeof(command),&sequence_ok,&next);received=total=0;
    if(!valid){ESP_LOGW(TAG,"management authentication failed");return;}
    snprintf(ack,sizeof(ack),"{\"seq_ok\":%s,\"next_seq\":%lu}",sequence_ok?"true":"false",(unsigned long)next);
    publish_status("ack",ack);
    if(sequence_ok)management_channel_verified_command(command);
}
static void start_mqtt(void){
    if(client||!CONFIG_GN_MQTT_URI[0])return;
    esp_mqtt_client_config_t config={.broker.address.uri=CONFIG_GN_MQTT_URI,
        .broker.verification.crt_bundle_attach=esp_crt_bundle_attach,
        .session.keepalive=60,.network.timeout_ms=10000};
    client=esp_mqtt_client_init(&config);if(!client){ESP_LOGE(TAG,"message client unavailable");return;}
    if(!management_channel_init(send_management_event,NULL)){ESP_LOGE(TAG,"management queue unavailable");return;}
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(client,ESP_EVENT_ANY_ID,mqtt_event,NULL));
    ESP_ERROR_CHECK(esp_mqtt_client_start(client));
}
static void network_event(void *argument,esp_event_base_t base,int32_t id,void *data){
    (void)argument;(void)data;
    if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_START)esp_wifi_connect();
    else if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_DISCONNECTED){ESP_LOGW(TAG,"Wi-Fi disconnected; reconnecting");esp_wifi_connect();}
    else if(base==IP_EVENT&&id==IP_EVENT_STA_GOT_IP){ESP_LOGI(TAG,"Wi-Fi ready");if(channel_ready)start_mqtt();}
}
void app_main(void){
    // Never erase an existing partition automatically on initialization failure.
    ESP_ERROR_CHECK(nvs_flash_init());ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,network_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,network_event,NULL));
    checkin_service_start();
    int a=snprintf(command_topic,sizeof(command_topic),"%s/%s/cmd",CONFIG_GN_TOPIC_PREFIX,CONFIG_GN_DEVICE_ID);
    int b=snprintf(status_topic,sizeof(status_topic),"%s/%s/status",CONFIG_GN_TOPIC_PREFIX,CONFIG_GN_DEVICE_ID);
    channel_ready=CONFIG_GN_DEVICE_ID[0]&&a>0&&b>0&&a<(int)sizeof(command_topic)&&b<(int)sizeof(status_topic)&&gn_secure_init();
    if(!channel_ready)ESP_LOGW(TAG,"management keys or identifier missing; USB provisioning remains available");
    if(!CONFIG_GN_WIFI_SSID[0]){ESP_LOGW(TAG,"Wi-Fi not configured; run configure.py or menuconfig");return;}
    wifi_config_t wifi={0};size_t ssid_size=strlen(CONFIG_GN_WIFI_SSID),password_size=strlen(CONFIG_GN_WIFI_PASSWORD);
    if(ssid_size>sizeof(wifi.sta.ssid)||password_size>=sizeof(wifi.sta.password)){ESP_LOGE(TAG,"Wi-Fi configuration length invalid");return;}
    memcpy(wifi.sta.ssid,CONFIG_GN_WIFI_SSID,ssid_size);memcpy(wifi.sta.password,CONFIG_GN_WIFI_PASSWORD,password_size);
    wifi.sta.pmf_cfg.capable=true;ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&wifi));ESP_ERROR_CHECK(esp_wifi_start());
}
