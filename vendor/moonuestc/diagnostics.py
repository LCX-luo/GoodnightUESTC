"""Small, allowlisted diagnostics; never persist raw school bodies or headers."""
import base64
import html
import json
import math
import re
import unicodedata
import urllib.parse
from html.parser import HTMLParser

MASK='[已隐藏]'
ACTIONS={'first_submit','recheck','not_submitted'}
OUTCOMES={'attempting','accepted','rejected','error','unknown'}
STATUSES={'PENDING','CHECKED_IN','STUDENT_REPORTED','INSTRUCTOR_REPORTED','EXEMPT'}


class _Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.skip:self.skip-=1
    def handle_data(self,value):
        if not self.skip:self.parts.append(value)


def school_message(value,account=None):
    if not isinstance(value,str) or not value.strip():return None
    if len(value)>8192:return '学校错误信息过长，已省略'
    secrets=[]
    for key in ('student_id','password','browser_fingerprint','user_agent','operation_ticket'):
        secret=(account or {}).get(key)
        if isinstance(secret,str) and secret:
            secrets.extend([secret,html.escape(secret),urllib.parse.quote(secret,safe=''),urllib.parse.quote_plus(secret),json.dumps(secret,ensure_ascii=True)[1:-1],base64.b64encode(secret.encode()).decode()])
    for secret in sorted(set(secrets),key=len,reverse=True):
        value=value.replace(secret,MASK)
        if re.fullmatch(r'[a-fA-F0-9]{24,}',secret):value=re.sub(re.escape(secret),MASK,value,flags=re.I)
    value=html.unescape(value)
    if '<' in value and '>' in value:
        parser=_Text()
        try:parser.feed(value);value=' '.join(parser.parts)
        except (ValueError,RecursionError):return '学校错误信息格式异常，已省略'
    value=html.unescape(value)
    # Reapply after entity decoding to avoid encoded echoed credentials.
    for secret in sorted(set(secrets),key=len,reverse=True):value=value.replace(secret,MASK)
    value=re.sub(r'(?im)(?:set-cookie|cookie|authorization)\s*[:=][^\r\n]*',lambda m:m.group(0).split(':',1)[0].split('=',1)[0]+'='+MASK,value)
    value=re.sub(r'https?://[^\s<>]+','[链接已隐藏]',value,flags=re.I)
    value=re.sub(r'(?i)\bBearer\s+[^\s,;]+','Bearer '+MASK,value)
    value=re.sub(r'''(?ix)["']?(\b(?:password|passwd|pwd|cookie|authorization|token|ticket|session(?:id)?|jsessionid|castgc|multifactor_browser_fingerprint|fingerprint|username)\b|学号|姓名|身份证号?|手机号?|密码)["']?\s*[:：=]\s*(?:"[^"]*"|'[^']*'|[^\s,，;；]+)''',lambda m:m.group(1)+'='+MASK,value)
    value=re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',MASK,value)
    value=re.sub(r'(?<!\d)\d{8,}(?:[Xx])?(?!\d)',MASK,value)
    value=re.sub(r'(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}={0,2}(?![A-Za-z0-9_-])',MASK,value)
    value=''.join(' ' if unicodedata.category(c).startswith('C') else c for c in value)
    return ' '.join(value.split())[:360] or None


def _code(value):return value if type(value) is int and -(2**63)<value<2**63 else None

def _stamp(value):return value if type(value) in (int,float) and math.isfinite(value) and 0<=value<=2**40 else None

def _stable(value):return value if isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}',value) else None


def error_details(error,account=None):
    result={'reason':error.reason,'stage':error.stage}
    if _code(error.api_code) is not None:result['apiCode']=error.api_code
    if type(getattr(error,'http_status',None)) is int and 100<=error.http_status<=599:result['httpStatus']=error.http_status
    message=school_message(getattr(error,'school_message',None),account)
    if message:result['schoolMessage']=message
    return result


def submission_details(value,account=None):
    if not isinstance(value,dict):return None
    result={}
    for key in ('attemptId','originRun'):
        if isinstance(value.get(key),str) and re.fullmatch(r'[a-f0-9]{32}',value[key]):result[key]=value[key]
    for key in ('startedAt','finishedAt'):
        if _stamp(value.get(key)) is not None:result[key]=value[key]
    if isinstance(value.get('outcome'),str) and value['outcome'] in OUTCOMES:result['outcome']=value['outcome']
    if type(value.get('httpStatus')) is int and 100<=value['httpStatus']<=599:result['httpStatus']=value['httpStatus']
    if _code(value.get('apiCode')) is not None:result['apiCode']=value['apiCode']
    for key in ('reason','stage'):
        if _stable(value.get(key)):result[key]=value[key]
    message=school_message(value.get('schoolMessage'),account)
    if message:result['schoolMessage']=message
    return result or None


def verification_details(value,account=None):
    if not isinstance(value,dict):return None
    result={}
    if type(value.get('attempt')) is int and 0<=value['attempt']<=3:result['attempt']=value['attempt']
    if _stamp(value.get('at')) is not None:result['at']=value['at']
    if isinstance(value.get('status'),str) and value['status'] in STATUSES:result['status']=value['status']
    for key in ('reason','stage'):
        if _stable(value.get(key)):result[key]=value[key]
    if type(value.get('httpStatus')) is int and 100<=value['httpStatus']<=599:result['httpStatus']=value['httpStatus']
    if _code(value.get('apiCode')) is not None:result['apiCode']=value['apiCode']
    message=school_message(value.get('schoolMessage'),account)
    if message:result['schoolMessage']=message
    return result or None
