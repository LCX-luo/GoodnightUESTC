# ESP32 关键组件与 Agent 部署指引

[手机管理关键代码、Agent 接入教程与踩坑](phone-companion/README.md)

此目录提供实验性的 ESP-IDF 组件、分区示例和 USB 配置工具，供熟悉 ESP32 或使用 AI agent 的读者自行集成。**不提供通用固件，也不能据此认定设备端全链路已可用。** 完整原生取票、真实提交、跨日运行和目标开发板的资源稳定性仍需逐项验证。

只用于本人或明确授权的账号，并遵守学校规定。配置中的地点应为本人实际位置；保存坐标本身不能证明每天人员实际在场。

## 组件做什么

设备使用已授权的微信凭据取得小程序登录 code，经学校接口建立小程序会话，核对学校账号，再申请操作票据。票据用于原签到接口；查询、提交和结果复查分别处理。微信 code、学校会话与操作票据是不同的凭据，不能相互替代。

当前源码包含原生协议实现和测试向量。协议参考 [MioYiSama/moon-uestc](https://github.com/MioYiSama/moon-uestc) 的相关模块；协议或平台变化后必须重新核实。其他实现或其他芯片上的成功，不能替代本组件在你的设备上的验证。

| 文件 | 作用 |
| --- | --- |
| `components/checkin_runtime/protocol.cpp` | 密码算法、消息编码、微信协议与网络传输 |
| `components/checkin_runtime/checkin_service.cpp` | 配置、账号核对、学校会话与票据、任务调度及 USB 命令 |
| `components/checkin_runtime/include/checkin_service.h` | 组件启动入口 |
| `components/checkin_runtime/include/protocol_vectors.hpp` | 不含真实账号的交叉语言测试向量 |
| `partitions.csv` | 分区布局示例，不能直接用于所有开发板 |
| `provision.py` | 从电脑账号库通过 USB 导入配置及执行诊断 |

## 先让 Agent 检查环境

实现以经典 ESP32、ESP-IDF 5.1.2 为适配起点，不依赖 PSRAM。ESP32-S3 等型号、其他 IDF 版本和不同 Flash 容量都应单独验证。不要直接更改芯片目标后假定能够工作。

可以把下面这段交给你的 agent：

> 先只读识别开发板芯片、Flash、PSRAM、串口和现有分区。为我创建自己的 ESP-IDF 工程，接入 checkin_runtime 组件。检查组件依赖、C++ 异常、AES-192 软件实现、证书包、网络和 SNTP；规划独立的 checkin NVS 分区，不覆盖已有数据。刷写前备份并记录哈希。默认不启用定时任务，先验证启动自检、内存、联网、USB 导入和只读取票，再等待我核对账号及实际位置后，进行一次真实提交和结果复查。不要输出、提交或分享凭据、私有配置和含密钥的固件。

## 新建自己的工程并接入

在已加载 ESP-IDF 环境的终端中创建工程，将 `components/checkin_runtime` 复制到工程的 `components` 目录，或通过 `EXTRA_COMPONENT_DIRS` 引用它。主组件的 `idf_component_register` 加上 `REQUIRES checkin_runtime`。

组件声明的依赖包括 `esp_wifi`、`esp_http_client`、`esp-tls`、`mbedtls`、`json`、`nvs_flash`、`lwip` 与 `esp_timer`，使用 C++17。主工程负责网络接口、事件循环、Wi-Fi 配置与连接；组件不会替你创建 Wi-Fi 登录页面。

初始化网络之后调用一次：

```c
#include "checkin_service.h"

// 完成自己的 NVS、网络接口、事件循环及 Wi-Fi 初始化。
checkin_service_start();
```

不要重复初始化默认网络栈或反复调用组件启动。组件随后等待网络与时钟就绪，使用北京时间和 SNTP。

核对至少这些配置：

```ini
CONFIG_COMPILER_CXX_EXCEPTIONS=y
# CONFIG_MBEDTLS_HARDWARE_AES is not set
```

该协议涉及 AES-192。本适配使用软件实现，关闭 `CONFIG_MBEDTLS_HARDWARE_AES`；不要仅凭芯片提供 AES 加速就直接开启。还应确认工程包含 HTTPS 所需的证书包支持，以及源码所需的密码算法配置。

构建前用 `idf.py set-target` 选择自己的芯片，再进行 `menuconfig` 和 `idf.py build`。Windows 下建议使用 ASCII 工程路径；部分旧工具对中文路径支持有限。

## 分区、备份与资源

组件使用名称为 `checkin`、类型为 `data`、子类型为 `nvs` 的独立分区。`partitions.csv` 只是 4 MB Flash 的示例布局，包含较大的 factory 应用区和签到配置区。应由 agent 按实际固件大小及原分区重新规划，检查偏移、大小、对齐和是否重叠，**不能直接照抄偏移刷写**。

首次刷写前完整备份设备 Flash，记录文件大小与 SHA-256，并确认恢复方式。备份和构建产物可能包含敏感配置，保存在 Git 忽略的私有目录。用当前工程生成的 `flasher_args.json` 核对刷写参数，不要直接擦除整片 Flash。

组件当前创建约 16 KB 的工作任务栈和 6 KB 的 USB 任务栈，真实运行还需要 TLS、协议缓冲与 JSON 内存。启动及认证期间检查空闲堆、最大连续空闲块、任务栈余量和其他任务响应。`native_self_test_passed` 只能证明本地向量检查通过；编译成功或自检成功都不能证明远端认证成功。

## 在电脑准备账号库

按仓库主 README 启动网页并打开 `/accounts`。每个账号分别完成学校登录、本人绑定微信授权、地图选择实际地点，最后点击“保存添加到库”。最多导入四个资料完整且已保存的账号，草稿不会导入。

账号库和本地密钥在 `private-data`；不要分享该目录、原始抓包、二维码、Cookie、票据或刷新凭据。USB 工具在内存中解密账号资料并发送，不另存明文导出文件。

设备端 NVS **默认明文存储**，没有自动启用 Flash/NVS 加密，也不会烧写 eFuse。能读取设备 Flash 的人可能获得凭据，不能把它称为硬件安全存储。微信授权也不是永久有效：用户撤销、风控、刷新失效或平台变化后仍需重新授权。学校会话的重建逻辑也必须通过实际测试，不能承诺永久无人值守。

## USB 导入与只读验证

电脑使用本仓库的 Python 环境，另需 `pyserial`。以下命令在仓库根目录执行，`COMx` 和 `SCHOOL_ID` 由你替换；Linux/macOS 使用自己的串口名称。配置工具与串口 monitor 不要同时占用设备。

查询调度开关：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx status
```

导入完整账号资料，**默认保持调度关闭**：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx import
```

加 `--account SCHOOL_ID` 可以只导入一个账号。导入替换设备上的整份账号配置，不会自动追加到旧配置；电脑资料变化后应重新导入。请先等待当前任务结束再导入配置。

仅验证账号身份与取票、不提交签到：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx probe --account SCHOOL_ID
```

“只读”指不写入签到记录；此流程仍会访问真实微信和学校认证接口，刷新并保存凭据。新取得的小程序会话必须核对绑定学号与配置一致，不能将不同微信绑定身份当成原账号继续运行。

## 一次真实提交与结果判断

确认账号主人授权、本人的实际地点与学校允许时段后，才运行：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx probe --account SCHOOL_ID --submit-once
```

这是一次真实签到写请求，组件仍会检查学校时段与位置范围，不会自动重试。USB 超时或网络结果不确定时，先查看学校当天状态，不要直接再次提交。

| 状态 | 应如何理解 |
| --- | --- |
| `profiles_saved` | 配置已保存，不代表远端凭据有效 |
| `authorization_verified` | 本次身份核对与取票成功，没有提交签到 |
| `request_accepted` | 学校接受请求，仍需结果复查 |
| `request_rejected` / `school_rejected` | 学校拒绝，保留并查看实际业务码 |
| `checkin_confirmed` | 提交前待签到，本次被接受，随后查询到已签到 |
| `existing_record_only` | 仅确认已有当天记录，不能证明本次票据有效 |
| `result_unknown_no_retry` | 结果未确认，不自动重发 |

`46001`、`46002`、`46003`、`46004` 等业务码需结合当前接口解释。已签到账号重复返回“已有记录”，不能替代未签到账号的有效提交测试。

`wifi_or_clock_unavailable` 时先修复网络或校时；`insufficient_heap`、`out_of_memory` 时检查资源；`outside_checkin_window` 或 `outside_allowed_location` 表示条件未满足。不要把错误信息统一解释为票据失效。

## 显式开启每日 21:10

先完成设备取票、一次正常提交、结果复查和并行任务资源测试，再显式启用：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx import --enable-schedule
.\.venv\Scripts\python.exe esp32\provision.py --port COMx status
```

当前任务使用北京时间，默认 **21:10–21:15（结束时刻不包含）**，各账号可分别设置起止时间。窗口内每隔至少 60 秒重新检查，已完成后停止。仅在明确未提交的时段检查失败，或学校明确返回“当前不在打卡时间段内”且回查仍为 PENDING 时继续；授权失效、其他拒绝、已接受待确认或结果未知均停止当天自动任务。每次尝试前将停止状态写入 NVS，断电不会重发结果未知的提交；每次新尝试都重新取票。错过窗口不会补签。

不带 `--enable-schedule` 重新导入即可关闭调度，并通过 `status` 确认。关闭电脑网页不会停止已经配置好的设备。不要循环调用 `probe --submit-once` 代替调度。

交付前还应验证跨日、断电、断网、会话失效、微信授权失效和多账号执行。分别记录自检、身份匹配、真实提交和复查证据；不要把实验代码描述为已验证的通用产品。


## 通用本地管理 API（实验）

组件提供 `checkin_service_set_listener(callback,user)` 和 `checkin_service_handle_request(json)`。它们不创建服务器、不连接消息代理，也不提供身份认证。主工程必须先完成自己的加密、认证和防重放验证，再派发管理请求；回调也应经原有加密通道返回。回调可能来自调用线程或工作任务，请立即复制 JSON，避免在回调内再次调用管理 API。

请求 JSON 最长 180 字节；若外层还带前缀，应把前缀算入现有传输的长度限制。`id` 使用 8–32 位纯字母数字。状态与账号列表即时返回；学校查询、授权刷新和提交进入单一工作队列。提交没有自动网络重试，工作任务请求在未完成 SNTP 同步时停止。

| 操作 | 请求主要字段 | 行为 |
| --- | --- | --- |
| `status` | `id,op` | 校时、联网、内存、全局开关、默认计划与账号数 |
| `list` | `id,op,a` | 按索引分页返回一个账号、GCJ-02 位置、`autoEnabled/hour/minute/end` 和上次结果 |
| `query` | `id,op,a,sid` | 只查询学校当天记录 |
| `refresh` | `id,op,a,sid` | 更新已有授权与学校会话，并验证取票；不提交签到 |
| `submit` | `id,op,a,sid` | 以设备保存的位置提交一次，并读取结果；接入端必须先让本人核对实际位置 |
| `schedule` | `id,op,enabled,hour,minute` | 设置全局开关及默认时间 |
| `edit` | `id,op,a,sid`，另附待更新字段 | 仅允许 `enabled`、成对的 `hour/minute`、结束分钟 `end`、成对的 `lat/lng` |
| `delete` | `id,op,a,sid` | 删除一个账号；不会删除其他账号 |

`a` 为从零起的索引，`sid` 是该索引对应的学号；操作前再次核对配对，避免列表重排后操作错误账号。全局开关必须开启且该账号也开启，才会自动处理。旧配置缺少账号开关时兼容为开启；通过下述完整包新建的账号始终默认关闭。账号可设置自己的时间，否则使用全局默认时间。`end` 是从午夜起的结束分钟（1–1440），必须晚于该账号开始时间；未设置时默认为开始后五分钟。跨午夜时段暂不支持。停止状态跨重启保留，次日重新判断。

`refresh/submit/schedule/edit/delete/put_commit` 使用 NVS 保存请求 ID，重复请求不会再次执行。状态轮询与只读查询不会为每条消息写入 NVS。请求 ID 存储不足或提交前持久化失败时，写操作停止，不能静默降级为不去重。

回调包含 `id/op/phase/ok/code/state`。`phase=accepted` 只表示任务已接收，`progress` 是中间状态，`done` 才是该请求的终态。因异步调度可能发生事件先后变化，接入端收到 `done` 后应忽略同 ID 后到的中间状态。结果中不包含票据、Cookie 或微信凭据。学校提示经过长度限制和敏感串剔除；应保留实际业务码与提交前后状态，不可把已有记录当成本次成功。

### 完整账号包上传

完整资料只在主工程的已认证加密通道中传输，不能经过日志、剪贴板、明文文件或未经保护的消息主题。手机等接入端应先完成真实学校登录、微信授权、账号匹配和位置确认，再上传。设备取码后仍会核对学校返回的绑定学号。

上传采用一条在途事务，最长 6000 字节，120 秒单调时钟超时：

1. `put_begin`：`{id,op,t,len,a,sid}`，`t` 为随机传输 ID；`a=-1` 表示新建，其他值表示更新原账号。
2. `put_chunk`：`{id,op,t,n,b}`，`n` 从零开始；`b` 是最多 64 个原始字节的 Base64，末片按剩余长度。相同传输、相同序号且内容一致的重复片可安全确认。
3. `put_commit`：`{id,op,t,sha256}`，`sha256` 为原始完整包的 64 位小写十六进制 SHA-256。

完整 JSON 包字段如下（这里只描述结构，不放任何真实材料）：

```text
student_id
schoolSession
wechat: openid, access_token, refresh_token, expires_at
location: latitude, longitude, coordinate_system="gcj02"
enabled: false
scheduleMinute: 从午夜起的分钟数，默认 1270
```

提交时检查包长、完整分片、哈希、字段白名单、学号配对和最多四个唯一账号，随后整套替换；会话、微信凭据与位置不从不同记录混合。只有持久化成功并返回 `account_saved` 才能提示保存完成。失败、完成或超时会清理传输缓冲；设备默认明文 NVS 的限制仍然存在。

上传和普通管理回调都不回显完整包。集成者应验证自身认证层、消息长度、QoS 重复、超时、掉电和索引变化，而不是把本地模拟测试当成实际远程管理已经通过。

### 手动测试与本地诊断

管理 `submit` 每次点击都重新取票并发一次正式请求，不因本地当天状态、学校时段或围栏预检跳过；身份绑定和请求认证仍保留。学校拒绝、已有记录、接受待确认和本次新建成功分别展示。地址反查用于构造提交体，不能用模拟字段证明人在该位置。

USB 原有 `GN1` Base64 JSON 还支持 `{op:"manage",request:{id,op,...}}`，仅供可信物理串口诊断。脱敏管理回包以 `GN2 ` 开头，字段与网络回调一致；不输出授权材料。设备凭据管理须限制物理访问。账号授权更新保留设备已有开关及起止时间。
