# pants-agent-skills

Reusable, runtime-neutral agent skill for working in Pants/Pantsbuild repositories.

The repository has two layers:

- `skills/pants/`: the installable skill bundle. Keep it small, portable, and free of local repository assumptions.
- repo-level docs, tests, and scripts: development support for maintaining and validating the skill.

## Agent Runtime Compatibility

The portable artifact is the `skills/pants/` directory:

- `SKILL.md` contains the trigger metadata and short operational workflow.
- `references/` contains longer Pants guidance loaded only when needed.
- `scripts/` contains deterministic helpers such as the tracked-file-safe repo probe.
- `agents/openai.yaml` is an optional OpenAI/Codex adapter. Other agents can ignore it.

For an agent that does not implement this exact skill format, use
`skills/pants/SKILL.md` as the entrypoint instructions and keep the bundled
`references/` and `scripts/` next to it.

See `docs/agent-runtime-compatibility.md` for the runtime-neutral contract.
OpenAI/Codex adapter maintenance links live in `docs/openai-adapter-sources.md`,
outside the portable skill reference set.

## Install

Install by copying `skills/pants/` into the skill directory expected by the
target agent runtime. Prefer an explicit target when adopting a new agent:

```bash
python scripts/install_skill.py --target-root /path/to/agent/skills --dry-run
python scripts/install_skill.py --target-root /path/to/agent/skills --backup
```

The generic default targets `$AGENT_SKILLS_DIR` when set, otherwise
`$HOME/.agents/skills`:

```bash
python scripts/install_skill.py --dry-run
```

Codex/OpenAI-style local discovery is available as a runtime profile, not as
the repository's default contract:

```bash
python scripts/install_skill.py --runtime codex --dry-run
python scripts/install_skill.py --runtime codex --backup
```

Existing installations are not overwritten unless `--force` or `--backup` is
provided.

## Validate

Run the local validation suite before relying on the skill:

```bash
python scripts/validate_skill.py
python -m unittest discover -s tests
python skills/pants/scripts/pants_repo_probe.py --help
python scripts/install_skill.py --dry-run
python scripts/install_skill.py --runtime codex --dry-run
```

`skills/pants/scripts/pants_repo_probe.py` is read-only for tracked project
files. It discovers the nearest `pants.toml`, selects `./pants` when an
executable wrapper exists, parses core configuration, and runs only lightweight
Pants commands unless `--files-only` is used. The default Pants invocations may
still create local cache or daemon state such as `.pants.d/`.

## Development Notes

When improving the skill from a real local repository, extract workflow rules,
not private code or project-specific policy. Put longer Pants detail in
`skills/pants/references/*.md`; keep `skills/pants/SKILL.md` focused on the
agent's first moves, decision points, and validation habits.

Use `docs/agent-field-notes.md` as the repo-local promotion queue for reusable
lessons before moving them into the installable skill bundle.

When validating an installed copy under a hidden directory such as
`.agents/skills/pants`, run targeted checks against the installed helper scripts
if the target repository's normal scanners skip dot-directories.
