"""Deterministic public protocol fixtures; no real authentication material."""
from pathlib import Path
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from moon_uestc._wechat_crypto import hkdf_expand, encrypt_record_payload
from moon_uestc._wechat_wire import build_client_hello, build_psk_client_hello, wpkg_head

def main():
    def public(n):
        return ec.derive_private_key(n,ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)
    rnd=bytes(range(32));key=bytes(range(16));iv=bytes(range(12));message=b'native vector'
    fixtures={
        'aes192':AESGCM(bytes(range(24))).encrypt(iv,message,b'public-aad').hex(),
        'point1':public(1).hex(),'point2':public(2).hex(),
        'hkdf':hkdf_expand(rnd,b'handshake key expansion'+hashlib.sha256(b'transcript').digest(),56).hex(),
        'cipher':encrypt_record_payload(key,iv,3,0x17,message).hex(),
        'hello':hashlib.sha256(build_client_hello(rnd,1700000000,public(1),public(2))).hexdigest(),
        'pskhello':hashlib.sha256(build_psk_client_hello(rnd,1700000000,b'fixture-entry')).hexdigest(),
        'wpkg':hashlib.sha256(wpkg_head({1:1,2:123456789},{14:b'',24:b'device',27:b'f9'})).hexdigest(),
    }
    output=['// Generated cross-language test vectors; all inputs are public fixtures.','namespace fixtures {']
    output += [f'constexpr const char *{key}="{value}";' for key,value in fixtures.items()]
    output.append('}')
    target=Path(__file__).resolve().parents[1]/'esp32/components/checkin_runtime/include/protocol_vectors.hpp'
    target.write_text('\n'.join(output)+'\n',encoding='utf-8')
    print('Generated public ESP32 cross-language fixtures.')

if __name__=='__main__':main()
