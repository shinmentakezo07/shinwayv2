---
paths:
  - "**/*.go"
  - "**/go.mod"
  - "**/go.sum"
---
# Go Coding Style

> Project-tailored Go coding style guidance for this repository.

> Verification note: this repo’s checked-in `CLAUDE.md` prefers `go build ./cmd/server` and `go test ./...` as the default validation loop unless the user explicitly asks for additional tooling.

## Formatting

- **gofmt** and **goimports** are mandatory — no style debates

## Design Principles

- Accept interfaces, return structs
- Keep interfaces small (1-3 methods)

## Error Handling

Always wrap errors with context:

```go
if err != nil {
    return fmt.Errorf("failed to create user: %w", err)
}
```

## Reference

See skill: `golang-patterns` for comprehensive Go idioms and patterns.
