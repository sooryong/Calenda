package com.vibezent.calendaragent

import android.accounts.Account
import android.content.Context
import com.google.android.gms.auth.GoogleAuthUtil
import com.google.android.gms.auth.api.signin.GoogleSignIn
import com.google.android.gms.auth.api.signin.GoogleSignInAccount
import com.google.android.gms.auth.api.signin.GoogleSignInClient
import com.google.android.gms.auth.api.signin.GoogleSignInOptions
import com.google.android.gms.common.api.Scope

/**
 * Gmail 읽기 권한(OAuth) 로그인 + 액세스 토큰 발급.
 * ⚠ 동작하려면 Google Cloud에 OAuth 클라이언트(Android, 패키지+SHA-1)·Gmail API·동의화면 설정 필요.
 */
object GmailAuth {
    const val SCOPE_GMAIL = "https://www.googleapis.com/auth/gmail.readonly"

    fun client(ctx: Context): GoogleSignInClient {
        val gso = GoogleSignInOptions.Builder(GoogleSignInOptions.DEFAULT_SIGN_IN)
            .requestEmail()
            .requestScopes(Scope(SCOPE_GMAIL))
            .build()
        return GoogleSignIn.getClient(ctx, gso)
    }

    fun account(ctx: Context): GoogleSignInAccount? = GoogleSignIn.getLastSignedInAccount(ctx)

    fun isConnected(ctx: Context): Boolean =
        account(ctx)?.let { GoogleSignIn.hasPermissions(it, Scope(SCOPE_GMAIL)) } == true

    fun email(ctx: Context): String? = account(ctx)?.email

    /** 블로킹: Gmail REST용 OAuth 액세스 토큰. 반드시 IO 스레드에서 호출. 실패 시 null. */
    fun accessToken(ctx: Context, account: Account): String? = try {
        GoogleAuthUtil.getToken(ctx, account, "oauth2:$SCOPE_GMAIL")
    } catch (e: Exception) {
        null
    }
}
