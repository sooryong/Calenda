package com.vibezent.calendaragent

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverters

/** 앱 단일 Room DB. 이벤트함 테이블 1개. */
@Database(entities = [DetectedEvent::class], version = 1, exportSchema = false)
@TypeConverters(Converters::class)
abstract class AppDatabase : RoomDatabase() {

    abstract fun eventDao(): EventDao

    companion object {
        @Volatile
        private var INSTANCE: AppDatabase? = null

        fun get(ctx: Context): AppDatabase = INSTANCE ?: synchronized(this) {
            INSTANCE ?: Room.databaseBuilder(
                ctx.applicationContext, AppDatabase::class.java, "calendar-agent.db",
            ).fallbackToDestructiveMigration(dropAllTables = true).build().also { INSTANCE = it }
        }
    }
}
