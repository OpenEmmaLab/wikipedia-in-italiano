# Planning

**Every plan lives in a GitHub issue on the `origin` repo.** A plan that is only in
the chat does not exist — never start implementing one.

When asked to plan, follow this order:

1. **Check the tooling.** `gh auth status` must succeed and
   `gh repo view --json viewerPermission` must report write access to the repo
   behind `origin`. If either fails, stop and ask the user to install `gh`
   (`brew install gh`) and run `gh auth login` — do not plan until it works.
   Ask once; do not retry the same failing command.
2. **Find the target issue.** Ask the user which existing issue holds the plan,
   or whether to create a new one. Use `gh issue list` to offer the open issues.
   Do not guess — ask, unless the user already named an issue number.
3. **Write the plan into the issue body** with `gh issue create` or
   `gh issue edit`, not into a local file and not only into the chat.
4. **Implement only from the issue.** If asked to implement something with no
   issue behind it, refuse and offer to open one first.
