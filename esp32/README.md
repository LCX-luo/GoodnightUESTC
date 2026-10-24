# ESP32 与现有空调遥控器合并原型

这里是实验性的 ESP-IDF 组件，不是可以直接烧录到任意开发板的成品。它复用现有空调项目的 Wi-Fi、MQTT 与红外控制，在独立任务中实现微信取码、学校取票和签到。电脑只负责配置；凭据有效期间，设备可以独立运行。

当前已完成原生协议实现、交叉语言测试向量生成和合并固件编译。原生向量已在设备自检通过，原空调 Flash 已在本地备份；首版合并固件已刷写，Wi-Fi/MQTT 连接、两个账号 USB 导入通过，自动调度关闭。**这些结果不等于设备已完成有效签到，也不等于空调并行运行已验证。** 旧学校会话已过期；电脑已只读证明微信凭据可重建新会话。按此修订的设备版本已编译，完整取票、提交、空调回归和跨日测试仍待验证。其他项目或其他芯片的成功记录不能代替本设备验证。

只用于本人或明确授权账号，并遵守学校规定。地图中保存的地点应为本人实际位置；配置并不能证明人员每天实际在场。请先逐账号人工验证，再决定是否开启定时任务。

## 硬件与限制

本次适配对象是经典 ESP32 双核芯片、4 MB Flash，未依赖 PSRAM；开发环境为 ESP-IDF 5.1.2。ESP32-S3 等型号需要单独适配和验证，不能直接使用经典 ESP32 的二进制文件。

- 原空调固件保留控制逻辑与 GPIO；签到共享原 Wi-Fi，不重新建立网络栈，不通过公共 MQTT 传输账号材料。
- 原型支持 1–4 个资料完整的账号，依次运行。
- 原生协议使用 AES-192 等算法。本适配关闭 `CONFIG_MBEDTLS_HARDWARE_AES`，由软件完成运算；不要仅凭芯片有 AES 加速就重新开启。
- 最新代码通过微信 code、check-bind 建立新学校 SESSION，严格核对学号后再查询与取票。该重建链已在电脑只读验证，设备完整链仍待验证；没有 CAS 密码自动登录。
- 微信授权可以刷新，但不是永久授权；撤销、风控、接口变化或刷新凭据失效仍需重新扫码。
- 新签到分区默认是**明文 NVS**。没有启用 Flash/NVS 加密或烧写 eFuse，不应称为硬件安全存储。能读取设备 Flash 的人可能获得账号凭据。
- 合并固件与私有构建配置包含原空调项目的 Wi-Fi 或控制密钥，不能上传、发送给其他人。每个人应从自己的配置构建。

## 文件入口

| 文件 | 作用 |
| --- | --- |
| `../prepare_esp32.py` | 复制原空调源码、生成私有配置与合并工程，编译后收集产物；不会自动刷写 |
| `components/checkin_runtime/protocol.cpp` | 原生微信协议、密码算法、消息编码与网络传输 |
| `components/checkin_runtime/checkin_service.cpp` | 账号配置、取票、时段与范围检查、USB 命令和定时任务 |
| `components/checkin_runtime/include/protocol_vectors.hpp` | 不含真实账号的交叉语言测试向量 |
| `partitions.csv` | 保留原 NVS/PHY 偏移并扩大应用区，新增签到 NVS |
| `provision.py` | 从电脑账号库直接通过 USB 导入，或启动只读/提交诊断 |

## 先准备电脑账号库

按仓库主 README 启动网页，打开 `/accounts`。每个账号分别完成学校登录、绑定本人微信扫码、地图选择实际地点，最后点击“保存添加到库”。未保存的草稿或缺少会话、微信授权、位置的账号不会导入。

账号库与密钥都保存在本机 `private-data`。不要把该目录、抓包或整个开发工作区发给别人。导入程序在内存中解密并通过 USB 发送，不额外生成明文凭据文件；这不改变设备端 NVS 默认明文的限制。

## 让 AI agent 适配你的现有空调项目

`prepare_esp32.py` 当前按照开发者本机目录编写，**不是通用安装器**。让接手的 agent 先只读检查原工程，再调整脚本中的 `OLD`、IDF 根目录、IDF Python 环境及工具路径。不能直接把别人的空调固件刷到自己的板上。

建议给 agent 的任务如下：

> 检查芯片型号、Flash 大小、现有分区、GPIO、Wi-Fi 和 MQTT 初始化方式。先完整备份原 Flash 并校验哈希。在原工程之外复制源码，将 checkin_runtime 作为组件接入，并在原网络初始化之后调用 checkin_service_start()。核对注入位置及原空调 MQTT 重连逻辑，避免重复初始化。保留原 NVS/PHY 偏移；先编译和检查分区，再仅刷写必要区域。先保持签到调度关闭，逐项验证空调、只读取票和一次人工确认提交，最后才启用调度。不得输出账号、密码、Cookie、票据或协议凭据。

当前脚本通过文本替换插入组件调用，原空调代码结构变化后，必须检查生成的 `main.c` 与 `CMakeLists.txt`，确认实际插入成功。编译通过并不能证明启动入口已接入。

构建命令在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe prepare_esp32.py --build
```

脚本复制原空调源文件到 `private-data/esp32-ac`，在系统临时目录建立带归属标记的 ASCII 路径工程，以兼容该 IDF/Ninja 对中文路径的限制。成功后，产物位于 `private-data/esp32-artifacts`。原空调项目不被修改；私有副本和临时构建目录均可能含有密钥。

## 备份、分区和刷写

先关闭其他串口工具。以下 `COMx`、IDF Python 和备份文件名都是占位示例，必须由 agent 按实际环境替换。完整备份应位于被 Git 忽略的私有目录。

在已加载 ESP-IDF 环境的终端中，确认板子确实为 4 MB Flash 后：

```powershell
python -m esptool --chip esp32 --port COMx flash_id
python -m esptool --chip esp32 --port COMx read_flash 0x0 0x400000 original-full-flash.bin
Get-FileHash -Algorithm SHA256 original-full-flash.bin
```

连接失败时，可按住 BOOT，按下并松开 EN/RESET，继续按住 BOOT，在工具开始连接后松开；必要时在 esptool 参数中使用 `--before no_reset`。不要把“无法进入下载模式”解释成固件损坏。

本适配的分区布局是：

| 分区 | 偏移 | 大小 |
| --- | --- | --- |
| 原空调 NVS | `0x9000` | `0x6000` |
| PHY | `0xf000` | `0x1000` |
| 合并 factory 应用 | `0x10000` | `0x280000` |
| 签到专用 NVS | `0x310000` | `0x40000` |

原应用区为 1 MB，合并应用约 1.12 MB，因此需要扩大应用分区。**只有原设备分区与这里的保留区域一致时，才能直接使用这份布局。** 其他设备必须重新规划。

确认备份可以读取、哈希已记录、产物适合当前芯片和分区之后，仅写入：

- Bootloader：`0x1000`
- 分区表：`0x8000`
- 合并应用：`0x10000`

具体文件和刷写选项应从本次构建的 `flasher_args.json` 核对。不要运行 `erase_flash`，不要覆盖原空调 NVS，也不要刷入其他项目的预编译固件。烧录完成不代表原空调功能已恢复，应立即检查启动、联网、MQTT 和实际红外控制。

如果发生启动循环、空调失效或无法解释的回归，先停止签到测试，使用相同芯片设置把完整原始备份写回 `0x0` 并验证空调恢复；不要在没有可靠备份时继续覆盖尝试。完整备份同样含有敏感材料。

## USB 配置与测试

电脑项目环境需安装 `pyserial`。以下命令在仓库根目录运行，串口按实际替换。不要同时开启 IDF monitor、串口终端与配置程序。

查询状态：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx status
```

导入资料齐全的账号，**默认不启用调度**：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx import
```

最多导入四个账号。使用 `--account SCHOOL_ID` 可只选一个账号；重新导入会替换设备保存的整份账号配置，不是向旧配置追加。电脑账号库中的会话、微信凭据或地点发生变化后，也需要重新导入。

仅验证一个账号能否刷新微信授权、核对学校身份并取得票据，不提交签到：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx probe --account SCHOOL_ID
```

`authorization_verified` 表示本次取票流程通过，不代表已创建签到记录。该过程会请求真实微信授权和学校接口，也可能刷新轮换设备内的微信凭据；“只读”仅指不提交签到。

确认账号本人在所选实际地点，且允许本次真实提交后，才使用：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx probe --account SCHOOL_ID --submit-once
```

这是一次真实学校写请求。原型仍会检查学校时段与位置范围；没有通过这些检查时不会提交。发送过程不自动重试。请求结果不确定时，先查询学校当天记录，不要因为 USB 工具超时就立即再次执行提交。

## 如何判断结果

配置程序只显示经过筛选的 `GN1` 状态，不回显配置内容、原始网络请求或串口启动日志。常见状态：

| 状态 | 含义 |
| --- | --- |
| `schedule_disabled` / `schedule_enabled` | 当前定时任务开关状态 |
| `profiles_saved` | 配置已写入设备，不代表账号仍有效 |
| `native_self_test_passed` | 原生协议本地向量检查通过，不代表远端认证成功 |
| `authorization_verified` | 本次微信取码、账号匹配和学校取票成功，未提交签到 |
| `submitting_once` | 开始一次真实提交，不应自动重试 |
| `request_accepted` | 学校接受提交，仍需结果复查 |
| `request_rejected` / `school_rejected` | 学校拒绝，结合 `code` 判断；不能因当天已有记录而忽略本次拒绝 |
| `checkin_confirmed` | 提交前待签到，本次请求被接受，随后读取到已签到 |
| `existing_record_only` | 只确认存在当天记录，不能据此证明本次票据或新提交有效 |
| `result_unknown_no_retry` | 结果未确认，程序不会自动重发 |

`46001`、`46002`、`46003`、`46004` 等代码应保留原值并结合当前学校接口解释。页面出现“今日已签到”只说明已有记录，不等于验证了新票据。已签到账号的重复测试不能替代未签到状态下的有效提交和跨日测试。

如果出现 `wifi_or_clock_unavailable`，先检查原空调 Wi-Fi 和 SNTP；`insufficient_heap` 或 `out_of_memory` 表示当前内存不够，不能直接用无限重启解决；`outside_checkin_window`、`outside_allowed_location` 是本地条件未通过，不应靠篡改时段或地点绕过。

## 开启每日 21:10

只有设备取票、一次正常提交、空调并行控制都已实际验证后，再显式导入并启用：

```powershell
.\.venv\Scripts\python.exe esp32\provision.py --port COMx import --enable-schedule
.\.venv\Scripts\python.exe esp32\provision.py --port COMx status
```

设备使用北京时间，经 SNTP 校时，在每天 **21:10–21:14** 的启动窗口内启动当日任务，账号依次处理。21:10 时断网或关机，且错过该窗口后，不会补签。当前实现不是全天重试调度器。

自动任务在真正提交前写入按账号与日期的尝试标记，以避免重启或网络不确定造成重复发送；同一天失败后也可能需要人工核对。手动 `probe --submit-once` 是独立诊断，不应被自动化脚本循环调用。

关闭调度可重新执行不带 `--enable-schedule` 的 `import`，然后用 `status` 确认。不要只关闭电脑网页就认为设备已经停止；配置写入后设备可以独立运行。

## 交接验收清单

后续 agent 应分别记录以下证据，不输出凭据：

1. 芯片、Flash 和原分区识别；原始完整备份的文件大小与 SHA-256。
2. 本次构建版本、应用体积、分区可容纳性和原生向量检查。
3. 刷写完成与设备启动；原空调联网、MQTT、红外控制仍正常。
4. 每个账号独立取票；错误身份、过期学校会话和刷新失败能清楚停止。
5. 有效窗口及本人实际地点的一次正常提交与结果复查。
6. 跨日、断电、断网、会话失效和多账号依次执行；确认没有自动重复提交。
7. 日志不泄露材料，私有配置和二进制没有进入 Git。

目前源码保留了以上工作的入口。未经实际验证的环节应持续标为待验证，尤其不能把“编译成功”“取得票据”或“重复提交返回已有记录”表述为无人值守签到已经恢复。

配置路径可通过 `GOODNIGHT_AC_PROJECT`、`IDF_PATH`、`GOODNIGHT_IDF_PYTHON` 覆盖；默认值只是本次本机工程布局。源码结构不匹配时脚本会停止，需由 AI Agent 或开发者审阅后适配。
