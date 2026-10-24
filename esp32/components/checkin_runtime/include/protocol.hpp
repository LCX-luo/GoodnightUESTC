#pragma once
#include <cstdint>
#include <vector>
#include <string>
#include <map>
#include <stdexcept>
#include <memory>
#include "cJSON.h"
namespace wc {
using B=std::vector<uint8_t>;
struct Error:std::runtime_error { int code; explicit Error(const char *stage,int business=0):std::runtime_error(stage),code(business){} };
inline void need(bool yes,const char *stage) { if(!yes) throw Error(stage); }
B bytes(const std::string &s); B hex(const char *s); B slice(const B& b,size_t start,size_t end);
B join(std::initializer_list<B> values); B be(uint64_t value,size_t n);
B sha(const B& b); B hmac(const B& key,const B& b); B hkdf(const B& key,const B& info,size_t n);
B random(size_t n); B pbv(unsigned field,uint64_t value); B pbb(unsigned field,const B& value);
struct Field { bool binary=false;uint64_t number=0;B data; };
using Fields=std::map<unsigned,Field>;
Fields parse(const B& data); B field(const Fields& f,unsigned n); uint64_t number(const Fields& f,unsigned n,uint64_t fallback=0);
B lz4(const B& data); B unz4(const B& data);
B gcm(const B& key,const B& iv,const B& aad,const B& data,bool decrypt=false);
B blob(const B& key,const B& aad,const B& data,bool decrypt=false);
B record(uint8_t type,const B& payload); B handshake(uint8_t type,const B& payload);
B clienthello(const B& rnd,uint32_t ts,const B& p1,const B& p2);
B pskhello(const B& rnd,uint32_t ts,const B& entry);
B rec_cipher(const B& key,const B& iv,uint64_t seq,uint8_t type,const B& data,bool decrypt=false);
B wpkg(const std::map<unsigned,uint64_t>& nums,const std::map<unsigned,B>& data);
size_t wpkg_size(const B& data);
std::string login_code(const std::string& login_buffer,const std::string& appid);
bool self_test();
struct JsonDeleter { void operator()(cJSON *p)const { cJSON_Delete(p); } };
using Json=std::unique_ptr<cJSON,JsonDeleter>;
Json json(const std::string& s); std::string dump(const cJSON *v);
std::string str(const cJSON *p,const char *key);
struct Http { int status=0;std::string body; };
Http https(const std::string &url,const std::string &method,const std::string &body,
           const std::map<std::string,std::string>& headers={});
}
