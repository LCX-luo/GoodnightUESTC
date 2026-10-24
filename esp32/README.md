# ESP32 关键组件与 Agent 部署指引

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

当前任务使用北京时间，在 **21:10–21:14** 的窗口启动每天一次的自动处理，各账号依次执行。设备错过这个窗口不会补签。自动提交前写入按账号和日期的尝试标记，以避免重启或不确定响应后重复发送；失败后应先人工核对。

不带 `--enable-schedule` 重新导入即可关闭调度，并通过 `status` 确认。关闭电脑网页不会停止已经配置好的设备。不要循环调用 `probe --submit-once` 代替调度。

交付前还应验证跨日、断电、断网、会话失效、微信授权失效和多账号执行。分别记录自检、身份匹配、真实提交和复查证据；不要把实验代码描述为已验证的通用产品。
