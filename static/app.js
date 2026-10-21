'use strict';
const $ = id => document.getElementById(id);
let csrf = '', map, marker, savedLocation = null, loginBusy = false, confirmation = '', submitting = false;
let refreshInFlight = false;
const liveProgress=document.createElement('p');liveProgress.id='checkin-progress';liveProgress.className='live-progress';liveProgress.hidden=true;liveProgress.setAttribute('role','status');$('checkin-error').before(liveProgress);
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('toast').hidden=true,5000); }
async function api(path, data) {
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),path==='/api/checkin'?120000:path.includes('/test/online')||path.includes('/checkin/prepare')?60000:8000);
  try{const response=await fetch(path,{signal:controller.signal,method:data===undefined?'GET':'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(data===undefined?{}:{body:JSON.stringify(data)})});
    const result=await response.json(); if(!response.ok)throw new Error(result.error||'操作失败');return result;
  }catch(e){if(e.name==='AbortError')throw new Error(path==='/api/checkin'?'响应超时，签到结果尚不明确，请先核对学校记录，勿重复提交。':'连接等待超时，请检查网络后重试。');throw e;}finally{clearTimeout(timeout);}
}
function inverse(lat,lng){ // Invert the forward GCJ transform for map display only.
  const a=6378245,ee=.00669342162296594323,pi=Math.PI;
  function forward(lat,lng){if(!(73.66<lng&&lng<135.05&&3.86<lat&&lat<53.55))return [lat,lng];const x=lng-105,y=lat-35;
    let dlat=-100+2*x+3*y+.2*y*y+.1*x*y+.2*Math.sqrt(Math.abs(x));
    dlat+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(y*pi)+40*Math.sin(y*pi/3))*2/3+(160*Math.sin(y*pi/12)+320*Math.sin(y*pi/30))*2/3;
    let dlng=300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x));
    dlng+=(20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3+(20*Math.sin(x*pi)+40*Math.sin(x*pi/3))*2/3+(150*Math.sin(x*pi/12)+300*Math.sin(x*pi/30))*2/3;
    const rad=lat*pi/180,magic=1-ee*Math.sin(rad)**2,sqrt=Math.sqrt(magic);
    return [lat+dlat*180/((a*(1-ee)/(magic*sqrt))*pi),lng+dlng*180/(a/sqrt*Math.cos(rad)*pi)];}
  let p=[lat,lng];for(let i=0;i<5;i++){const f=forward(...p);p=[p[0]+lat-f[0],p[1]+lng-f[1]];}return p;
}
function showPoint(lat,lng,system='wgs84',center=false){
  if(!map)return; const point=system==='gcj02'?inverse(lat,lng):[lat,lng];
  if(marker)marker.setLatLng(point);else marker=L.circleMarker(point,{radius:9,color:'#fff',weight:3,fillColor:'#2c6676',fillOpacity:1}).addTo(map);
  if(center)map.setView(point,17);
  $('point-state').textContent='已选位置'; $('map-tip').textContent='已选点 · 可继续点击调整';
}
function fillLocation(loc,center=true){savedLocation=loc;if(!loc)return;$('place-name').value=loc.name;$('latitude').value=loc.latitude;$('longitude').value=loc.longitude;$('coordinate-system').value=loc.coordinate_system;showPoint(loc.latitude,loc.longitude,loc.coordinate_system,center);$('converted').textContent=`学校坐标 GCJ-02：${loc.gcj02.longitude.toFixed(6)}, ${loc.gcj02.latitude.toFixed(6)}`;}
function currentLocation(){return {name:$('place-name').value.trim()||'手动选点',latitude:Number($('latitude').value),longitude:Number($('longitude').value),coordinate_system:$('coordinate-system').value};}
function dirtyLocation(){if(!$('latitude').value||!$('longitude').value)return true;const loc=currentLocation();return !savedLocation||['name','latitude','longitude','coordinate_system'].some(k=>loc[k]!==savedLocation[k]);}
async function refresh(){
  if(refreshInFlight)return;refreshInFlight=true;try{
  const r=await api('/api/status');csrf=r.csrf;
  const active=['opening','waiting','verifying'].includes(r.login.state);loginBusy=active;
  $('login-button').disabled=active;$('cancel-login').hidden=!active;
  $('login-button').textContent=active?(r.login.state==='verifying'?'正在验证学校会话…':'等待学校登录完成…'):'用 Edge 登录并导入 ↗';
  $('session-badge').textContent=r.account?'已保存':active?'登录中':'未登录';$('session-badge').className='badge'+(r.account?' green':'');
  $('account-dot').classList.toggle('active',Boolean(r.account));
  $('account-label').textContent=r.account?`${r.account.student_id} · ${r.account.cookie_count} 个会话 Cookie`:'等待导入学校账号';
  $('login-message').textContent=r.login.state==='idle'&&r.account?'已保存会话，运行在线检查可验证是否有效。':r.login.message+(active&&r.login.elapsed!==undefined?`（已用 ${Math.floor(r.login.elapsed)} 秒）`:'');
  if(r.login.state==='success'&&refresh.previous!=='success')toast('Cookie 已自动导入，可进行在线只读检查。');refresh.previous=r.login.state;
  if(!refresh.initialized){fillLocation(r.location,false);refresh.initialized=true;}
  $('prepare-checkin').disabled=!r.account||!savedLocation||active||submitting;
  const op=r.operation;const working=op&&op.active;
  $('prepare-checkin').textContent=working&&op.kind==='prepare'?`正在预检查… ${Math.floor(op.elapsed)} 秒`:'预检查并确认签到 →';
  if(working){const message=op.message+`（已用 ${Math.floor(op.elapsed)} 秒）`;
    if(op.kind==='prepare'||op.kind==='checkin')$('checkin-message').textContent=message;
    if(op.kind==='online')$('online').textContent=message;
    liveProgress.hidden=op.kind!=='checkin';liveProgress.textContent=message;
    if(op.kind==='checkin')$('submit-checkin').textContent='正在提交并核对…';
  }else{liveProgress.hidden=true;$('submit-checkin').textContent='确认并提交签到';}
  }finally{refreshInFlight=false;}
}
function renderResult(result){
  $('result').hidden=false;$('result').classList.remove('error');$('result-title').textContent=result.mode==='offline'?'离线自检通过':'在线只读检查完成';$('result-time').textContent=new Date().toLocaleTimeString('zh-CN');
  $('result-json').textContent=JSON.stringify(result,null,2);$('result-summary').replaceChildren();
  const statuses={PENDING:'待打卡',CHECKED_IN:'已签到',STUDENT_REPORTED:'学生已报告',INSTRUCTOR_REPORTED:'辅导员已报告',EXEMPT:'已豁免'};
  const values=result.mode==='offline'?[['访问学校','0 次'],['提交记录','0 次'],['写入保护',`${result.blockedRequests.length} 项已拦截`]]:[['当天记录',statuses[result.recordStatus]||result.recordStatus],['学校时段',`${result.window.start}–${result.window.end}`],['当前时段',result.window.open?'开放':'未开放'],['所选位置',result.insideFence===null?'尚未配置':result.insideFence?'在允许范围内':'不在允许范围内'],['位置范围',`${result.fenceCount} 个`],['提交记录','0 次']];
  for(const [label,value] of values){const box=document.createElement('div');box.className='metric';const span=document.createElement('span'),strong=document.createElement('strong');span.textContent=label;strong.textContent=value;box.append(span,strong);$('result-summary').append(box);}
}
async function runTest(mode){const button=$(mode);const label=button.innerHTML;button.disabled=true;button.textContent=mode==='online'?'正在读取学校记录…':'正在运行离线自检…';try{if(mode==='online'&&dirtyLocation())throw new Error('请先选择并保存实际位置。');const r=await api('/api/test/'+mode,{});renderResult(r.result);}catch(e){toast(e.message);$('result').hidden=false;$('result').classList.add('error');$('result-title').textContent=e.message;$('result-summary').replaceChildren();$('result-json').textContent='未提交任何打卡或报告记录。';$('result-time').textContent='';}finally{button.disabled=false;button.innerHTML=label;}}
$('login-form').addEventListener('submit',async e=>{e.preventDefault();$('login-button').disabled=true;$('login-button').textContent='正在打开 Edge…';const password=$('password').value;try{await api('/api/login',{student_id:$('student-id').value.trim(),password});await refresh();}catch(e){toast(e.message);$('login-button').disabled=false;$('login-button').textContent='用 Edge 登录并导入 ↗';}});
$('show-password').addEventListener('click',()=>{const hide=$('password').type==='password';$('password').type=hide?'text':'password';$('show-password').textContent=hide?'隐藏':'显示';});
$('cancel-login').addEventListener('click',async()=>{try{await api('/api/login/cancel',{});toast('已请求取消，窗口稍后关闭。');}catch(e){toast(e.message);}});
$('forget').addEventListener('click',async()=>{try{await api('/api/session/forget',{});await refresh();toast('本机会话已清除。');}catch(e){toast(e.message);}});
$('location-form').addEventListener('submit',async e=>{e.preventDefault();try{const r=await api('/api/location',currentLocation());fillLocation(r.location);toast('位置已保存在本机。');}catch(e){toast(e.message);}});
for(const id of ['latitude','longitude','coordinate-system'])$(id).addEventListener('change',()=>{if($('latitude').value&&$('longitude').value){const loc=currentLocation();if(Number.isFinite(loc.latitude)&&Number.isFinite(loc.longitude)&&Math.abs(loc.latitude)<=90&&Math.abs(loc.longitude)<=180){showPoint(loc.latitude,loc.longitude,loc.coordinate_system,true);$('converted').textContent='位置已修改，请保存后运行检查。';}}});
$('offline').addEventListener('click',()=>runTest('offline'));$('online').addEventListener('click',()=>runTest('online'));
$('prepare-checkin').addEventListener('click',async()=>{
  if(dirtyLocation()){toast('请先保存当前实际位置。');return;}
  submitting=true;$('prepare-checkin').disabled=true;$('prepare-checkin').textContent='正在预检查…';$('checkin-message').textContent='正在检查学校会话、时段和位置…';
  try{const r=await api('/api/checkin/prepare',{});confirmation=r.confirmation;$('checkin-preview').replaceChildren();
    for(const [label,value] of [['日期',r.preview.businessDate],['位置',r.preview.name],['地址',r.preview.address],['学校坐标',`${r.preview.longitude.toFixed(6)}, ${r.preview.latitude.toFixed(6)} · GCJ-02`],['允许时段',`${r.preview.window.start}–${r.preview.window.end}`]]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;$('checkin-preview').append(dt,dd);}
    $('confirm-location').checked=false;$('submit-checkin').disabled=true;$('checkin-error').hidden=true;$('checkin-dialog').showModal();
  }catch(e){toast(e.message);$('checkin-message').textContent=e.message;}
  finally{submitting=false;refresh().catch(()=>{});}
});
$('confirm-location').addEventListener('change',()=>{$('submit-checkin').disabled=!$('confirm-location').checked;});
$('close-confirmation').addEventListener('click',()=>{$('checkin-dialog').close();confirmation='';});
$('submit-checkin').addEventListener('click',async()=>{
  if(!confirmation||!$('confirm-location').checked||submitting)return;
  submitting=true;$('submit-checkin').disabled=true;$('close-confirmation').disabled=true;$('confirm-location').disabled=true;
  $('submit-checkin').textContent='正在复核并提交…';liveProgress.hidden=false;liveProgress.textContent='正在做提交前检查，请勿重复点击。';
  const ticket=confirmation;confirmation='';
  try{const r=await api('/api/checkin',{confirmation:ticket,confirm:true,actual_location_confirmed:true});const result=r.result;
    const labels={confirmed:'签到已确认',already_recorded:'学校已有当天记录',prior_attempt:'当天已有提交尝试，仅复查',unknown:'提交结果待核对',rejected:'学校拒绝提交',record_changed:'当天记录发生变化'};
    $('checkin-state').textContent=labels[result.result]||'请核对学校记录';
    $('checkin-message').textContent=result.confirmed?'已回读学校当天记录，确认签到成功。':result.result==='already_recorded'?'没有再次提交，学校当天已经有签到、报告或豁免记录。':result.result==='prior_attempt'?'没有重复提交，请运行在线只读检查核对学校记录。':result.result==='rejected'?`学校未接受本次请求${result.apiCode!==undefined?'（业务码 '+result.apiCode+'）':''}，请核对学校记录。`:'本工具不会自动重发，请运行在线只读检查并核对学校记录。';
    $('checkin-dialog').close();toast(labels[result.result]||'请核对学校记录');
  }catch(e){$('checkin-error').textContent=e.message+' 请关闭弹窗后重新检查；不要连续重试。';$('checkin-error').hidden=false;}
  finally{submitting=false;$('close-confirmation').disabled=false;$('confirm-location').disabled=false;refresh().catch(()=>{});}
});
$('checkin-dialog').addEventListener('cancel',e=>{if(submitting)e.preventDefault();else confirmation='';});
const campuses={shahe:[30.6752,104.0975],qingshuihe:[30.7528,103.9313]};
function viewCampus(key){map.setView(campuses[key],16);for(const name of Object.keys(campuses))$('campus-'+name).setAttribute('aria-pressed',String(name===key));}
try{map=L.map('map',{scrollWheelZoom:true}).setView(campuses.shahe,16);const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'}).addTo(map);let tileErrors=0;tiles.on('tileerror',()=>{if(++tileErrors>2)$('map-tip').textContent='底图暂时不可用，可手动输入坐标';});map.on('click',e=>{$('coordinate-system').value='wgs84';$('latitude').value=e.latlng.lat.toFixed(7);$('longitude').value=e.latlng.lng.toFixed(7);showPoint(e.latlng.lat,e.latlng.lng);$('converted').textContent='已选地图位置，请保存。';});for(const key of Object.keys(campuses))$('campus-'+key).addEventListener('click',()=>viewCampus(key));}catch(e){$('map-tip').textContent='地图未加载，可手动输入经纬度。';}
refresh().catch(e=>toast(e.message));setInterval(()=>refresh().catch(()=>{}),1000);
