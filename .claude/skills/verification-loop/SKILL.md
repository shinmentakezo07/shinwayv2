---
name: verification-loop
description: "A comprehensive verification system for Claude Code sessions."
origin: ECC
---

# Verification Loop Skill

A comprehensive verification system for Claude Code sessions.

## When to Use

Invoke this skill:
- After completing a feature or significant code change
- Before creating a PR
- When you want to ensure quality gates pass
- After refactoring

## Verification Phases

### Phase 1: Build Verification
```bash
# Check the server entrypoint builds
go build ./cmd/server
```

If build fails, STOP and fix before continuing.

### Phase 2: Test Suite
```bash
# Repository baseline verification
go test ./...
```

When the change is localized, also run the most relevant package tests.

If the task specifically involved tricky concurrency, hot paths, or executor changes, consider targeted runs such as:

```bash
go test -race ./internal/runtime/executor
go test -cover ./internal/runtime/executor
```

Report:
- Packages tested
- Passed / failed status
- Any targeted coverage or race checks run

### Phase 3: Optional Extra Checks
```bash
# Only if the user asks for stricter verification or the environment already uses them
go vet ./...
staticcheck ./...
```

Do not claim these are standard repo requirements unless they are already part of the project workflow.

### Phase 4: Security Scan
Check changed Go code for:
- raw secret logging
- missing context propagation on outbound I/O
- unsafe request mutation before forwarding
- buffered handling of streaming responses that should stay streamed
- missing timeout handling on upstream HTTP clients

### Phase 5: Diff Review
```bash
# Show what changed
git diff --stat
git diff --name-only
```

Review each changed file for:
- Unintended changes
- Missing error handling
- Potential edge cases

## Output Format

After running all phases, produce a verification report:

```
VERIFICATION REPORT
==================

Build:     [PASS/FAIL]
Types:     [PASS/FAIL] (X errors)
Lint:      [PASS/FAIL] (X warnings)
Tests:     [PASS/FAIL] (X/Y passed, Z% coverage)
Security:  [PASS/FAIL] (X issues)
Diff:      [X files changed]

Overall:   [READY/NOT READY] for PR

Issues to Fix:
1. ...
2. ...
```

## Continuous Mode

For long sessions, run verification every 15 minutes or after major changes:

```markdown
Set a mental checkpoint:
- After completing each function
- After finishing a component
- Before moving to next task

Run: /verify
```

## Integration with Hooks

This skill complements PostToolUse hooks but provides deeper verification.
Hooks catch issues immediately; this skill provides comprehensive review.
