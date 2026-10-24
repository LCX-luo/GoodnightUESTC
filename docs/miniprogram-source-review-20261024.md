# 智慧学工本地源码与独立取码方案审阅

日期：2026-10-24。仅静态读取本地材料和公开参考仓库，没有启动微信、开启 Root、调用取票接口或提交签到。

## 材料与来源

- 本地 `源码/56/dec.wxapkg_dir/app-service.js`：3027001 字节，82093 行，SHA-256 `1b90fbfd780089be4103404563a73689029b66b56bb581e7cbc60fee50df1f69`。
- 本地 `源码/51/dec.wxapkg_dir/app-service.js`：3147685 字节，85417 行，SHA-256 `402d8853a7bd07bc6aec31b2563ae389115878efdaa759601991bb36c1743460`。
- 文件夹名 51/56 只作为材料标识，不据此判断微信版本或服务端上线时间。
- 当前公开 [UESTC-MoonCheck](https://github.com/richard297779/UESTC-MoonCheck)，下载时 HEAD 为 `3fbc75310b611218b3f864227322f0c4637b599c`，私有只读参考副本位于 `private-data/mooncheck-current/`。

## 56 材料确认的执行链

| 源码位置 | 观察 |
| --- | --- |
| app-service.js:55957 | `isCheckinTarget` 限定学校域名及 daily-checkin-h5 路径，包含测试路径匹配；这是客户端选路条件，不等于测试服务可用或免授权 |
| app-service.js:55970 | `requestCheckinTicket` 是授权取票函数 |
| app-service.js:55984 | 调用 uni-app 封装的 `login({provider:'weixin'})`，从成功回调取得微信 code；此处没有 code 计算算法 |
| app-service.js:56000 | 使用 `{code: r}` 请求 `/api/auth/checkin-ticket` |
| app-service.js:49131 | 请求拦截器为相对路径添加平台基址 |
| app-service.js:57381 | 基址为 `https://jzsz.uestc.edu.cn/platform-app`，因此完整取票路径为 `/platform-app/api/auth/checkin-ticket` |
| app-service.js:49158 | 拦截器添加 `platform`，读取本地 sessionId 并构造 `Cookie: SESSION=...` |
| app-service.js:57428 | 小程序 platform 值为 `mp-weixin` |
| app-service.js:56003 | 取票函数检查响应 `ok`；失败使用学校返回的 msg，并记录阶段和业务码 |
| app-service.js:56009 | 校验 ticket 符合 `[A-Za-z0-9_-]{43}`，随后原样返回 `data.ticket`；43 字符不能证明随机源、签名算法或密钥长度 |
| app-service.js:78911 | WebView 入口识别到签到目标后，先调用取票函数 |
| app-service.js:78925 | 将学校 sessionId 与新 ticket 一起交给 buildWebviewUrl |
| app-service.js:58243 | buildWebviewUrl 将 sessionId、checkinTicket 添加到主 URL 查询参数，保留 hash 路由 |
| app-service.js:78974 | 页面 onLoad 执行授权入口；失败时呈现错误和重试入口，并非一个已证明持续后台刷票的服务 |

该取票函数没有单独调用 code2Session，也没有读取或计算学校票据密钥。若学校内部进行微信身份交换，是服务端行为，不能从这个前端函数还原。

原生定位页经 getLocation 流程获取坐标，再回到通用 WebView 入口（77990—78007 行）；该入口会按签到目标再次执行授权。因此仅复制定位回调 URL 或替换 User-Agent，不等于完成授权。

学校平台登录也有独立微信流程（76978 行起）：调用登录能力，执行 checkWechatBind，保存返回的 sessionId，并按 bind/authorizeUrl 状态继续。它与签到操作票据是不同环节，不应把一次已消费 code 同时用于多个交换请求。

51 材料的 app-service.js 未匹配 checkinTicket/requestCheckinTicket 等已知取票字段。这里只记录文件差异，不据此判断整个历史平台是否没有授权要求。

## 对 ESP32 自主微信协议客户端说法的判断

用户提供的方案文字声称扫码取得长期凭据、直接 MMTLS 取学校小程序 code。当前未提供可复核实现，不能当作已验证成果。

需要区分四个能力：

1. 实现 ECDH/AES-GCM 等密码运算。
2. 实现当前版本的完整微信传输和业务消息格式。
3. 正常建立、刷新微信身份，并在正确的小程序上下文取得服务器认可的登录 code。
4. 学校为对应账号签发票据，完成一次有效提交、回查与后续跨日运行。

完成第 1 项不代表第 2—4 项完成。扫码授权的具体对象、凭据范围和刷新条件也不能从“应用宝凭据”五个字推断。普通微信网页登录授权码、自建小程序的 code、学校小程序的 code 并非可直接互换。

2024 年 [Citizen Lab 的 MMTLS 原始研究](https://citizenlab.ca/research/should-we-chat-too-security-analysis-of-wechats-mmtls-encryption-protocol/)在其测试版本中观察到 MMTLS 外层及独立业务层加密，说明不能把微信协议客户端等同于几次标准密码库调用；该研究不直接证明当前微信版本的全部实现。

MoonCheck 当前 README 明确记录停服，并称抓票后提交曾可行；公开树中未找到 MMTLS、wx.login 或新取票接口的实现。它提供旧业务链路参考，不能作为上述独立微信客户端方案已完成的证据。

## 电脑端、Android 端恢复条件

两端都可以实现正常 HTTPS 取票请求、账号隔离、加密保存、到期处理及单次提交，但目前仍缺可靠的微信 code 来源。普通浏览器和独立 Android APK 没有学校小程序上下文中的 wx.login 能力。

取得本人在正确小程序上下文产生的未消费 code 后，学校登录、取票和提交可由常规 HTTP 客户端承接；仍须实测账号绑定和服务器规则，不能仅凭字段一致宣称恢复。只有票据的伴随方案则继续使用同账号票据并在到期前完成一次明确授权的操作。

用户另行提供的 46004 响应表示授权已使用或结果待确认。现有源码快照未定义服务端消费时点，故新实现应保守处理：提交一次后先回查，46004/超时/不明响应均不自动换票重发。此前已签到分支返回 4006 不证明新签到可重复消费同票据。

当前适合继续的工作是核验独立取码方案的真实代码与运行边界，并将正常授权提供方与学校 HTTP 客户端分离；不是修改 platform 头、伪造 code 或继续尝试旧账号票据。
