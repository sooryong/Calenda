package com.calenda

import java.io.BufferedInputStream
import java.io.File
import java.io.InputStream

/**
 * GGUF 헤더에서 모델 버전명(general.name)만 가볍게 읽는다.
 *
 * 모델을 메모리에 로드하지 않고 파일 헤더만 스트리밍 파싱하므로,
 * '파일 있음(미로드)' 상태에서도 어떤 라운드 모델인지 표시할 수 있다.
 * general.* 키는 보통 파일 맨 앞에 오므로 tokenizer 같은 큰 배열에 닿기 전에 반환된다.
 *
 * 포맷 참고: magic(u32 'GGUF') · version(u32) · tensor_count(u64) · kv_count(u64) ·
 *            [ key(str) · type(u32) · value ] * kv_count.  모든 정수는 little-endian.
 */
object GgufInfo {
    private const val MAGIC = 0x46554747 // 'GGUF' (little-endian)
    private const val TYPE_STRING = 8
    private const val TYPE_ARRAY = 9

    /** name: general.name (없으면 null). lastModified: 파일 수정시각(=업로드 시점) epoch millis.
     *  fileType: general.file_type (양자화 enum, 없으면 -1). */
    data class Info(val name: String?, val lastModified: Long, val fileType: Int = -1) {
        /** 양자화 라벨: general.file_type → "Q8_0" 등 (LLaMA file_type enum). */
        fun quantLabel(): String = when (fileType) {
            0 -> "F32"; 1 -> "F16"; 2 -> "Q4_0"; 3 -> "Q4_1"; 7 -> "Q8_0"
            8 -> "Q5_0"; 9 -> "Q5_1"; 10 -> "Q2_K"; 11 -> "Q3_K_S"; 12 -> "Q3_K_M"
            13 -> "Q3_K_L"; 14 -> "Q4_K_S"; 15 -> "Q4_K_M"; 16 -> "Q5_K_S"
            17 -> "Q5_K_M"; 18 -> "Q6_K"
            else -> if (fileType >= 0) "q$fileType" else ""
        }

        /** 표시 모델명: "R32-Q3-0.6B-Q8".
         *  general.name("R32 Qwen3 0.6b") 토큰 변환(Qwen3→Q3, 0.6b→0.6B) + 양자화 단축(Q8_0→Q8), '-'로 연결. */
        fun shortName(): String? {
            val n = name ?: return null
            val parts = n.trim().split(Regex("\\s+")).map { tok ->
                Regex("(?i)qwen(\\d+)").matchEntire(tok)?.let { "Q${it.groupValues[1]}" }   // Qwen3 → Q3
                    ?: if (tok.matches(Regex("(?i)[\\d.]+b"))) tok.uppercase() else tok       // 0.6b → 0.6B
            }
            val q = quantLabel().removeSuffix("_0")   // Q8_0 → Q8
            return (parts + if (q.isNotEmpty()) listOf(q) else emptyList()).joinToString("-")
        }
    }

    fun read(file: File): Info {
        val mtime = file.lastModified()
        return try {
            BufferedInputStream(file.inputStream()).use { val (n, ft) = parse(it); Info(n, mtime, ft) }
        } catch (e: Exception) {
            Info(null, mtime)
        }
    }

    /** general.name 과 general.file_type 둘 다 읽는다(둘 다 general.* 초기 블록이라 큰 배열 전에 끝남). */
    private fun parse(s: InputStream): Pair<String?, Int> {
        if (readU32(s) != MAGIC) return null to -1
        readU32(s)              // version
        readU64(s)              // tensor_count
        val kvCount = readU64(s)
        var name: String? = null
        var fileType = -1
        var i = 0L
        while (i < kvCount) {
            val key = readStr(s) ?: break
            val type = readU32(s)
            when {
                key == "general.name" && type == TYPE_STRING -> name = readStr(s)
                key == "general.file_type" && (type == 4 || type == 5) -> fileType = readU32(s)
                else -> skipValue(s, type)
            }
            if (name != null && fileType >= 0) break   // 둘 다 찾으면 종료
            i++
        }
        return name to fileType
    }

    private fun skipValue(s: InputStream, type: Int) {
        when (type) {
            0, 1, 7 -> skipN(s, 1)        // uint8 / int8 / bool
            2, 3 -> skipN(s, 2)           // uint16 / int16
            4, 5, 6 -> skipN(s, 4)        // uint32 / int32 / float32
            10, 11, 12 -> skipN(s, 8)     // uint64 / int64 / float64
            TYPE_STRING -> readStr(s)
            TYPE_ARRAY -> {
                val elemType = readU32(s)
                val n = readU64(s)
                var j = 0L
                while (j < n) { skipValue(s, elemType); j++ }
            }
            else -> throw IllegalStateException("unknown gguf type $type")
        }
    }

    private fun readU32(s: InputStream): Int {
        val b = readN(s, 4)
        return (b[0].toInt() and 0xFF) or ((b[1].toInt() and 0xFF) shl 8) or
            ((b[2].toInt() and 0xFF) shl 16) or ((b[3].toInt() and 0xFF) shl 24)
    }

    private fun readU64(s: InputStream): Long {
        val b = readN(s, 8)
        var v = 0L
        for (k in 7 downTo 0) v = (v shl 8) or (b[k].toLong() and 0xFF)
        return v
    }

    private fun readStr(s: InputStream): String? {
        val len = readU64(s)
        if (len < 0 || len > 1_000_000) return null // sanity 가드
        return String(readN(s, len.toInt()), Charsets.UTF_8)
    }

    private fun readN(s: InputStream, n: Int): ByteArray {
        val b = ByteArray(n)
        var off = 0
        while (off < n) {
            val r = s.read(b, off, n - off)
            if (r < 0) throw IllegalStateException("EOF")
            off += r
        }
        return b
    }

    private fun skipN(s: InputStream, n: Long) {
        var rem = n
        while (rem > 0) {
            val sk = s.skip(rem)
            if (sk <= 0) { if (s.read() < 0) throw IllegalStateException("EOF"); rem-- } else rem -= sk
        }
    }
}
