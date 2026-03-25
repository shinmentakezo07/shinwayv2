---
description: Git workflow and commit message conventions for this project.
---
# Git Workflow

## Commit Message Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`

- `feat`: new feature (MINOR in semver)
- `fix`: bug fix (PATCH in semver)
- `perf`: performance improvement
- `refactor`: code change that neither fixes a bug nor adds a feature
- `test`: adding or updating tests
- `docs`: documentation only
- `chore`: maintenance (deps, config, tooling)
- `ci`: CI/CD changes
- `BREAKING CHANGE`: footer or `!` after type — major API change

Examples:
```
feat(auth): add per-key daily token budget enforcement
fix(pipeline): reset retry context before each attempt
perf(rate_limit): LRU-bound _per_key_limiters to max 10k entries
docs: update UPDATES.md for session 26
```

## Branching

- Main branch: `main` — production-ready at all times.
- Feature branches: `feature/<issue-id>-description`
- Hotfix branches: `hotfix/v<x.y.z>`
- Never commit directly to `main`.

## Pull Requests

1. Analyze full commit history with `git diff main...HEAD`
2. Write comprehensive PR summary
3. Include test plan
4. All CI checks must pass before merge

## After Every Completed Task

1. Update `UPDATES.md` with what changed, which lines/functions, why, and commit SHAs.
2. Commit `UPDATES.md` as the final step.
3. Push.

Note: Attribution disabled globally via `~/.claude/settings.json`.
