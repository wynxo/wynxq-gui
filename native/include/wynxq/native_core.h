#pragma once

#include <stddef.h>

#if defined(_WIN32)
#  if defined(WYNXQ_NATIVE_BUILD)
#    define WYNXQ_NATIVE_API __declspec(dllexport)
#  else
#    define WYNXQ_NATIVE_API __declspec(dllimport)
#  endif
#else
#  define WYNXQ_NATIVE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Stable C ABI for the native core.
 *
 * Literal string results (version and normalized permission mode) are owned by
 * the library for the lifetime of the process. Scanner/error strings are owned
 * by the library and remain valid until the next scanner call on the same
 * thread. Callers must never free any returned pointer. Integer booleans are
 * 0/1 so the ABI stays straightforward for Python ctypes, Rust FFI, or a future
 * Qt C++ application shell.
 */

WYNXQ_NATIVE_API const char* wynxq_native_version(void);
WYNXQ_NATIVE_API const char* wynxq_normalize_permission_mode(const char* mode);
WYNXQ_NATIVE_API int wynxq_command_is_destructive(const char* command);
WYNXQ_NATIVE_API int wynxq_permission_needs_confirmation(
    const char* action,
    const char* mode,
    const char* command
);

/*
 * Scan exactly one already-authorized directory without following symlinks.
 * The JSON object is {"entries":[...],"truncated":bool}. Each entry contains
 * name, absolute path, isDir, size, and link. Product filtering and sorting are
 * intentionally left to the caller.
 *
 * Returns NULL on failure; wynxq_native_last_error() then contains a readable
 * diagnostic. max_entries is defensively capped inside the native core.
 */
WYNXQ_NATIVE_API const char* wynxq_scan_directory_json(
    const char* directory,
    size_t max_entries
);
WYNXQ_NATIVE_API const char* wynxq_native_last_error(void);

#ifdef __cplusplus
}
#endif
