"""Generate local configuration only; no credentials are sent anywhere."""
import getpass,json,secrets,os
from pathlib import Path
from urllib.parse import urlsplit
ROOT=Path(__file__).resolve().parent

def main():
    outputs=[ROOT/'sdkconfig.defaults.local',ROOT/'phone-management.local.json']
    if any(p.exists() for p in outputs):
        raise SystemExit('Local configuration exists; back it up and use menuconfig or edit locally. Not overwritten.')
    ssid=input('Wi-Fi SSID: ').strip();password=getpass.getpass('Wi-Fi password: ')
    uri=input('Your MQTT URI (mqtt://host:1883 or mqtts://host:8883): ').strip()
    parsed=urlsplit(uri)
    if not ssid or len(ssid.encode())>32 or len(password.encode())>63 or parsed.scheme not in ('mqtt','mqtts') or not parsed.hostname or parsed.username or parsed.password:
        raise SystemExit('Invalid SSID/password or broker URI. URI credentials are not supported by this setup helper.')
    prefix='goodnight';device=secrets.token_hex(6);encryption=secrets.token_hex(32);signing=secrets.token_hex(32)
    fields={'GN_WIFI_SSID':ssid,'GN_WIFI_PASSWORD':password,'GN_MQTT_URI':uri,'GN_TOPIC_PREFIX':prefix,'GN_DEVICE_ID':device,'GN_ENCRYPTION_KEY':encryption,'GN_SIGNING_KEY':signing}
    outputs[0].write_text(''.join('CONFIG_'+k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in fields.items()),encoding='utf-8')
    outputs[1].write_text(json.dumps({'brokerUri':uri,'topicPrefix':prefix,'deviceId':device,'encryptionKeyHex':encryption,'signingKeyHex':signing},indent=2),encoding='utf-8')
    for path in outputs:os.chmod(path,0o600)
    print('Local build defaults and phone configuration created. Never upload either file or a configured firmware binary.')
    if (ROOT/'sdkconfig').exists():print('sdkconfig already exists: review menuconfig; defaults do not replace existing values automatically.')

if __name__=='__main__':main()
