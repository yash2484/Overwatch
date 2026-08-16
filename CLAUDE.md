# CLAUDE.md - Overwatch

The global `~/.claude/CLAUDE.md` applies. These rules make Overwatch's Git lifecycle explicit.

## Git Workflow

- Treat `main` as integration-only. Before substantive work, create a typed branch such as `feat/<topic>`, `fix/<topic>`, `refactor/<topic>`, or `phase-<number>-<topic>`.
- Keep the primary checkout on `main`; create at most one active linked feature worktree under `.worktrees/<branch>`, and remove merged or obsolete worktrees and branches only after verifying all unique changes are committed or migrated.
- After each coherent feature, fix, or significant update passes its relevant tests and review, create a focused local commit automatically. Use conventional commit messages and keep unrelated changes in separate commits.
- Update `PROGRESS.md` when verified project state changes, and commit that record separately from implementation when practical.
- Never commit secrets, generated local evidence, exported session transcripts, or known-failing work. Stage explicit paths instead of `git add .`.
- Before a PR, run the relevant backend tests and Ruff checks, frontend tests/build when affected, `git diff --check`, and a final code review.
- Pushes, PR creation, and merges require explicit user approval. The user performs the final merge unless they explicitly delegate it.
