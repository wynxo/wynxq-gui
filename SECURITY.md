# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | ✅        |

## Reporting a Security Vulnerability

If you discover a security vulnerability in Wynxq, please report it directly to the maintainers:

- **Email**: security@wynxq.dev (or the maintainer's email)
- **Do NOT** open a public GitHub issue for security concerns

Wynxq's security model:
- All inference runs locally via Ollama on loopback (`127.0.0.1:11434`)
- No telemetry, no cloud dependency, no external API calls
- Desktop control requires explicit user permission via XDG portals (Wayland) or XTEST (X11)
- Commands run with the user's permissions, never elevated
- Destructive commands (deletes, Git resets, package removal) require explicit approval even in Auto mode

## Hardening Tips

- Run Wynxq under a dedicated user account for untrusted workloads
- Use the **Manual** permission mode for maximum control
- Review commands in the permission prompt before approving
- Keep Ollama bound to loopback only
