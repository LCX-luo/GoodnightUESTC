# 操作票据证据与结论边界

2026-10-23 重新读取学校公开入口，不携带登录会话：

- 入口：<https://jzsz.uestc.edu.cn/daily-checkin-h5/index.html?appId=294>
- 入口引用的脚本：<https://jzsz.uestc.edu.cn/daily-checkin-h5/assets/index-8dl4qBZd.js>
- 下载字节数：504425。
- SHA-256：`edfe5d7a9f20560c4f346196c60665acffee9374aa03d7dd19ce94e906fdf76f`。

原始公开脚本和来源摘要保存在本机 `private-data/h5-research/ticket-evidence-current.js` 与 `ticket-evidence-source.json`。源文件经过压缩，几乎只有一行，可搜索以下字符串。

## 直接观察

脚本定义存储键 `daily-checkin-operation-ticket`，入口从 URL 查询或 hash 查询读取 `checkinTicket`，保存到 `sessionStorage` 并从地址栏清除该参数。请求头辅助函数 `Ow` 从该存储键取值，存在时返回 `X-Checkin-Ticket` 请求头；没有时返回空对象。

前端把 `46001/46002/46003` 作为签到或情况填报操作的授权错误处理：清除票据、提示授权失效，并在小程序环境中返回 `/pages/webview/index` 重新进入授权流程。提示提到停留时间和登录身份变化，但提示本身不是后端 TTL 或绑定规则的实现代码。

2026-10-23 21:25 的单次正式脚本提交，HTTP 200、业务码 46001，提示“请从微信小程序重新进入打卡应用后提交”；回查为 PENDING。该请求没有有效操作票据。脱敏记录只保存在本机 `private-data/last-authorized-submit-diagnostic.json`。

22:02—22:05 在当天已签到的前提下，经本人授权继续对照：缺票据返回 46001；带 MuMu 正常入口取得的票据返回 4006；重复使用及配对同账号另一个有效 SESSION 也返回 4006。每次回查记录 ID 和签到时间均未改变。详情见 [MuMu 路线说明](mumu-session.md)。

## 能得出的结论

票据是当前提交授权链路的一部分。上述对照支持票据能通过电脑 Python 请求使用，在已签到分支不要求原来的那一个 SESSION；这次测试所用 UA 来自桌面配置，并非实际捕获的微信 UA。

后续经另一个账号主人明确授权，在其浏览器会话、未签到状态及核对过的实际位置下，携带原账号票据提交一次，返回 `46003：小程序授权身份不匹配，请重新进入打卡应用`；回查仍为 PENDING，记录 ID 未改变。这有力支持票据校验账号身份。样本本身的完整有效期仍未知。

不能据此确定票据完整有效期、首次成功签到后是否一次性、是否对首次提交另有设备校验，也不能证明后台不检查其他定位或环境字段。仅有前端代码时，更不能断言各个错误码在后端分别对应哪一种绑定条件。浏览器签发入口检查见 [authorization-research.md](authorization-research.md)。
