cmake_minimum_required(VERSION 3.20)
project(wynxq_native_core LANGUAGES CXX)

option(WYNXQ_NATIVE_BUILD_TESTS "Build the native core tests" ON)

add_library(wynxq_native_core SHARED
    src/permission_policy.cpp
    src/project_scanner.cpp
    src/c_api.cpp
)

target_compile_features(wynxq_native_core PUBLIC cxx_std_20)
target_compile_definitions(wynxq_native_core PRIVATE WYNXQ_NATIVE_BUILD=1)
target_include_directories(wynxq_native_core
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

set_target_properties(wynxq_native_core PROPERTIES
    OUTPUT_NAME "wynxq_native_core"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)

target_compile_options(wynxq_native_core PRIVATE
    $<$<CXX_COMPILER_ID:GNU,Clang>:-Wall;-Wextra;-Wpedantic;-Wconversion;-Wshadow>
)

if(WYNXQ_NATIVE_BUILD_TESTS)
    enable_testing()

    add_executable(wynxq_native_core_tests
        tests/permission_policy_test.cpp
    )
    target_compile_features(wynxq_native_core_tests PRIVATE cxx_std_20)
    target_link_libraries(wynxq_native_core_tests PRIVATE wynxq_native_core)
    target_include_directories(wynxq_native_core_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

    add_test(NAME wynxq_native_core_tests COMMAND wynxq_native_core_tests)
endif()
