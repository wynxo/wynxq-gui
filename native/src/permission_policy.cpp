#include "permission_policy.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <regex>
#include <string>

namespace wynxq::native {
namespace {

std::string ascii_lower(std::string_view value) {
    std::string out(value);
    std::transform(out.begin(), out.end(), out.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return out;
}

std::string trim_ascii(std::string_view value) {
    auto first = value.begin();
    auto last = value.end();
    while (first != last && std::isspace(static_cast<unsigned char>(*first)) != 0) {
        ++first;
    }
    while (last != first && std::isspace(static_cast<unsigned char>(*(last - 1))) != 0) {
        --last;
    }
    return std::string(first, last);
}

bool is_one_of(std::string_view value, const auto& entries) noexcept {
    return std::find(entries.begin(), entries.end(), value) != entries.end();
}

const std::array<std::regex, 23>& destructive_patterns() {
    // Compile once per process. These patterns deliberately match categories
    // that can erase data, alter accounts/disks/packages, or discard Git work.
    static const std::array<std::regex, 23> patterns = {
        std::regex(R"(\brm\s+(-[a-z]*[rf][a-z]*\s+)+)", std::regex::icase),
        std::regex(R"(\brmdir\s+/)", std::regex::icase),
        std::regex(R"(\bmkfs(\.[a-z0-9]+)?\b)", std::regex::icase),
        std::regex(R"(\b(fdisk|sfdisk|parted|wipefs|shred|blkdiscard)\b)", std::regex::icase),
        std::regex(R"(\bdd\b[^|;&]*\bof=/dev/)", std::regex::icase),
        std::regex(R"(>\s*/dev/(sd|nvme|vd|hd|mmcblk))", std::regex::icase),
        std::regex(R"(\b(shutdown|reboot|poweroff|halt)\b)", std::regex::icase),
        std::regex(R"(\bsystemctl\s+(poweroff|reboot|halt|isolate)\b)", std::regex::icase),
        std::regex(R"(\b(sudo|doas|pkexec|su)\s)", std::regex::icase),
        std::regex(R"(\b(userdel|usermod|groupdel|chpasswd|visudo)\b)", std::regex::icase),
        std::regex(R"((^|[;&|]\s*)passwd\b)", std::regex::icase),
        std::regex(R"(\bchmod\s+(-[a-z]+\s+)*(777|-R\s+777))", std::regex::icase),
        std::regex(R"(\bcho(wn|rp)\s+(-[a-z]+\s+)*[^\s]+\s+/(\s|$))", std::regex::icase),
        std::regex(R"(\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|k|da)?sh\b)", std::regex::icase),
        std::regex(R"(\b(apt|apt-get|dnf|yum|pacman|zypper|snap|flatpak|pip3?|npm|cargo)\b[^|;&]*\b(remove|purge|uninstall|autoremove|-R|-Rns)\b)", std::regex::icase),
        std::regex(R"(\bgit\s+(push[^|;&]*--force|reset\s+--hard|clean\s+-[a-z]*f))", std::regex::icase),
        std::regex(R"(\bcrontab\s+-r\b)", std::regex::icase),
        std::regex(R"(\bfind\b[^|;&]*-(delete|exec\s+rm)\b)", std::regex::icase),
        std::regex(R"(\bkill(all)?\s+(-9\s+)?-1\b)", std::regex::icase),
        std::regex(R"(\bdocker\s+(system\s+prune|volume\s+rm|rm\s+-f)\b)", std::regex::icase),
        std::regex(R"(\btruncate\b[^|;&]*-s\s*0\b)", std::regex::icase),
        std::regex(R"(:\(\)\s*\{[^}]*\|[^}]*&[^}]*\})", std::regex::icase),
        std::regex(R"(\b(init\s+0|telinit\s+[06])\b)", std::regex::icase),
    };
    return patterns;
}

}  // namespace

PermissionMode normalize_permission_mode(std::string_view mode) noexcept {
    const std::string value = ascii_lower(trim_ascii(mode));
    if (value == "manual" || value == "ask") {
        return PermissionMode::Manual;
    }
    if (value == "auto") {
        return PermissionMode::Auto;
    }
    if (value == "full") {
        return PermissionMode::Full;
    }
    // "safe_auto" is the pre-ladder id. Unknown/corrupt values also fall
    // back to Safe; they must never silently expand privileges.
    return PermissionMode::Safe;
}

std::string_view permission_mode_id(PermissionMode mode) noexcept {
    switch (mode) {
        case PermissionMode::Manual: return "manual";
        case PermissionMode::Safe: return "safe";
        case PermissionMode::Auto: return "auto";
        case PermissionMode::Full: return "full";
    }
    return "safe";
}

bool command_is_destructive(std::string_view command) {
    if (command.empty()) {
        return false;
    }
    const std::string input(command);
    const auto& patterns = destructive_patterns();
    return std::any_of(patterns.begin(), patterns.end(), [&input](const std::regex& pattern) {
        return std::regex_search(input, pattern);
    });
}

ActionRisk action_risk(std::string_view action, std::string_view command) {
    static constexpr std::array<std::string_view, 6> low_risk = {
        "screenshot", "list_apps", "wait", "move_pointer", "scroll", "remember"
    };
    static constexpr std::array<std::string_view, 7> sensitive = {
        "type_text", "press_key", "hold_key", "run_command",
        "click", "hold_button", "drag"
    };

    const std::string lowered = ascii_lower(trim_ascii(action));
    if (lowered == "run_command" && command_is_destructive(command)) {
        return ActionRisk::Destructive;
    }
    if (is_one_of(std::string_view(lowered), low_risk)) {
        return ActionRisk::Low;
    }
    if (is_one_of(std::string_view(lowered), sensitive)) {
        return ActionRisk::Sensitive;
    }
    return ActionRisk::Normal;
}

bool needs_confirmation(std::string_view action, PermissionMode mode,
                        std::string_view command) {
    const ActionRisk risk = action_risk(action, command);
    if (mode == PermissionMode::Full || risk == ActionRisk::Low) {
        return false;
    }
    if (mode == PermissionMode::Auto) {
        return risk == ActionRisk::Destructive;
    }
    if (mode == PermissionMode::Manual) {
        return true;
    }
    // Safe mode is intentionally conservative around pointer actions too.
    // A click or drag can submit, delete, purchase, or move data just as a key
    // press can; merely moving/scrolling the pointer remains prompt-free.
    return risk == ActionRisk::Sensitive || risk == ActionRisk::Destructive;
}

}  // namespace wynxq::native
