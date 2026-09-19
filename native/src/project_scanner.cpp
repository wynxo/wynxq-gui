#include "project_scanner.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

#if !defined(_WIN32)
#include <sys/stat.h>
#endif

namespace wynxq::native {
namespace {

struct Entry {
    std::string name;
    std::string path;
    std::uintmax_t size = 0;
    bool is_dir = false;
    bool is_link = false;
};

void append_json_string(std::string& out, const std::string& value) {
    static constexpr char hex[] = "0123456789abcdef";
    out.push_back('"');
    for (unsigned char ch : value) {
        switch (ch) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (ch < 0x20U) {
                    out += "\\u00";
                    out.push_back(hex[(ch >> 4U) & 0x0fU]);
                    out.push_back(hex[ch & 0x0fU]);
                } else {
                    // On Linux filesystem paths are byte strings. Preserve
                    // non-ASCII bytes unchanged; Python decodes the result with
                    // surrogateescape so even unusual filenames round-trip.
                    out.push_back(static_cast<char>(ch));
                }
        }
    }
    out.push_back('"');
}

Entry inspect(const std::filesystem::directory_entry& item) {
    Entry result;
    result.name = item.path().filename().string();
    result.path = item.path().string();

#if defined(_WIN32)
    std::error_code status_error;
    const auto status = item.symlink_status(status_error);
    if (status_error) {
        throw std::filesystem::filesystem_error(
            "could not inspect project entry", item.path(), status_error);
    }
    result.is_link = std::filesystem::is_symlink(status);
    result.is_dir = std::filesystem::is_directory(status);
    if (!result.is_dir && !result.is_link) {
        std::error_code size_error;
        const auto size = item.file_size(size_error);
        if (!size_error) {
            result.size = size;
        }
    }
#else
    struct stat info {};
    if (::lstat(result.path.c_str(), &info) != 0) {
        throw std::filesystem::filesystem_error(
            "could not inspect project entry", item.path(),
            std::error_code(errno, std::generic_category()));
    }
    result.is_link = S_ISLNK(info.st_mode);
    result.is_dir = S_ISDIR(info.st_mode);
    if (!result.is_dir && info.st_size > 0) {
        result.size = static_cast<std::uintmax_t>(info.st_size);
    }
#endif
    return result;
}

std::string serialize(const std::vector<Entry>& entries, bool truncated) {
    std::string out;
    // Avoid repeated growth for ordinary project folders without reserving an
    // amount proportional to the configured upper bound.
    out.reserve(64U + entries.size() * 160U);
    out += "{\"entries\":[";
    bool first = true;
    for (const Entry& entry : entries) {
        if (!first) {
            out.push_back(',');
        }
        first = false;
        out += "{\"name\":";
        append_json_string(out, entry.name);
        out += ",\"path\":";
        append_json_string(out, entry.path);
        out += ",\"isDir\":";
        out += entry.is_dir ? "true" : "false";
        out += ",\"size\":";
        out += std::to_string(entry.size);
        out += ",\"link\":";
        out += entry.is_link ? "true" : "false";
        out.push_back('}');
    }
    out += "],\"truncated\":";
    out += truncated ? "true" : "false";
    out.push_back('}');
    return out;
}

}  // namespace

std::string scan_directory_json(const std::string& directory,
                                std::size_t max_entries) {
    if (directory.empty()) {
        throw std::invalid_argument("project directory is empty");
    }
    // The UI currently asks for at most 4k. Keep a defensive ceiling at the
    // ABI boundary so a corrupt caller cannot make one response enormous.
    max_entries = std::min<std::size_t>(max_entries, 100000U);

    const std::filesystem::path target(directory);
    std::error_code type_error;
    if (!std::filesystem::is_directory(target, type_error) || type_error) {
        if (type_error) {
            throw std::filesystem::filesystem_error(
                "could not inspect project directory", target, type_error);
        }
        throw std::invalid_argument("project path is not a directory");
    }

    std::vector<Entry> entries;
    entries.reserve(std::min<std::size_t>(max_entries, 4096U));
    bool truncated = false;

    std::error_code iterator_error;
    std::filesystem::directory_iterator iterator(target, iterator_error);
    if (iterator_error) {
        throw std::filesystem::filesystem_error(
            "could not list project directory", target, iterator_error);
    }
    const std::filesystem::directory_iterator end;
    while (iterator != end) {
        if (entries.size() >= max_entries) {
            truncated = true;
            break;
        }
        entries.push_back(inspect(*iterator));
        iterator.increment(iterator_error);
        if (iterator_error) {
            throw std::filesystem::filesystem_error(
                "could not continue project directory listing", target,
                iterator_error);
        }
    }
    return serialize(entries, truncated);
}

}  // namespace wynxq::native
