# Agent Runtime Compatibility

The repository should stay useful for multiple coding agents, not only Codex.
The stable, portable contract is the `skills/pants/` directory.

## Portable Bundle

Required by all runtimes:

- `SKILL.md`: trigger metadata plus concise workflow instructions.
- `references/`: optional one-hop reference documents.
- `scripts/`: deterministic helper scripts that can run from any checkout.

Agent-specific metadata is optional:

- `agents/openai.yaml`: OpenAI/Codex UI metadata. Other runtimes can ignore it.

Do not put runtime-specific policy into `SKILL.md` unless that policy is also
valid for non-OpenAI agents.

## Installation Model

Use an explicit target root when adopting a new runtime:

```bash
python scripts/install_skill.py --target-root /path/to/runtime/skills --dry-run
python scripts/install_skill.py --target-root /path/to/runtime/skills --backup
```

Generic default:

- `$AGENT_SKILLS_DIR` if set,
- otherwise `$HOME/.agents/skills`.

Runtime profiles are convenience presets only. They must not change the skill
content:

- `generic`: generic default above,
- `codex`: `${CODEX_HOME:-$HOME/.codex}/skills`.

## Manual Adoption

For agents without automatic skill discovery:

1. Point the agent at `skills/pants/SKILL.md`.
2. Keep `references/` and `scripts/` in the same directory.
3. Tell the agent to run `scripts/pants_repo_probe.py --pretty` from the skill
   bundle when orienting in a Pants repository.

This preserves the same workflow without depending on a specific agent runtime.
