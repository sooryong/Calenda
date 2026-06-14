// JNI bridge for on-device GGUF inference (llama.cpp C API, b9371).
// Minimal greedy completion: load model once, run prompt → text.
#include <jni.h>
#include <android/log.h>
#include <string>
#include <vector>
#include "llama.h"

#define LOG_TAG "LlamaJNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

// 전역 핸들 (단일 모델 가정)
static llama_model * g_model = nullptr;

extern "C" JNIEXPORT jboolean JNICALL
Java_com_calenda_LlamaBridge_nativeLoadModel(
        JNIEnv * env, jobject /*thiz*/, jstring model_path) {
    static bool backends_loaded = false;
    if (!backends_loaded) {
        ggml_backend_load_all();
        backends_loaded = true;
    }

    const char * path = env->GetStringUTFChars(model_path, nullptr);
    LOGI("loading model: %s", path);

    llama_model_params mparams = llama_model_default_params();
    mparams.n_gpu_layers = 0;  // 폰 CPU 추론

    if (g_model != nullptr) {
        llama_model_free(g_model);
        g_model = nullptr;
    }
    g_model = llama_model_load_from_file(path, mparams);
    env->ReleaseStringUTFChars(model_path, path);

    if (g_model == nullptr) {
        LOGE("failed to load model");
        return JNI_FALSE;
    }
    LOGI("model loaded");
    return JNI_TRUE;
}

extern "C" JNIEXPORT void JNICALL
Java_com_calenda_LlamaBridge_nativeFree(
        JNIEnv * /*env*/, jobject /*thiz*/) {
    if (g_model != nullptr) {
        llama_model_free(g_model);
        g_model = nullptr;
    }
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_calenda_LlamaBridge_nativeComplete(
        JNIEnv * env, jobject /*thiz*/, jstring prompt_j, jint n_predict) {
    if (g_model == nullptr) {
        return env->NewStringUTF("[error] model not loaded");
    }

    const char * prompt_c = env->GetStringUTFChars(prompt_j, nullptr);
    std::string prompt(prompt_c);
    env->ReleaseStringUTFChars(prompt_j, prompt_c);

    const llama_vocab * vocab = llama_model_get_vocab(g_model);

    // 토크나이즈
    const int n_prompt = -llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(),
                                         nullptr, 0, true, true);
    if (n_prompt <= 0) {
        return env->NewStringUTF("[error] tokenize failed");
    }
    std::vector<llama_token> prompt_tokens(n_prompt);
    if (llama_tokenize(vocab, prompt.c_str(), (int32_t) prompt.size(),
                       prompt_tokens.data(), (int32_t) prompt_tokens.size(), true, true) < 0) {
        return env->NewStringUTF("[error] tokenize failed (2)");
    }

    // 컨텍스트
    llama_context_params cparams = llama_context_default_params();
    cparams.n_ctx   = (uint32_t) (n_prompt + n_predict + 8);
    cparams.n_batch = (uint32_t) std::max(n_prompt, 512);
    cparams.no_perf = true;

    llama_context * ctx = llama_init_from_model(g_model, cparams);
    if (ctx == nullptr) {
        return env->NewStringUTF("[error] context init failed");
    }

    // 그리디 샘플러
    auto sparams = llama_sampler_chain_default_params();
    sparams.no_perf = true;
    llama_sampler * smpl = llama_sampler_chain_init(sparams);
    llama_sampler_chain_add(smpl, llama_sampler_init_greedy());

    std::string result;
    llama_batch batch = llama_batch_get_one(prompt_tokens.data(), (int32_t) prompt_tokens.size());

    int n_decoded = 0;
    for (int n_pos = 0; n_pos + batch.n_tokens < n_prompt + n_predict; ) {
        if (llama_decode(ctx, batch)) {
            LOGE("decode failed");
            break;
        }
        n_pos += batch.n_tokens;

        llama_token new_token_id = llama_sampler_sample(smpl, ctx, -1);
        if (llama_vocab_is_eog(vocab, new_token_id)) {
            break;
        }
        char buf[256];
        int n = llama_token_to_piece(vocab, new_token_id, buf, sizeof(buf), 0, true);
        if (n < 0) {
            break;
        }
        result.append(buf, n);
        batch = llama_batch_get_one(&new_token_id, 1);
        n_decoded++;
        if (n_decoded >= n_predict) {
            break;
        }
    }

    llama_sampler_free(smpl);
    llama_free(ctx);

    return env->NewStringUTF(result.c_str());
}
