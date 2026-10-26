# 手机管理 ESP32：关键代码与 Agent 接入教程

仅限本人或明确授权的账号及实际位置，遵守学校规定。这里提供可复用的管理逻辑与接入边界，不是完整 App、通用固件或无人值守成功承诺。服务地址、通信密钥、设备标识、账号及配置均由使用者自行提供。

## 交给 Agent 的任务

> 先阅读本教程、上级 ESP32 管理 API 和仓库 Android 授权源码，再检查我的现有 App 与固件。复用已有连接，接入已认证、加密并防重放的管理命令。保持原有设备功能。先做禁用合成账号的增删改查、分片传输和掉线测试，再由我正常登录和扫码更新本人账号。每项注明模拟、真机或未验证；不把私钥、账号、抓包、APK 或设备配置提交仓库。

## 文件怎么用

| 文件 | 用途 |
| --- | --- |
| `android/SecureManagementCodec.kt` | 独立工程的 AES-GCM / HMAC-SHA256 消息编解码，密钥从本地配置注入 |
| `android/CheckinProtocol.kt` | 180 字节以内的命令、账号绑定、完整包分片与 SHA-256 |
| `android/CheckinRepository.kt` | 账号列表、CRUD、传输确认、结果状态机、超时与序列号校准反馈 |
| `android/CheckinScreen.kt` | Compose 管理页面，起止时段及手动单次提交 |
| `native/AccountEditorActivity.java` | 学校登录、微信扫码、地图与原生账号导出页面 |
| `native/WeChatAuth.java` | 已验证的 0.2.4 授权流程，加上短时、身份配对的设备资料导出 |
| `native/AccountDraftHandoff.java` | 进程内一次性句柄，Activity result 不传凭据 |
| `native/assets/` | 账号编辑页面关键资源；地图 vendor 文件复用仓库已有资源 |
| `transport/management_channel.c/.h` | 与具体网络无关的发送队列与已认证命令分派 |

代码没有配置消息服务器，也没有生成共享通信密钥。Kotlin 命名空间可改为接入 App 的名称。原生 Java 与本仓库授权类需处于同一包；Agent 更改包名时应一起调整。

## 手机端接入

1. 项目需要 Kotlin、Compose Material3、协程、`org.json`；原生授权沿用本仓库 `android` 的 Chaquopy/Python 和已审查协议模块。以实际工程版本为准，不照搬机器路径。
2. 从本仓库 Android 源码复用 `AuthSession`、`SchoolClient`、`Coordinates`、`LoginActivity` 和 `native_auth.py`，授权类使用本目录 `native/WeChatAuth.java`。用仓库脚本准备受审查的协议模块及地图 vendor 资源；不要用无法追溯的缓存包替代。
3. 注册 `AccountEditorActivity` 和 `LoginActivity`，均设置 `exported=false`；配置网络权限。若现有 App 的 assets 有同名文件，移动到独立子目录，并同步修改 Activity 的本地 URL、资产路径和 CSP。
4. 在 ViewModel 中创建一次 Repository，避免重组时重建任务：

```kotlin
val repository = CheckinRepository(
    viewModelScope,
    connected = { myChannel.isConnected },
    send = { body -> myChannel.sendAuthenticatedEncrypted(body) }
)
// Compose: CheckinScreen(connected, repository, ::openAccountEditor)
```

`myChannel` 是 Agent 为实际 App 接入的接口，不是这里提供的类。返回 true 只表示本地成功交给传输层，不能表示设备已保存。

5. 收到已验证的管理明文 JSON，调用 `repository.receive(JSONObject(json))`。收到原通道签名序列号错误的确认时，先更新传输层序列号，再调用 `repository.transportSequenceRejected()`，结束等待并要求用户重新点击，不能自动重发签到。
6. 新增账号不传设备索引；更新账号时保留索引并传入 `expected_sid`，可附原 `latitude/longitude`。通过 Activity result 取得 `verified_account_handle`，立即删除 Intent 里的句柄，再调用 `AccountDraftHandoff.take(handle)`，成功后交给 `repository.importAccount(raw, indexOrNull)`。不要把原始 JSON 写进 Intent、Bundle、WebView、剪贴板或日志。
7. 导出前会再次正常取票，检查学校会话、学校身份与缓存微信资料配对；导出的是完整账号包，**不包含操作票据**。确认 `account_saved` 后才显示同步成功。更新保留设备原有启停和时段；新账号自动关闭。

编辑页的提交按钮只导出账号包，实际签到始终交给 ESP32。不要把原独立签到 App 的提交按钮接到账号编辑页。

## 固件与消息通道

先启动 `checkin_service_start()`，再调用 `management_channel_init(sender, context)`。`sender` 负责用自己的安全通道发送管理事件。网络实现可以不同，但必须做到：

- 收到命令后先解密、验证身份与防重放，再调用 `management_channel_verified_command(plaintext)`；`CI:` 分派应在原普通 JSON 解析之前。
- 返回事件须加密认证，不保留消息，不打印正文，不把请求成功入队当成学校签到成功。
- 管理发送采用独立有界队列，不能在设备本地操作回调内直接等待网络连接。消息丢失时手机应保持未确认并查询，不提示保存成功。
- 服务地址、端口和 TLS 必须匹配；两端接到不同服务器，即使都显示已连接也不能互通。先做连接握手与只读状态测试。
- 服务不可达先区分 DNS、TCP、TLS、订阅和业务回包，不要因此重新扫码或刷空 NVS。换第三方服务前征得使用者同意。

协议、字段、分片大小、请求 ID、账号索引与学号绑定见 [管理 API](../README.md#通用本地管理-api实验)。同账号的 Cookie、微信凭据和位置必须整套配对替换。凭据只走已认证加密通道，不提供公共下载或聊天导出。

## 时间与提交逻辑

设备按北京时间工作，必须 SNTP 实际同步成功。默认开始 1270、结束 1275，即 21:10–21:15，结束时刻不包含。每账号可改 `hour/minute/end`；不支持跨午夜窗口。全局开关与账号开关都启用才自动执行。

自动任务间隔至少 60 秒，每次重新取票、先查询当天记录。已完成即停止；仅明确可重试的未提交情形继续。授权失效、其他拒绝、已接受待确认或未知结果均停止当天任务。尝试前持久化停止状态，断电不会重发未知写操作，次日重新判断。

手动“立即测试一次签到”不按本地已有记录、学校时段或围栏预检跳过；点击一次申请新票据并提交一次，学校负责业务判断。界面分别展示实际返回码、文字、是否接受及提交后记录。已有记录不能当成本次新建成功。

## 已踩过的坑

| 现象 | 原因与处理 |
| --- | --- |
| 切到微信再回来二维码消失 | Activity 销毁时取消了任务或重放顺序清除了二维码；任务归进程所有，界面仅 attach/detach，显式取消才终止 |
| 微信显示已授权，App 一直等待 | 二维码轮询连接中断；对同一二维码做有限重连，记录固定阶段，不盲目生成新二维码 |
| 截图从相册无法扫码 | 某些授权二维码要求摄像头，需另一屏展示；不能承诺截图或直接跳微信一定可用 |
| 其他地方重新授权后旧凭据失效 | 服务端返回 -101、-109；-101 最多强制刷新一次并先持久化；-109 正常扫码更新，停止循环 |
| 设备重启后请求没有业务回包 | 原签名序列号可能归零；使用已验证 ACK 校准，结束该次等待，重新人为发起 |
| 网络不通连 USB 管理也卡住 | 回调内调用网络发送等待客户端锁；独立有界队列发送，不阻塞本地操作 |
| 显示保存但设备没更新 | 只收到传输 ACK 或 accepted；必须等 put_commit 的 account_saved 才成功 |
| 授权更新后计划被重置 | 手机导出默认关闭字段覆盖旧计划；设备替换资料时保留已有计划 |
| 返回4006就认为已验证所有校验 | 必须保留文字与前后状态；本次4006是时段外，不是签到成功 |
| 编译器/Gradle 在 Windows 临时目录报错 | 使用项目内临时目录；旧 Ninja 中文路径问题可用项目内短路径映射，勿修改原工程或扩大删除范围 |
| Root或抓包证书导致微信异常 | 本方案不需要这些操作；沿用正常学校登录和扫码授权，不隐藏 Root 或解除证书校验 |

## 本轮证据与边界

2026-10-26，私人测试工程的手机授权更新、设备接收完整资料、板上取码/取票和单次提交已实测。学校在时段外返回4006“当前不在打卡时间段内”，前后PENDING；随机票据对照返回46002“小程序授权已过期，请重新进入打卡应用”，前后PENDING，均无新增签到。

已做禁用合成账号的真实 USB/加密 MQTT 全套 CRUD 与分片测试；手机管理逻辑13项模拟测试通过。这里抽出的通用参考源码没有独立宿主工程，Agent 仍须在接入项目中编译、检查原有功能并实测。时段内新建签到、真实自动执行及跨日仍待验证。

## 完整独立固件的传输格式

仓库 `esp32/main` 是独立宿主，使用 `SecureManagementCodec.kt`，不依赖任何使用者原项目。

- AES 密钥与 HMAC 密钥分别为本地生成的32字节；命令 AAD 为 `goodnight-management-command-v1`，事件 AAD 为 `goodnight-management-status-v1`。
- 命令明文 `{seq,body,sig}`，`body` 是 `CI:` 加紧凑 JSON，`sig=HMAC-SHA256(signingKey, UTF8(seq+":"+body))`，小写hex。再以随机12字节 nonce 做 AES-GCM，16字节tag；外层 `{v:1,type:"command",data:base64(nonce+ciphertext+tag)}`。
- 事件解密后 `{kind,payload}`，外层 type 必须等于内部 kind；ack 的 payload 含 `seq_ok/next_seq`，ci 的 payload 交给 Repository。
- 设备在执行前把下一序列号写入 NVS，重启不归零；客户端序列号不同步先按有效 ACK 校准，再由本人重新发起操作，不能自动重发签到。
- 本地生成的 `phone-management.local.json` 包含密钥，只能私下配置到本人手机，不加入仓库或聊天。

这个独立传输层完成真实 ESP-IDF 编译，但与手机的独立宿主硬件联调仍需执行；不要把此前其他宿主的真机成功当成它已经上板通过。
