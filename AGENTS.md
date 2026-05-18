# Agent instructions for pants-agent-skills

This repository maintains a reusable, runtime-neutral Agent Skill for Pants/Pantsbuild.

- Keep `skills/pants/SKILL.md` concise and operational.
- Put longer Pants details in `skills/pants/references/*.md`.
- Keep Codex/OpenAI-specific behavior in optional adapters or runtime profiles, not in the portable skill instructions.
- Keep the installable skill bundle free of private local paths, secrets, and project-specific assumptions.
- Helper scripts must be deterministic, cross-platform, read-only by default, and tested.
- Validate frontmatter, references, scripts, and installer behavior before considering the skill ready.
- When improving the skill from a real local Pants repo, extract general workflow rules only; do not copy private code or credentials.
