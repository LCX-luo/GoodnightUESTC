# 浏览器授权链路检查（2026-10-23）

## 本次范围

MuMu 保持关闭。只读取已知正常页面和它们明确引用的公开 JavaScript，不提交签到，不调用身份绑定、注销、短信或修改密码接口，不枚举猜测接口。

## 浏览器正常入口

使用本人获授权的有效浏览器学校会话，GET `/daily-checkin/checkLogin?appId=294` 返回 302，跳转至 `/daily-checkin-h5/index.html`，查询参数只有 `appId`，没有 `checkinTicket`。这仅说明当前这条浏览器入口没有在跳转中提供操作票据，不代表所有服务端授权入口都已检查。

入口响应摘要：本机 `private-data/ticket-research/public-flow/entry-probes.json`，不记录 Cookie 或敏感跳转参数值。

## 检查的公开脚本

| 来源 | 字节数 | 观察 |
| --- | ---: | --- |
| [门户主脚本](https://jzsz.uestc.edu.cn/static/js/app.8821ff1e.js) | 126777 | 无 `checkinTicket`、`X-Checkin-Ticket`、`daily-checkin-operation-ticket`；包含门户微信授权页与身份绑定接口定义 |
| [门户登录模块](https://jzsz.uestc.edu.cn/static/js/login.3cb46c99.js) | 38213 | 从链接接收微信身份参数并进入绑定流程，没有签到操作票据字段；SDK 中其他 ticket 字段不能视作签到授权 |
| [签到 H5 主脚本](https://jzsz.uestc.edu.cn/daily-checkin-h5/assets/index-8dl4qBZd.js) | 504425 | 从入口接收 `checkinTicket`，暂存后通过请求头发送；有授权失败的返回小程序逻辑，未见生成票据的代码 |

门户首页的打包映射明确指定 `login.3cb46c99.js` 为 JavaScript；`8b9f1439` 是对应 CSS 的摘要，不能混淆。上述脚本均由官网页面引用，不是通过猜测后端路由发现。

公开资源副本、SHA-256 和匹配片段仅保存在本机 `private-data/ticket-research/public-flow/`。原有 H5 票据证据见 [ticket-evidence.md](ticket-evidence.md)。

## 与真实响应结合

先前已授权的对照中，同账号票据可以配对另一份有效 SESSION，电脑 Python 请求到达“今日已完成打卡”的业务分支。另一个未签到账号使用该票据，返回 `46003：小程序授权身份不匹配，请重新进入打卡应用`，回查仍为 PENDING。

这支持票据会校验账号身份。它不揭示随机数生成、签名密钥、服务端存储方式或 TTL。

## 结论与下一步条件

本次未找到可在浏览器端复现的票据计算函数，也未找到浏览器正常入口签发此票据的流程。现有证据更符合“外部授权链路提供票据，H5 负责使用”的结构；具体签发方和机制仍不能确认。

若希望继续定位签发方，需要观察官方小程序正常授权时的代码或合法请求响应，或者取得学校提供的接口说明、后端实现或测试环境。当前由于微信已出现安全警告，不继续启用模拟器或注入。仅凭票据长度、样本或错误码，不能可靠还原生成方法。
