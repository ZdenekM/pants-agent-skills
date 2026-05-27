# Agent Field Notes

Local knowledge base for reusable lessons from applying `pants-agent-skills` in
real repositories.

This file is development input for the skill. It is not installed with the
portable `skills/pants/` bundle. Keep entries general enough to improve the
skill without leaking private repository names, paths, credentials, or
project-specific policy.

## How To Add Notes

Add newest entries at the top of `## Entries`. Keep each entry compact and
actionable:

- `Context`: anonymized repository shape and Pants version when relevant.
- `Observed`: concrete behavior seen by the agent.
- `Risk`: why the current skill can mislead agents or miss a quality issue.
- `Candidate skill change`: how to improve instructions, references, scripts,
  tests, or docs.
- `Status`: `open`, `promoted`, or `rejected`, with the target file when known.

Prefer rules that are reusable across repositories. If a lesson is specific to a
single repo, keep it in that repo's `AGENTS.md`, plans, or local memory instead.

## Entries

### 2026-05-26 - First Test Slice Must Prove Target Ownership

- Context: Small Python-only Pants 2.28 repository that initially had no
  `tests/` tree and no `python_tests` targets.
- Observed:
  - A migration plan correctly added future `pants test tests::` checks, but the
    first slice creating tests did not explicitly require `tests/BUILD`,
    `python_tests()`, `pants tailor tests`, or `pants list tests::` before the
    test run.
  - In a no-wrapper repository, a Pants version bump in `pants.toml` also needed
    an explicit `pants --version` runner preflight to prove the PATH runner could
    bootstrap the configured version.
- Risk:
  - Agents can report a test plan that looks complete while the first test files
    are not owned by Pants, or while a PATH-based Pants runner is unable to run
    the updated configured Pants version.
- Candidate skill change:
  - In Python test guidance, say that the first test-adding slice should create
    or generate the `python_tests` target and verify it with `pants list
    tests::` before relying on `pants test tests::`.
  - In dependency/toolchain update guidance, include `pants --version` after a
    `pants.toml` version change when the repo has no executable wrapper.
- Status: promoted to `skills/pants/references/pants-python.md` and
  `skills/pants/references/pants-core-workflow.md`.

### 2026-05-26 - Do Not Parallelize Read-Only Pants Introspection

- Context: Small Python-only Pants 2.28 repository with source root `.`, one
  resolve, and a repo instruction to serialize Pants commands.
- Observed:
  - Running two read-only Pants introspection commands at the same time
    (`pants list ...` and `pants roots`) still triggered Pants' concurrency
    lock waiting message.
  - The command completed, but the evidence stream became noisier and confirmed
    that "read-only" does not mean "safe to run in parallel" for Pants.
- Risk:
  - Agents may parallelize harmless-looking Pants commands while gathering
    context, creating lock waits, confusing timing, or worse signal in final
    verification logs.
- Candidate skill change:
  - Add an explicit warning near the core commands/probe guidance: if a target
    repo says Pants is lock-prone or serialized, that applies to read-only
    discovery commands as well as fmt/lint/check/test/package.
  - In examples, avoid batching Pants commands through generic parallel tool
    wrappers even when each individual command is read-only.
- Status: promoted to `skills/pants/SKILL.md` and
  `skills/pants/references/parallel-pants-workspaces.md`.

### 2026-05-26 - Do Not Use PyPI Index Alone For Pants 2 Runner Selection

- Context: Python-only Pants 2.28 repository without an executable `./pants`
  wrapper, using `pants` from `PATH`.
- Observed:
  - `python -m pip index versions pantsbuild.pants` reported only the old 1.x
    package stream, while the configured and executable runner was Pants
    2.28.0.
  - `pants --version` and the repo probe gave the authoritative active runner
    version for the checkout.
- Risk:
  - Treating the `pantsbuild.pants` PyPI package index as the Pants 2 upgrade
    source can lead agents to record a false "latest" version or downgrade
    target.
- Candidate skill change:
  - For Pants version audits, prefer `pants --version`, `pants.toml`, and
    official Pants release guidance over `pip index pantsbuild.pants`.
  - If a plan explicitly asks for the pip-index audit, record the mismatch and
    keep the active Pants runner unchanged unless the repo has a separate
    approved upgrade path.
- Status: promoted to `skills/pants/references/pants-core-workflow.md`.

### 2026-05-26 - First Install In A Small Python-Only Pants Repo

- Context: Small Python-only Pants 2.28 repository with one user resolve,
  `lockfile.txt`, no executable `./pants` wrapper, and an installed repo-local
  copy of `skills/pants/`.
- Observed:
  - The probe correctly selected `pants` from `PATH`, found source root `.`, and
    reported the configured Python resolve.
  - The probe is read-only with respect to tracked project files, but its
    default mode runs `pants --version` and `pants roots`, which can create
    local Pants state, often ignored, such as `.pants.d/`.
  - `pants generate-lockfiles --resolve=<resolve>` in Pants 2.28 did not expose
    a no-update mode. Regenerating after one direct Git requirement revision
    also refreshed unrelated open transitive dependencies.
  - Installing the skill under a dot-directory such as `.agents/skills/pants`
    can make root-level quality tools skip the bundled Python helper script
    unless they are run against the hidden root explicitly.
  - Repositories without a local `./pants` wrapper need instructions that
    override the skill's default preference for `./pants` while still preserving
    per-repo runner discovery.
- Risk:
  - Saying that the probe "does not modify the repository" is too broad; agents
    may be surprised by local cache/daemon files even though tracked files are
    untouched.
  - A lockfile refresh can look like a narrow dependency sync while actually
    changing unrelated transitive versions. This is easy to miss if agents only
    check that Pants passes.
  - Quality evidence can be incomplete when helper Python lives under a hidden
    installed-skill directory and root scans ignore dot-directories.
- Candidate skill change:
  - Reword `SKILL.md`, `README.md`, and the probe docstring to say the probe is
    read-only for tracked/project source files, while Pants subcommands may
    create local cache or daemon state.
  - Replace the old `--skip-pants-commands` mode with a clearer `--files-only`
    flag, and mention when to use it.
  - Add reference guidance for lockfile updates: inspect `git diff --numstat`
    and named package/version diffs after `generate-lockfiles`; if unrelated
    transitive drift appears, either explicitly accept it or narrow the lockfile
    change using a repo-approved workflow.
  - Add a note that installed skill helper scripts may need targeted quality
    checks when the target repo's normal scanner ignores dot-directories.
  - Keep runner selection as discovery-first: prefer `./pants` when executable,
    but let target repo instructions require `pants` from `PATH`.
- Status: promoted by item:
  - probe tracked-file contract and `--files-only`: `README.md`,
    `skills/pants/SKILL.md`, and `skills/pants/scripts/pants_repo_probe.py`;
  - lockfile drift checks: `skills/pants/references/pants-python.md`;
  - hidden installed-skill validation: `README.md`;
  - runner discovery remains covered by `skills/pants/SKILL.md` and
    `skills/pants/references/pants-core-workflow.md`.
