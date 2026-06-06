package com.vibezent.calendaragent

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

    /** name: general.name (없으면 null). lastModified: 파일 수정시각(=업로드 시점) epoch millis. */
    data class Info(val name: String?, val lastModified: Long)

    fun read(file: File): Info {
        val mtime = file.lastModified()
        val name = try {
            BufferedInputStream(file.inputStream()).use { parseName(it) }
        } catch (e: Exception) {
            null
        }
        return Info(name, mtime)
    }

    private fun parseName(s: InputStream): String? {
        if (readU32(s) != MAGIC) return null
        readU32(s)              // version
        readU64(s)              // tensor_count
        val kvCount = readU64(s)
        var i = 0L
        while (i < kvCount) {
            val key = readStr(s) ?: return null
            val type = readU32(s)
            if (key == "general.name" && type == TYPE_STRING) return readStr(s)
            skipValue(s, type)
            i++
        }
        return null
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
