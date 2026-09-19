#pragma once

#include <string_view>

namespace wynxq::native {

enum class PermissionMode {
    Manual,
    Safe,
    Auto,
    Full,
};

enum class ActionRisk {
    Low,
    Normal,
    Sensitive,
    Destructive,
};

PermissionMode normalize_permission_mode(std::string_view mode) noexcept;
std::string_view permission_mode_id(PermissionMode mode) noexcept;
bool command_is_destructive(std::string_view command);
ActionRisk action_risk(std::string_view action, std::string_view command = {});
bool needs_confirmation(std::string_view action, PermissionMode mode,
                        std::string_view command = {});

}  // namespace wynxq::native
