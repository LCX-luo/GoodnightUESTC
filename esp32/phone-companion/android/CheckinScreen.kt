package cn.lcx.goodnightuestc.companion

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import cn.lcx.goodnightuestc.companion.CheckinAccount
import cn.lcx.goodnightuestc.companion.CheckinRepository
import java.util.Locale

@Composable
fun CheckinScreen(connected: Boolean, repository: CheckinRepository, editAccount: (CheckinAccount?) -> Unit = {}) {
    val state by repository.state.collectAsState()
    var deleting by remember { mutableStateOf<CheckinAccount?>(null) }
    var editingPlan by remember { mutableStateOf<CheckinAccount?>(null) }
    var accountEnabled by remember { mutableStateOf(false) }
    var accountHour by remember { mutableStateOf("21") }
    var accountMinute by remember { mutableStateOf("10") }
    var endHour by remember { mutableStateOf("21") }
    var endMinute by remember { mutableStateOf("15") }
    var scheduleEnabled by remember(state.enabled) { mutableStateOf(state.enabled) }
    var hour by remember(state.hour) { mutableStateOf("%02d".format(state.hour)) }
    var minute by remember(state.minute) { mutableStateOf("%02d".format(state.minute)) }
    val selected = state.accounts.firstOrNull { it.index == state.selectedIndex }
    val available = connected && !state.busy
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)) {
        CheckinCard("设备状态") {
            Text(if (connected) "消息服务已连接；设备状态以实际响应为准。" else "消息服务未连接，请先到设置连接。")
            Button(onClick = repository::refreshDevice, enabled = available) { Text("刷新设备和账号") }
            if (state.deviceReady) {
                Text("固件：${state.version.ifEmpty { "未提供" }}")
                Text("设备时间：${state.deviceTime.ifEmpty { "未提供" }}（北京时间）")
                Text("校时：${if(state.timeSynced) "已完成" else "未完成"} · Wi-Fi：${if(state.wifi) "已连接" else "未连接"}")
                Text("可用内存：${state.freeHeap / 1024} KiB · 最大连续块：${state.largestBlock / 1024} KiB")
                Text("设备任务：${if(state.deviceBusy) "执行中" else "空闲"} · 已存 ${state.count} 个账号")
            }
        }
        CheckinCard("板上账号") {
            if (state.accounts.isEmpty()) Text("暂无已读取账号。先刷新设备，也可以在此手机新增本人账号。")
            Button(onClick = { editAccount(null) }, enabled = available && state.deviceReady && !state.deviceBusy) { Text("新增本人账号（登录 / 微信授权 / 地图）") }
            state.accounts.forEach { account ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = state.selectedIndex == account.index,
                        onClick = { repository.select(account.index) }, enabled = !state.busy)
                    Column(Modifier.weight(1f)) {
                        Text(account.schoolId.ifEmpty { "账号 ${account.index + 1}" }, fontWeight = FontWeight.SemiBold)
                        if (account.hasLocation) Text(String.format(Locale.ROOT,"GCJ-02 %.6f, %.6f",account.latitude, account.longitude), style = MaterialTheme.typography.bodySmall)
                        if (account.last.isNotEmpty()) Text(account.last, style = MaterialTheme.typography.bodySmall)
                        Text("自动：${if(account.autoEnabled) "启用" else "关闭"} · 北京时间 %02d:%02d–%02d:%02d".format(account.hour,account.minute,account.endMinute/60,account.endMinute%60),style=MaterialTheme.typography.bodySmall)
                    }
                }
            }
            OutlinedButton(onClick = { editAccount(selected) }, enabled = available && selected != null && !state.deviceBusy) { Text("更新登录授权 / 修改保存位置") }
            OutlinedButton(onClick = {
                selected?.let { editingPlan=it;accountEnabled=it.autoEnabled;accountHour="%02d".format(it.hour);accountMinute="%02d".format(it.minute);endHour="%02d".format(it.endMinute/60);endMinute="%02d".format(it.endMinute%60) }
            }, enabled = available && selected != null && !state.deviceBusy) { Text("所选账号自动开关与时间") }
            TextButton(onClick = { deleting=selected }, enabled = available && selected != null && !state.deviceBusy) { Text("删除所选设备账号") }
            Button(onClick = { repository.selected("query") }, enabled = available && selected != null && !state.deviceBusy) { Text("查询所选账号（只读）") }
            OutlinedButton(onClick = { repository.selected("refresh") }, enabled = available && selected != null && !state.deviceBusy) { Text("刷新已保存的微信授权 / 验证取票") }
            Button(onClick = { selected?.let(repository::submit) },
                enabled = available && selected?.hasLocation == true && !state.deviceBusy) { Text("立即测试一次签到（正式提交）") }
            Text("测试按钮直接申请新票据并提交一次，学校负责判断时段、位置和已有记录；请在点击前核对所选账号及位置。", style = MaterialTheme.typography.bodySmall)
        }
        CheckinCard("每天定时签到") {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("启用每天定时", Modifier.weight(1f))
                Switch(checked = scheduleEnabled, onCheckedChange = { scheduleEnabled = it }, enabled = !state.busy)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(hour, { hour = it.filter(Char::isDigit).take(2) }, Modifier.weight(1f),
                    label = { Text("时（00–23）") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
                OutlinedTextField(minute, { minute = it.filter(Char::isDigit).take(2) }, Modifier.weight(1f),
                    label = { Text("分（00–59）") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            }
            Button(onClick = { repository.schedule(scheduleEnabled, hour.toIntOrNull() ?: -1, minute.toIntOrNull() ?: -1) },
                enabled = available && state.deviceReady && !state.deviceBusy) { Text("保存到设备") }
            Text("使用北京时间，默认 21:10。仅对已导入账号生效；设备须联网、校时成功且授权有效。逐账号设置时段；每隔至少 60 秒检查，成功停止，授权失效或结果未知时停止当天任务。", style = MaterialTheme.typography.bodySmall)
        }
        CheckinCard("操作反馈") {
            if (state.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(state.message)
            if (state.resultCode.isNotEmpty()) Text("返回代码：${state.resultCode}", style = MaterialTheme.typography.bodySmall)
            if(state.lastUpdate.isNotEmpty()) Text(state.lastUpdate,fontWeight=FontWeight.SemiBold)
        }
        CheckinCard("新增账号 / 更新登录") {
            Text("点击上方新增或更新，使用与晚安成电 0.2.4 相同的学校登录、微信扫码和国内地图流程。二维码轮询支持切换应用及有限断线重连。授权材料仅在手机原生内存和加密缓存中处理，经加密消息分片写入设备。")
            Text("仅收到设备完成写入确认后显示已同步。新账号默认关闭自动签到；可以再为每个账号设置开关和北京时间。账号编辑页只更新设备，不在手机直接签到。", style = MaterialTheme.typography.bodySmall)
        }
        Text("仅限本人账号与实际位置、学校允许的用途。操作反馈以学校实际返回和结果复查为准。", style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(8.dp))
    }
    deleting?.let { account ->
        AlertDialog(onDismissRequest={deleting=null}, title={Text("删除设备账号")},
            text={Text("从设备移除 ${account.schoolId} 的登录材料、位置和计划？不会撤销学校账号，也不会修改当天已有签到。")},
            confirmButton={TextButton(onClick={deleting=null;repository.delete(account)},enabled=available){Text("确认删除")}},
            dismissButton={TextButton(onClick={deleting=null}){Text("取消")}})
    }
    editingPlan?.let { account ->
        AlertDialog(onDismissRequest={editingPlan=null}, title={Text("账号 ${account.schoolId} 的计划")},
            text={Column(verticalArrangement=Arrangement.spacedBy(10.dp)) {
                Row(verticalAlignment=Alignment.CenterVertically) { Text("自动签到",Modifier.weight(1f));Switch(accountEnabled,{accountEnabled=it}) }
                OutlinedTextField(accountHour,{accountHour=it.filter(Char::isDigit).take(2)},label={Text("开始：时 00–23")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number))
                OutlinedTextField(accountMinute,{accountMinute=it.filter(Char::isDigit).take(2)},label={Text("分 00–59")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number))
                OutlinedTextField(endHour,{endHour=it.filter(Char::isDigit).take(2)},label={Text("结束：时 00–24")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number))
                OutlinedTextField(endMinute,{endMinute=it.filter(Char::isDigit).take(2)},label={Text("结束：分 00–59（24 时仅允许 00 分）")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Number))
                Text("每隔至少 60 秒检查；已完成即停止。授权失效、已接受但待确认或结果未知时停止当天自动任务。设备总开关也须开启。")
            }},confirmButton={TextButton(enabled=available,onClick={
                repository.editSchedule(account,accountEnabled,accountHour.toIntOrNull()?:-1,accountMinute.toIntOrNull()?:-1,endHour.toIntOrNull()?:-1,endMinute.toIntOrNull()?:-1);editingPlan=null
            }){Text("保存到设备")}},dismissButton={TextButton(onClick={editingPlan=null}){Text("取消")}})
    }
}

@Composable
private fun CheckinCard(title: String, content: @Composable ColumnScope.() -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            content()
        }
    }
}
