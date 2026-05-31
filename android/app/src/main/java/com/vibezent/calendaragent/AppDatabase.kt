package com.vibezent.calendaragent

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/** 앱 단일 Room DB. 이벤트함 테이블 1개. */
@Database(entities = [DetectedEvent::class], version = 3, exportSchema = false)
@TypeConverters(Converters::class)
abstract class AppDatabase : RoomDatabase() {

    abstract fun eventDao(): EventDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        // v2→v3: exported 컬럼 추가(기존 데이터 보존 — 파괴적 초기화 대신 정식 마이그레이션).
        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE detected_events ADD COLUMN exported INTEGER NOT NULL DEFAULT 0")
            }
        }

        fun get(ctx: Context): AppDatabase = INSTANCE ?: synchronized(this) {
            INSTANCE ?: Room.databaseBuilder(
                ctx.applicationContext, AppDatabase::class.java, "calendar-agent.db",
            ).addMigrations(MIGRATION_2_3)
                .fallbackToDestructiveMigration(dropAllTables = true)  // 그 외 비정상 케이스 백스톱
                .build().also { INSTANCE = it }
        }
    }
}
