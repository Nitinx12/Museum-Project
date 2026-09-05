# monitor_logs.sh

Monitors and cleans up the `logs/` directory at the project root.

## What it does

- Flags log files older than `MAX_AGE_DAYS` (default: 7).
- Flags log files larger than `MAX_SIZE_MB` (default: 5).
- Always preserves the most recently modified log file, regardless of age or size.
- Never deletes anything unless you explicitly run `clean`.

## Usage

```bash
./scripts/bash/monitor_logs.sh                 # Summary report (default, read-only)
./scripts/bash/monitor_logs.sh summary         # Same as above
./scripts/bash/monitor_logs.sh clean           # Delete flagged logs (asks for confirmation)
./scripts/bash/monitor_logs.sh clean --dry-run # Preview what 'clean' would delete
./scripts/bash/monitor_logs.sh clean -y        # Skip the confirmation prompt
./scripts/bash/monitor_logs.sh -h              # Show help
```

## Configuration

Override the defaults via environment variables:

```bash
MAX_AGE_DAYS=14 MAX_SIZE_MB=10 ./scripts/bash/monitor_logs.sh clean
```

## Expected structure

```
project/
├── logs/
│   ├── app.log
│   ├── database.log
│   └── ...
└── scripts/
    └── bash/
        └── monitor_logs.sh
```

## Status codes (summary report)

| Status | Meaning |
|---|---|
| `LATEST` | Most recently modified file; always kept |
| `OLD` | Older than `MAX_AGE_DAYS` |
| `LARGE` | Larger than `MAX_SIZE_MB` |
| `OLD+LARGE` | Both old and large |
| `OK` | Within limits |

## Notes

- Works on both Linux (GNU) and macOS (BSD) via portable `stat` fallbacks.
- Uses nanosecond mtime precision (GNU) to correctly pick the latest file when several logs share the same second.
- Empty subdirectories left behind under `logs/` after a clean are removed automatically; `logs/` itself is never deleted.
- Exits without error if `logs/` doesn't exist.