#pragma once
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
/** Caller encrypts/authenticates outgoing status; send synchronously or copy it. */
typedef bool (*management_sender)(const char *json,void *context);
bool management_channel_init(management_sender callback,void *context);
/** Call ONLY for an already decrypted/authenticated/replay-checked command. */
bool management_channel_verified_command(const char *plaintext);
#ifdef __cplusplus
}
#endif
