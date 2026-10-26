package cn.lcx.goodnightuestc.companion

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.UUID
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.security.MessageDigest
import java.util.Base64

data class CheckinAccount(val index: Int, val schoolId: String, val latitude: Double,
    val longitude: Double, val last: String, val autoEnabled: Boolean = false,
    val hour: Int = 21, val minute: Int = 10,
    val endMinute: Int = (hour*60+minute+5).coerceAtMost(1440)) {
    val hasLocation: Boolean get() = latitude.isFinite() && longitude.isFinite() &&
        latitude in -90.0..90.0 && longitude in -180.0..180.0
}
data class CheckinUiState(
    val busy: Boolean = false, val requestId: String = "", val operation: String = "",
    val deviceReady: Boolean = false, val version: String = "", val deviceTime: String = "",
    val timeSynced: Boolean = false, val wifi: Boolean = false,
    val freeHeap: Long = 0, val largestBlock: Long = 0, val deviceBusy: Boolean = false,
    val enabled: Boolean = false, val hour: Int = 21, val minute: Int = 10,
    val count: Int = 0, val accounts: List<CheckinAccount> = emptyList(),
    val selectedIndex: Int? = null, val message: String = "点击刷新设备，读取板上状态和账号。",
    val resultCode: String = "", val phase: String = "",
    val lastUpdate: String = "",
)

/** Uses the existing encrypted, signed command sender; never owns MQTT credentials. */
class CheckinRepository(private val scope: CoroutineScope,
    private val connected: () -> Boolean, private val send: (String) -> Boolean) {
    private val mutable = MutableStateFlow(CheckinUiState())
    val state = mutable.asStateFlow()
    private var timeout: Job? = null
    private var enumerateAccounts = false
    private data class Transfer(val bytes: ByteArray, val token: String, val account: Int,
        val schoolId: String, var chunk: Int = 0)
    private var transfer: Transfer? = null
    private fun clearTransfer() { transfer?.bytes?.fill(0); transfer = null }
    fun transportSequenceRejected() {
        if(!mutable.value.busy)return
        timeout?.cancel();clearTransfer();enumerateAccounts=false
        mutable.value=mutable.value.copy(busy=false,phase="done",message="设备已重启或序列号变化，现已自动校准。本次命令没有执行，请重新点击；不会自动重发签到。")
    }
    fun close() { timeout?.cancel(); clearTransfer() }
    fun enrollmentError() { mutable.value = mutable.value.copy(message = "账号编辑任务已中断或过期，请重新登录验证；未更新设备。") }
    fun importAccount(raw: String, index: Int?) {
        if (mutable.value.busy) { enrollmentError(); return }
        try {
            val bundle = JSONObject(raw)
            require(bundle.keys().asSequence().toSet() == setOf("student_id","schoolSession","wechat","location","enabled","scheduleMinute"))
            val sid = bundle.getString("student_id")
            require(sid.matches(Regex("[A-Za-z0-9._-]{1,40}")))
            if(index != null) {
                val account = mutable.value.accounts.firstOrNull { it.index == index && it.schoolId == sid }
                    ?: throw IllegalArgumentException("Changed account")
                bundle.put("enabled",account.autoEnabled).put("scheduleMinute",account.hour*60+account.minute)
            } else bundle.put("enabled",false)
            val bytes = bundle.toString().toByteArray(Charsets.UTF_8)
            require(bytes.size in 1..6000)
            clearTransfer()
            val item = Transfer(bytes, UUID.randomUUID().toString().replace("-", "").take(12), index ?: -1, sid)
            transfer=item
            if (!beginSend(newId(),"put_begin") { id -> CheckinProtocol.begin(id,item.token,item.bytes.size,item.account,item.schoolId) }) clearTransfer()
        } catch (_: Exception) { clearTransfer(); enrollmentError() }
    }
    fun delete(account: CheckinAccount) {
        if(mutable.value.accounts.none { it == account }) return
        request("delete",account.index)
    }
    fun editSchedule(account: CheckinAccount, enabled: Boolean, hour: Int, minute: Int, endHour: Int, endMinute: Int) {
        if(mutable.value.accounts.none { it == account } || hour !in 0..23 || minute !in 0..59 || endHour !in 0..24 || endMinute !in 0..59 || endHour*60+endMinute !in (hour*60+minute+1)..1440) {
            mutable.value=mutable.value.copy(message="结束时间须晚于开始时间，最晚 24:00；请刷新核对账号。")
            return
        }
        beginSend(newId(),"edit") { id -> CheckinProtocol.edit(id,account.index,account.schoolId,enabled,hour,minute,endMinute=endHour*60+endMinute) }
    }
    private fun nextTransfer() {
        val item=transfer ?: return
        val offset=item.chunk*64
        if(offset<item.bytes.size) {
            val part=item.bytes.copyOfRange(offset,minOf(offset+64,item.bytes.size))
            val encoded=Base64.getEncoder().encodeToString(part)
            part.fill(0)
            if(!beginSend(newId(),"put_chunk") { id -> CheckinProtocol.chunk(id,item.token,item.chunk,encoded) }) clearTransfer()
        } else {
            val digest=MessageDigest.getInstance("SHA-256").digest(item.bytes).joinToString("") { "%02x".format(it) }
            if(!beginSend(newId(),"put_commit") { id -> CheckinProtocol.commit(id,item.token,digest) }) clearTransfer()
        }
    }
    private fun newId() = UUID.randomUUID().toString().replace("-", "").take(16)
    fun select(index: Int) {
        if (!mutable.value.busy && mutable.value.accounts.any { it.index == index })
            mutable.value = mutable.value.copy(selectedIndex = index)
    }
    fun refreshDevice() { if (request("status")) enumerateAccounts = true }
    fun selected(op: String) {
        if (op !in setOf("query", "refresh")) return
        val index = mutable.value.selectedIndex ?: return
        request(op, index)
    }
    fun submit(account: CheckinAccount) {
        if (!account.hasLocation || mutable.value.accounts.none { it == account } ||
            mutable.value.selectedIndex != account.index) {
            mutable.value = mutable.value.copy(message = "账号或保存位置已变化，请刷新后重新确认。")
            return
        }
        request("submit", account.index)
    }
    fun schedule(enabled: Boolean, hour: Int, minute: Int) {
        if (hour !in 0..23 || minute !in 0..59) {
            mutable.value = mutable.value.copy(message = "请输入 00:00–23:59 的北京时间。")
            return
        }
        request("schedule", enabled = enabled, hour = hour, minute = minute)
    }
    private fun request(op: String, account: Int? = null, enabled: Boolean? = null,
                        hour: Int? = null, minute: Int? = null): Boolean {
        val sid=if(op in setOf("query","refresh","submit","delete"))
            mutable.value.accounts.firstOrNull { it.index==account }?.schoolId ?: return false else null
        return beginSend(newId(),op) { id -> CheckinProtocol.command(id,op,account,enabled,hour,minute,sid) }
    }
    private fun beginSend(id: String, op: String, makeBody: (String)->String): Boolean {
        if (mutable.value.busy) return false
        if (!connected()) {
            mutable.value = mutable.value.copy(message = "尚未连接设备消息服务，请先在设置中连接。")
            return false
        }
        val body = try { makeBody(id) } catch(_: IllegalArgumentException) {
            mutable.value=mutable.value.copy(message="管理请求参数无效或过长，未发送。")
            return false
        }
        mutable.value = mutable.value.copy(busy = true, requestId = id, operation = op,
            phase = "sending", resultCode = "", message = "正在等待设备响应；不会自动重发操作。")
        if (!send(body)) {
            mutable.value = mutable.value.copy(busy = false, phase = "not_sent",
                message = "命令未能交给消息服务，请检查连接。")
            enumerateAccounts = false
            return false
        }
        timeout?.cancel()
        timeout = scope.launch {
            delay(180_000)
            if (mutable.value.requestId == id && mutable.value.busy) {
                enumerateAccounts = false
                clearTransfer()
                mutable.value = mutable.value.copy(busy = false, phase = "unknown",
                    message = "设备响应超时，操作结果待查询。请先查询状态；不会自动重试签到。")
            }
        }
        return true
    }
    private fun text(value: String, limit: Int = 160): String {
        if (value.contains(Regex("https?://|(?i)cookie|access_token|refresh_token|ticket"))) return "设备返回了状态信息"
        return value.replace(Regex("[\\p{Cntrl}]"), " ").take(limit)
    }
    fun receive(result: JSONObject) {
        val previous = mutable.value
        if (result.optString("id") != previous.requestId || result.optString("op") != previous.operation) return
        val phase = result.optString("phase")
        if (phase !in setOf("accepted", "progress", "done")) return
        // A worker may finish before its queued acknowledgement is delivered.
        // Never let a late accepted/progress event overwrite a terminal result.
        if (previous.phase == "done" || !previous.busy && phase != "done") return
        val op = previous.operation
        val code = result.opt("code")?.toString()?.takeIf { it.matches(Regex("[A-Za-z0-9_.-]{1,64}")) } ?: ""
        val deviceState=result.optString("state")
        val hint=when(deviceState) {
            "oauth_rejected" -> "微信授权失效或被其他登录更新。请点“更新登录授权”，重新扫码并同步设备。"
            "authorization_verified" -> "板上微信取码、学校身份和操作票据均验证成功；未提交签到。"
            "checkin_confirmed" -> "本次签到成功，学校回查已确认。"
            "existing_record_only", "already_recorded" -> "学校已有记录；不能视为本次新增签到。"
            "result_unknown_no_retry", "accepted_pending" -> "提交结果待确认；先查询学校记录，设备不会自动重发。"
            "account_saved" -> "设备已保存本次完整授权。"
            "wifi_or_clock_unavailable", "clock_unsynchronized" -> "设备尚未联网或校时，请稍后刷新。"
            "submission_rejected" -> "学校拒绝本次提交，具体原因见返回文字与代码。"
            else -> ""
        }
        val messages = mutableListOf<String>()
        if(hint.isNotEmpty())messages+=hint
        messages+=text(result.optString("msg",deviceState.ifEmpty { "设备已响应" }))
        if (phase == "done") {
            result.optString("businessDate").takeIf { it.isNotEmpty() }?.let { messages += "业务日期：${text(it,40)}" }
            result.optString("recordStatusCode").takeIf { it.isNotEmpty() }?.let { messages += "学校当天状态：${text(it,40)}" }
            result.optString("after").takeIf { it.isNotEmpty() }?.let { messages += "回查状态：${text(it,40)}" }
            if (op == "submit" && result.has("accepted")) messages += "本次请求被接受：${if(result.optBoolean("accepted")) "是" else "否"}"
        }
        var next = previous.copy(phase = phase, resultCode = code, message = messages.joinToString("\n"))
        if (phase != "done") { mutable.value = next; return }
        timeout?.cancel()
        next = next.copy(busy = false)
        if (result.optBoolean("ok", false)) {
            if (op == "status") {
                val epoch = result.optLong("time")
                val displayTime = if (epoch > 0 && epoch <= 253402300799L)
                    SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT).apply {
                        timeZone = TimeZone.getTimeZone("Asia/Shanghai")
                    }.format(Date(epoch * 1000)) else "未校时"
                next = next.copy(deviceReady = true, version = text(result.optString("v"), 40),
                    deviceTime = displayTime, timeSynced = result.optBoolean("timeSynced"),
                    wifi = result.optBoolean("wifi"), freeHeap = result.optLong("freeHeap"),
                    largestBlock = result.optLong("largestBlock"), deviceBusy = result.optBoolean("busy"),
                    enabled = result.optBoolean("enabled"), hour = result.optInt("hour",21).coerceIn(0,23),
                    minute = result.optInt("minute",10).coerceIn(0,59), count = result.optInt("count").coerceIn(0,32),
                    accounts = emptyList(), selectedIndex = null)
            } else if (op == "list") {
                val index = result.optInt("a", -1)
                val last = result.optJSONObject("last")
                if (index in 0 until next.count) {
                    val account = CheckinAccount(index, text(result.optString("sid"), 40),
                        result.optDouble("lat", Double.NaN), result.optDouble("lng", Double.NaN),
                        text(listOfNotNull(last?.optString("state"), last?.optString("code"),
                            last?.optString("msg"), last?.optString("time")).filter { it.isNotEmpty() }.joinToString(" · ")),
                        autoEnabled=result.optBoolean("autoEnabled"),hour=result.optInt("hour",21),minute=result.optInt("minute",10),endMinute=result.optInt("end",(result.optInt("hour",21)*60+result.optInt("minute",10)+5).coerceAtMost(1440)))
                    next = next.copy(accounts = (next.accounts.filterNot { it.index == index } + account).sortedBy { it.index },
                        selectedIndex = next.selectedIndex ?: index)
                }
            } else if (op == "schedule") {
                next = next.copy(enabled = result.optBoolean("enabled", next.enabled),
                    hour = result.optInt("hour", next.hour), minute = result.optInt("minute", next.minute))
            }
        } else enumerateAccounts = false
        if (op == "submit") next = next.copy(message = next.message +
            "\n这是设备本次提交的反馈；已有签到记录不代表本次新建记录。不会自动重发。")
        mutable.value = next
        if(op in setOf("put_begin","put_chunk","put_commit")) {
            if(!result.optBoolean("ok",false)) { clearTransfer(); return }
            if(op=="put_commit") {
                if(result.optString("state")!="account_saved") {
                    clearTransfer(); mutable.value=mutable.value.copy(message="设备未确认账号写入，不能视为已同步。")
                    return
                }
                clearTransfer()
                mutable.value=mutable.value.copy(lastUpdate="设备已确认账号同步成功。")
                refreshDevice()
            } else {
                if(op=="put_chunk") transfer?.let { it.chunk++ }
                nextTransfer()
            }
            return
        }
        if(op in setOf("edit","delete") && result.optBoolean("ok",false)) {
            mutable.value=mutable.value.copy(lastUpdate=if(op=="delete") "设备已确认账号删除。" else "设备已确认账号计划更新。")
            refreshDevice()
            return
        }
        if (enumerateAccounts && phase == "done") {
            val index = if (op == "status") 0 else result.optInt("a", -1) + 1
            if (op in setOf("status", "list") && index in 0 until next.count) request("list", index)
            else enumerateAccounts = false
        }
    }
}
