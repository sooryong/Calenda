cmake_minimum_required(VERSION 3.22.1)

project("calendaragent" LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# --------------------------------------------------------------------------
# llama.cpp — 빌드 시 고정 태그(b9371)로 받아옴. 프로젝트를 self-contained하게 유지.
#   로컬에 이미 클론한 llama.cpp가 있으면 LLAMA_CPP_DIR로 가리켜 오프라인 빌드 가능:
#   -DLLAMA_CPP_DIR=D:/llama.cpp
# --------------------------------------------------------------------------
if(DEFINED LLAMA_CPP_DIR AND EXISTS "${LLAMA_CPP_DIR}/CMakeLists.txt")
    message(STATUS "Using local llama.cpp at ${LLAMA_CPP_DIR}")
    add_subdirectory(${LLAMA_CPP_DIR} ${CMAKE_BINARY_DIR}/llama-build)
else()
    include(FetchContent)
    FetchContent_Declare(
        llama_cpp
        GIT_REPOSITORY https://github.com/ggml-org/llama.cpp.git
        GIT_TAG        b9371
    )
    FetchContent_MakeAvailable(llama_cpp)
endif()

# JNI 브리지 라이브러리
add_library(calendaragent SHARED llama_jni.cpp)

find_library(log-lib log)

target_link_libraries(calendaragent
        llama
        ggml
        android
        ${log-lib})
