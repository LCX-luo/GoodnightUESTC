package cn.lcx.goodnightuestc.companion

/** Small management messages only: credentials never enter this protocol. */
object CheckinProtocol {
    val operations = setOf("status", "list", "query", "refresh", "submit", "schedule", "edit", "delete", "put_begin", "put_chunk", "put_commit")
    private fun schoolId(sid: String?) = sid?.also { require(it.matches(Regex("[A-Za-z0-9._-]{1,40}"))) }
        ?: throw IllegalArgumentException("Missing school id")
    private fun packet(id: String, op: String, fields: List<String>): String {
        require(id.matches(Regex("[A-Za-z0-9]{8,32}")) && op in operations)
        return ("CI:{" + (listOf("\"id\":\"$id\"", "\"op\":\"$op\"") + fields).joinToString(",") + "}").also {
            require(it.toByteArray(Charsets.UTF_8).size <= 180)
        }
    }
    fun command(id: String, op: String, account: Int? = null, enabled: Boolean? = null,
                hour: Int? = null, minute: Int? = null, sid: String? = null): String {
        require(id.matches(Regex("[A-Za-z0-9]{8,32}")))
        require(op in setOf("status","list","query","refresh","submit","schedule","delete"))
        val parts = mutableListOf<String>()
        if (op in setOf("list", "query", "refresh", "submit", "delete")) {
            require(account != null && account in 0..31)
            parts += "\"a\":$account"
        } else require(account == null)
        if(op in setOf("query","refresh","submit","delete")) parts += "\"sid\":\"${schoolId(sid)}\""
        if (op == "schedule") {
            require(enabled != null && hour != null && hour in 0..23 && minute != null && minute in 0..59)
            parts += listOf("\"enabled\":$enabled", "\"hour\":$hour", "\"minute\":$minute")
        } else require(enabled == null && hour == null && minute == null)
        return packet(id,op,parts)
    }
    fun edit(id:String, account:Int, sid:String, enabled:Boolean?=null,
             hour:Int?=null, minute:Int?=null, latitude:Double?=null,longitude:Double?=null,endMinute:Int?=null):String {
        require(account in 0..31)
        val fields=mutableListOf("\"a\":$account","\"sid\":\"${schoolId(sid)}\"")
        if(enabled!=null) fields += "\"enabled\":$enabled"
        if(hour!=null||minute!=null) {
            require(hour!=null&&hour in 0..23&&minute!=null&&minute in 0..59)
            fields += listOf("\"hour\":$hour","\"minute\":$minute")
        }
        if(endMinute!=null) { require(endMinute in 1..1440); fields += "\"end\":$endMinute" }
        if(latitude!=null||longitude!=null) {
            require(latitude!=null&&latitude.isFinite()&&latitude in -90.0..90.0&&longitude!=null&&longitude.isFinite()&&longitude in -180.0..180.0)
            fields += listOf("\"lat\":$latitude","\"lng\":$longitude")
        }
        require(fields.size>2)
        return packet(id,"edit",fields)
    }
    private fun transfer(t:String) { require(t.matches(Regex("[A-Za-z0-9]{12}"))) }
    fun begin(id:String,t:String,length:Int,account:Int,sid:String):String {
        transfer(t);require(length in 1..6000 && account in -1..31)
        return packet(id,"put_begin",listOf("\"t\":\"$t\"","\"len\":$length","\"a\":$account","\"sid\":\"${schoolId(sid)}\""))
    }
    fun chunk(id:String,t:String,index:Int,encoded:String):String {
        transfer(t);require(index in 0..93 && encoded.length in 4..88 && encoded.matches(Regex("[A-Za-z0-9+/]+={0,2}")))
        return packet(id,"put_chunk",listOf("\"t\":\"$t\"","\"n\":$index","\"b\":\"$encoded\""))
    }
    fun commit(id:String,t:String,digest:String):String {
        transfer(t);require(digest.matches(Regex("[a-f0-9]{64}")))
        return packet(id,"put_commit",listOf("\"t\":\"$t\"","\"sha256\":\"$digest\""))
    }
}
