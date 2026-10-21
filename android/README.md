# Android 手机版

独立 APK，Android 8.0 及以上。安装后直接使用，不需要电脑保持开机、不需要 Python、服务器或地图 Key。联网用于学校登录、接口请求和地图瓦片。当前为 **0.1.1 测试版**，已改用国内高德底图，地图加载无需代理。

## 下载和使用

1. 从仓库的 [安装包目录](../downloads/) 下载 `GoodnightUESTC-Android.apk`，在手机中打开安装。需要时，允许当前浏览器或文件管理器安装此 APK。
2. 打开“晚安成电”，点击“学校账号登录”，在学校官方统一认证网页输入本人账号、密码，并按提示完成验证码或二次验证。
3. 登录完成后点击底部“完成登录，返回检查”。应用只读查询当天记录，显示“会话有效”后即可使用。若学校网页要求继续跳转，请先完成该流程。
4. 地图默认位于沙河校区。用“沙河 / 清水河”查看两个校区，点击地图上的本人实际位置。双指缩放地图；也可填写 **GCJ-02** 经纬度。查看校区不会改变已选点。
5. 首次试用先点击“在线检查”或“只读预检查”。这些操作只查询学校，不会上传签到。
6. 正式签到时点击“预检查并签到”，核对学校地址、日期和 GCJ-02 坐标，勾选本人实际在场，再点击原生弹窗中的“确认提交”。只有这一步会提交真实签到。
7. 显示“签到已确认”表示已经回读到当天正常 `CHECKED_IN` 记录。若结果未知，请查询学校官方入口，程序不会自动重发。

学校不在签到时段、所选点超出允许范围、会话过期、已有当天记录或返回异常时会停止。结束前两分钟停止提交，防止跨时段请求。不要为了通过检查而选择不符合本人实际位置的地址。

## 手机网络、会话和重复提交

- 学校只读接口会优先直连，并在系统配置了代理时竞争可用线路，短期复用成功线路；VPN 由 Android 系统处理。登录网页和地图使用系统 WebView 的网络设置。网络不可用或代理本身阻断学校连接时仍可能失败，无法保证所有代理环境均能连接。
- 始终验证 HTTPS 证书，不忽略学校证书错误。网页登录由学校处理，应用不实现密码导出、手动 Cookie 导入或绕过 MFA。
- 会话保存在此应用的 WebView 数据目录，关闭应用后可复用；系统备份已关闭。应用不会把 Cookie 返回给页面或写入仓库，不会从聊天、电脑浏览器导入他人会话。点击“清除会话”可退出。
- 本机按北京时间日期保存提交尝试标记；即使超时、重启或换账号，当天也不会重复提交。这是保守限制；有疑问请查看官方记录，不要通过卸载、清除应用数据来重试未知结果。
- 手机版地图改用高德 GCJ-02 底图，选点直接以 GCJ-02 提交，不再重复转换。0.1.0 版保存的 WGS84 位置会自动转换一次并标记为 GCJ-02。沙河和清水河预设点由旧版 WGS84 预设转换而来。不能保证地图、围栏和学校地址完全一致，请核对学校返回地址。没有伪造 GPS、定位精度或传感器测量数据。
- 底图地址参考[高德官方瓦片示例](https://lbs.amap.com/demo/javascript-api-v2/example/thirdlayer/functile)，坐标依据[高德 GCJ-02 说明](https://developer.amap.com/api/javascript-api-v2/guide/abc/basetype)。已验证不使用代理可返回地图图片；服务端仍可能调整访问策略，请遵守地图服务条款，不批量下载瓦片。

## Android Studio 编译

在 Android Studio 中选择 **Open**，打开本仓库的 `android` 目录，等待 Gradle 同步。需要 JDK 17 或更新版本（推荐 Studio 自带 JDK 21）、Android SDK Platform 36.1；首次同步需要联网下载 Gradle/Android Gradle Plugin，应用无第三方 Java 运行库依赖。Gradle Wrapper 已提交。

连接开启 USB 调试并已授权的手机，选择 `app` 后点击 Run。也可在 `android` 目录执行：

```powershell
.\gradlew.bat assembleDebug
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb shell am start -n cn.lcx.goodnightuestc/.MainActivity
```

macOS/Linux 使用 `./gradlew assembleDebug`。SDK 路径通过本机 `ANDROID_HOME` 或未提交的 `local.properties` 配置。不要提交 SDK 路径、私钥或手机数据。工程允许当前 Windows 中文目录；如果本机 SDK 工具无法处理中文路径，可把仓库克隆到英文目录。

预编译 APK 使用维护者本机调试签名，适合试用；签名私钥没有上传。自己编译或下载 GitHub Actions 的 APK 使用的签名可能不同，无法直接覆盖安装，需要自行处理签名或卸载旧版（会丢失会话和本机标记）。仓库 `downloads/SHA256SUMS` 提供安装包校验值。

## 不提交真实签到的测试

在已连接的测试手机上运行：

```powershell
.\gradlew.bat assembleDebug assembleDebugAndroidTest
adb install -r app\build\outputs\apk\debug\app-debug.apk
adb install -r app\build\outputs\apk\androidTest\debug\app-debug-androidTest.apk
adb shell am instrument -w cn.lcx.goodnightuestc.test/cn.lcx.goodnightuestc.SmokeInstrumentation
```

测试使用独立偏好设置及模拟学校接口，验证坐标转换、业务日期和状态检查、只读检查没有 POST、单次提交、结果回读、超时不重发及防重复提交，不使用真实账号或学校接口。测试成功打印 `PASS`。时段测试使用当天 00:00—24:00，结束前两分钟的保护同样生效，请避开北京时间 23:58—24:00 执行该设备测试。

已在维护者连接的 Android 16 手机上通过构建、安装和 29 项模拟断言，Android lint 检查通过；电脑版 40 项测试通过。**真实学校登录、MFA 和真实签到需要本人验证，目前没有通过开发操作提交真实签到。**

## 免责声明

仅供本人账号及学校允许的用途。遵守学校管理规定，按本人实际位置签到；不得代签、伪造位置、批量操作他人账号或绕过学校验证。最终确认会提交真实记录，结果以学校系统为准。本工具不保证持续可用或签到成功，请勿共享会话。学校接口变化可能使应用失效。

本项目 MIT 许可证；Leaflet 和 coordtransform 的许可证一并保留在仓库及 APK 资源中。手机版高德底图归其相应权利人所有，地图署名保留。
