#pragma once
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
void checkin_service_start(void);
/** Local management only. Caller MUST authenticate/decrypt requests before dispatch.
 * Callback JSON contains no credentials. It may run on the caller or worker task;
 * copy it synchronously and do not call management APIs from inside the callback.
 */
typedef void (*checkin_service_listener)(const char *json, void *user);
void checkin_service_set_listener(checkin_service_listener listener, void *user);
/** Compact JSON, at most 180 UTF-8 bytes. No network transport is installed here. */
bool checkin_service_handle_request(const char *json);
#ifdef __cplusplus
}
#endif
