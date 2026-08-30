# monitor.js

Watches the project directory tree in real time and logs file activity, git
activity, and dependency changes. Zero external dependencies — built on
Node.js core modules only (`fs`, `path`, `crypto`, `child_process`, `os`).
Requires Node.js >= 18.

## What it tracks

- **File/folder changes** — creation, deletion, and content modification.
- **Renames and moves** — matched by content hash, not raw add+delete pairs.
- **Git activity** — new commits, branch switches, and a dirty working tree.
- **Dependency changes** — added, removed, or bumped packages in `package.json`.

## Usage

```bash
node monitor.js [options]
```

| Option | Effect |
|---|---|
| `--dir <path>` | Project root to monitor (default: script's directory) |
| `--interval <ms>` | Debounce window before rescanning (default: 300) |
| `--no-git` | Disable git activity tracking |
| `--no-hash` | Disable content hashing (turns off rename detection, faster on huge repos) |
| `--log-file <path>` | Persistent log location (default: `<project>/.monitor/monitor.log`) |
| `--quiet` | Suppress INFO-level console output (still written to the log file) |

Stop with `Ctrl+C` (SIGINT) or `SIGTERM` for a clean shutdown.

## How it works

1. Takes a full snapshot of the project (path, size, mtime, and optionally a
   SHA-1 hash of every file).
2. Watches for filesystem events using native recursive `fs.watch`, falling
   back automatically to a hand-rolled per-directory watch tree on platforms
   or Node versions where recursive watching isn't supported.
3. On each debounced change, re-snapshots and diffs against the previous
   state to report added, removed, modified, and renamed files.
4. Polls `.git` (watch + safety-net interval) to report new commits, branch
   switches, and uncommitted changes.
5. Diffs `package.json` whenever a dependency file changes, logging each
   added, removed, or version-bumped package.

## Ignored by default

Directories: `.git`, `.monitor`, `node_modules`, `.venv`, `venv`,
`__pycache__`, `.pytest_cache`, `dist`, `build`, `.next`, `.dbt`, `.cache`,
`coverage`, `.turbo`, `.parcel-cache`.

Files: `.DS_Store`, `Thumbs.db`.

`.gitignore` patterns in the project root are also respected on a best-effort
basis, and the monitor's own log file is always excluded to avoid watching
itself.

## Notes

- Files larger than 5 MB are not hashed (size checks and mtime are still
  used to detect modifications).
- If `--dir` isn't a git repo, or `--no-git` is passed, git tracking is
  disabled and noted in the log.
- Uncaught exceptions are logged rather than crashing the process.