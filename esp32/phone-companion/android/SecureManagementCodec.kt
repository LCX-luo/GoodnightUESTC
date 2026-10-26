package cn.lcx.goodnightuestc.companion

import android.util.Base64
import org.json.JSONObject
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/** Wire codec for the standalone ESP32 project. Supply locally generated keys. */
class SecureManagementCodec(encryptionKey: ByteArray, signingKey: ByteArray) {
    private val aes=SecretKeySpec(encryptionKey.copyOf(),"AES")
    private val hmac=SecretKeySpec(signingKey.copyOf(),"HmacSHA256")
    private val random=SecureRandom()
    init { require(encryptionKey.size==32 && signingKey.size==32 && encryptionKey.any{it.toInt()!=0} && signingKey.any{it.toInt()!=0}) }
    data class Event(val kind:String,val payload:JSONObject)
    fun command(body:String,sequence:Long):String {
        require(body.startsWith("CI:") && body.toByteArray(Charsets.UTF_8).size<=180 && sequence in 0..4294967294L)
        val mac=Mac.getInstance("HmacSHA256");mac.init(hmac)
        val signature=mac.doFinal("$sequence:$body".toByteArray(Charsets.UTF_8)).joinToString(""){(it.toInt() and 255).toString(16).padStart(2,'0')}
        val clear=JSONObject().put("seq",sequence).put("body",body).put("sig",signature).toString().toByteArray(Charsets.UTF_8)
        val nonce=ByteArray(12).also(random::nextBytes);val cipher=Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE,aes,GCMParameterSpec(128,nonce));cipher.updateAAD("goodnight-management-command-v1".toByteArray(Charsets.UTF_8))
        return JSONObject().put("v",1).put("type","command").put("data",Base64.encodeToString(nonce+cipher.doFinal(clear),Base64.NO_WRAP)).toString()
    }
    fun event(envelope:String):Event {
        require(envelope.length<=1600)
        val outer=JSONObject(envelope);require(outer.getInt("v")==1)
        val packet=Base64.decode(outer.getString("data"),Base64.NO_WRAP);require(packet.size in 28..1024)
        val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,aes,GCMParameterSpec(128,packet.copyOfRange(0,12)))
        cipher.updateAAD("goodnight-management-status-v1".toByteArray(Charsets.UTF_8))
        val inner=JSONObject(cipher.doFinal(packet.copyOfRange(12,packet.size)).toString(Charsets.UTF_8))
        val kind=inner.getString("kind");require(kind in setOf("ack","ci") && kind==outer.getString("type"))
        return Event(kind,inner.getJSONObject("payload"))
    }
}
