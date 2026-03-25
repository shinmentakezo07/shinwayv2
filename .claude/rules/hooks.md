---
paths:
  - "**/*.go"
  - "**/go.mod"
  - "**/go.sum"
---
# Go Hooks

> Project-tailored Go hook guidance for this repository.

> Prefer lightweight hooks aligned with repo conventions. Auto-formatting Go files is helpful; heavyweight verification hooks should not assume `staticcheck` is installed unless the user asks for it.

## PostToolUse Hooks

Configure in `~/.claude/settings.json`:

- **gofmt/goimports**: Auto-format `.go` files after edit
- **go vet**: Run static analysis after editing `.go` files
- **staticcheck**: Run extended static checks on modified packages
