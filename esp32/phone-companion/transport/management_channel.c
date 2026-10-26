#include "management_channel.h"
#include "checkin_service.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <string.h>

typedef struct { char json[451]; } event_t;
static QueueHandle_t events;
static management_sender sender;
static void *sender_context;
static void publish_worker(void *unused) {
    (void)unused;event_t event;
    for (;;) if(xQueueReceive(events,&event,portMAX_DELAY)==pdTRUE)
        sender(event.json,sender_context);
}
static void copy_event(const char *json,void *unused) {
    (void)unused;if(!json||strlen(json)>450)return;
    event_t event={0};memcpy(event.json,json,strlen(json)+1);
    // Never block a local operation on an unavailable network.
    // A missing acknowledgement remains pending/unknown in the UI, never saved-success.
    (void)xQueueSend(events,&event,0);
}
bool management_channel_init(management_sender callback,void *context) {
    if(!callback||events)return false;
    events=xQueueCreate(16,sizeof(event_t));if(!events)return false;
    sender=callback;sender_context=context;
    if(xTaskCreate(publish_worker,"management_tx",6144,NULL,2,NULL)!=pdPASS) {
        vQueueDelete(events);events=NULL;return false;
    }
    checkin_service_set_listener(copy_event,NULL);return true;
}
bool management_channel_verified_command(const char *plaintext) {
    // Caller MUST verify encryption, sender authentication and anti-replay first.
    if(!plaintext||strncmp(plaintext,"CI:",3))return false;
    if(strlen(plaintext)<=180)checkin_service_handle_request(plaintext+3);
    return true;
}
