"""AES-GCM secret storage and encrypted, account-bound school Cookie caching."""
import hashlib
import hmac
import http.cookiejar
import json
import os
from pathlib import Path
import ssl
import urllib.request

from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from .errors import ToolError
from .transport import NoRedirect, Transport


class Vault:
    def __init__(self, directory):
        directory=Path(directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        path=directory/'dashboard.key'
        if not path.exists():
            if (directory/'dashboard.sqlite3').exists():
                raise ToolError('dashboard_key_missing','storage')
            try:
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(get_random_bytes(32)); stream.flush(); os.fsync(stream.fileno())
        self.key=path.read_bytes()
        if len(self.key)!=32:
            raise ToolError('dashboard_key_invalid','storage')

    def seal(self, value, purpose):
        cipher=AES.new(self.key,AES.MODE_GCM,nonce=get_random_bytes(12))
        cipher.update(purpose.encode())
        data=json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()
        encrypted,tag=cipher.encrypt_and_digest(data)
        return b'MW1'+cipher.nonce+tag+encrypted

    def open(self, value, purpose):
        try:
            if not isinstance(value,bytes) or value[:3]!=b'MW1' or len(value)<31:
                raise ValueError()
            cipher=AES.new(self.key,AES.MODE_GCM,nonce=value[3:15])
            cipher.update(purpose.encode())
            return json.loads(cipher.decrypt_and_verify(value[31:],value[15:31]))
        except (ValueError,TypeError,UnicodeError):
            raise ToolError('encrypted_data_invalid','storage') from None

    def digest(self, namespace, value):
        return hmac.new(self.key,(namespace+'\0'+value).encode(),hashlib.sha256).hexdigest()


class EncryptedTransport(Transport):
    """Uses the same HTTPS protocol as the CLI, with encrypted Cookie persistence."""
    def __init__(self,user_agent,cookie_path,store,timeout=25):
        self.user_agent=user_agent
        self.cookie_path=Path(cookie_path)
        self.binding=self.cookie_path.name
        self.store=store
        self.timeout=timeout
        self.jar=http.cookiejar.CookieJar()
        saved=store.cookie_load(self.binding)
        if saved is not None:
            try:
                for item in saved:
                    self.jar.set_cookie(http.cookiejar.Cookie(**item))
            except (ValueError,TypeError,KeyError):
                raise ToolError('encrypted_cookie_invalid','cookies') from None
        self.opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def save(self):
        values=[]
        for cookie in self.jar:
            if cookie.is_expired():
                continue
            values.append({key:getattr(cookie,key) for key in (
                'version','name','value','port','port_specified','domain','domain_specified',
                'domain_initial_dot','path','path_specified','secure','expires','discard','comment','comment_url')})
            values[-1]['rest']=dict(cookie._rest)
            values[-1]['rfc2109']=cookie.rfc2109
        self.store.cookie_save(self.binding,values)
