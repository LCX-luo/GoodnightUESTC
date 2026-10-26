'use strict';
const $=id=>document.getElementById(id);
// GCJ02 reference points, converted once from the original WGS84 campus presets.
const campuses={shahe:[30.672809763982574,104.1000423138758],qingshuihe:[30.750093670478687,103.9334055836269]};
const map=L.map('map',{scrollWheelZoom:true}).setView(campuses.shahe,17);
const tiles=L.tileLayer('https://wprd0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}',{subdomains:'1234',maxZoom:18,attribution:'&copy; <a href="https://www.amap.com/">高德地图</a>'}).addTo(map);
let loadedTiles=0;
tiles.on('tileload',()=>{loadedTiles++;$('map-status').textContent='国内高德底图 · GCJ-02，选点直接用于学校接口，不重复转换。请核对学校返回的地址。';});
tiles.on('tileerror',()=>{if(!loadedTiles)$('map-status').textContent='底图暂未加载，请检查网络后拖动地图重试。坐标为 GCJ-02。';});
let marker=L.circleMarker(campuses.shahe,{radius:9,color:'#fff',weight:3,fillColor:'#24674f',fillOpacity:1}).addTo(map);
function point(lat,lng,pan=false){$('lat').value=Number(lat).toFixed(7);$('lng').value=Number(lng).toFixed(7);marker.setLatLng([lat,lng]);if(pan)map.setView([lat,lng],17);}
map.on('click',e=>point(e.latlng.lat,e.latlng.lng));
$('shahe').onclick=()=>map.setView(campuses.shahe,17);
$('qingshuihe').onclick=()=>map.setView(campuses.qingshuihe,17);
let started=0,elapsed;
function stopTimer(){clearInterval(elapsed);elapsed=null;}
function begin(){started=Date.now();stopTimer();elapsed=setInterval(()=>{$('timer').textContent=`已用时 ${Math.floor((Date.now()-started)/1000)} 秒`;},500);}
window.onNative=(kind,value)=>{
 if(kind==='qr'){ $('qr').src='data:image/png;base64,'+value;$('qr-panel').hidden=false;$('wechat-cancel').hidden=false;$('wxstatus').textContent='请用绑定账号的本人微信摄像头扫码，并在微信确认授权。'; }
 if(kind==='qrhide'){ $('qr-panel').hidden=true;$('qr').removeAttribute('src');$('wechat-cancel').hidden=true; }
 if(kind==='wxstatus')$('wxstatus').textContent=value;
 if(kind==='location')point(value.lat,value.lng,true);
 if(kind==='progress'||kind==='result')$('message').textContent=value;
 if(kind==='busy'){
  const busy=value==='true';document.querySelectorAll('.actions button').forEach(b=>b.disabled=busy);
  if(busy)begin();else {stopTimer();$('qr-panel').hidden=true;$('qr').removeAttribute('src');$('wechat-cancel').hidden=true;}
 }
};
$('login').onclick=()=>Android.login();
$('check').onclick=()=>Android.check();
$('logout').onclick=()=>Android.logout();
$('wechat').onclick=()=>Android.wechatAuthorize();
$('wechat-forget').onclick=()=>Android.wechatForget();
$('wechat-cancel').onclick=()=>Android.wechatCancel();
function prepare(confirm){
 const lat=Number($('lat').value),lng=Number($('lng').value);
 if(!$('lat').value.trim()||!$('lng').value.trim()||!Number.isFinite(lat)||!Number.isFinite(lng)||Math.abs(lat)>90||Math.abs(lng)>180){$('message').textContent='请输入有效经纬度';return;}
 point(lat,lng);Android.prepare(lat,lng,confirm);
}
$('dry').onclick=()=>Android.check();
$('prepare').onclick=()=>prepare(true);
