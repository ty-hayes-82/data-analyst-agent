# Sync Refactor Branch

Commit and push current changes to the refactor branch.

## Steps

1. Verify we are on the `refactor` branch: `git branch --show-current`
   - If NOT on refactor, STOP and warn the user
2. Show status: `git status --short`
3. Show diff summary: `git diff --stat`
4. Stage all changes: `git add -A`
5. Create commit with descriptive message based on the changes
6. Push to origin: `git push origin refactor`

## Rules
- NEVER commit to any branch other than `refactor`
- NEVER force push
- Commit message format: `refactor: <what changed>` or `chore: <what changed>`
- If there are no changes, say so and stop
