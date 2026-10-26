#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
bool gn_secure_init(void);
/** Returns an encrypted JSON envelope; never prints plaintext or keys. */
bool gn_secure_pack(const char *kind,const char *payload,char *output,size_t capacity);
/** Verifies AEAD, HMAC and durable sequence before writing command and next_seq. */
bool gn_secure_unpack(const char *envelope,size_t length,char *command,size_t capacity,
                      bool *sequence_ok,uint32_t *next_seq);
