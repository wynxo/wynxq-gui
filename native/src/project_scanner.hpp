#pragma once

#include <cstddef>
#include <string>

namespace wynxq::native {

// Scan one already-authorized directory without following symlinks. Product
// filtering/sorting stays in Python so the native layer only owns filesystem
// I/O and a compact transport format.
std::string scan_directory_json(const std::string& directory,
                                std::size_t max_entries);

}  // namespace wynxq::native
