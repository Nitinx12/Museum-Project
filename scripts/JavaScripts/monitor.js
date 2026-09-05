#!/usr/bin/env node
/**
 * monitor.js — Production-grade project monitor
 * ------------------------------------------------------------------
 * Watches a project directory tree and reports, in real time:
 *
 *   • File / folder creation, deletion and content modification
 *   • File / folder RENAMES and MOVES (matched by content hash, not
 *     just raw add+delete events)
 *   • Git activity: new commits, branch switches, dirty working tree
 *   • Dependency version changes in package.json (added / removed /
 *     bumped packages)
 *
 * Zero external dependencies — built entirely on Node.js core
 * modules (fs, path, crypto, child_process, os). Works with Node.js
 * >= 18. On platforms/Node versions where native recursive fs.watch
 * isn't available, it falls back automatically to a hand-rolled
 * recursive watch tree.
 *
 * Usage:
 *   node monitor.js [options]
 *
 * Options:
 *   --dir <path>        Project root to monitor (default: script dir)
 *   --interval <ms>      Debounce window before rescanning (default: 300)
 *   --no-git             Disable git activity tracking
 *   --no-hash            Disable content hashing (rename detection off,
 *                        faster on huge repos)
 *   --log-file <path>    Where to write the persistent log
 *                        (default: <project>/.monitor/monitor.log)
 *   --quiet              Suppress INFO-level console output (still logged)
 *
 * Stop with Ctrl+C (SIGINT) or SIGTERM for a clean shutdown.
 * ------------------------------------------------------------------
 */

"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const os = require("os");
const { execFile } = require("child_process");

// ────────────────────────────────────────────────────────────────
// 1. CONFIGURATION
// ────────────────────────────────────────────────────────────────

function parseArgs(argv) {
    const out = {};
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === "--dir") out.dir = argv[++i];
        else if (a === "--interval") out.interval = argv[++i];
        else if (a === "--log-file") out.logFile = argv[++i];
        else if (a === "--no-git") out.git = false;
        else if (a === "--no-hash") out.hash = false;
        else if (a === "--quiet") out.quiet = true;
    }
    return out;
}

const CLI = parseArgs(process.argv.slice(2));
const PROJECT_DIR = path.resolve(CLI.dir || __dirname);

const CONFIG = {
    projectDir: PROJECT_DIR,
    debounceMs: Number(CLI.interval) || 300,   // quiet period before a rescan
    gitPollMs: 2000,                           // fallback poll for git changes
    hashEnabled: CLI.hash !== false,           // content hashing → rename detection
    hashMaxBytes: 5 * 1024 * 1024,             // skip hashing files bigger than 5MB
    logFile: CLI.logFile || path.join(PROJECT_DIR, ".monitor", "monitor.log"),
    quiet: Boolean(CLI.quiet),
    ignoreDirs: new Set([
        ".git", ".monitor", "node_modules", ".venv", "venv", "__pycache__",
        ".pytest_cache", "dist", "build", ".next", ".dbt",
        ".cache", "coverage", ".turbo", ".parcel-cache",
    ]),
    ignoreFiles: new Set([".DS_Store", "Thumbs.db"]),
    depFiles: ["package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"],
};

// Never let the monitor's own log file trigger itself in an endless loop.
const LOG_RELATIVE = path.relative(CONFIG.projectDir, CONFIG.logFile);

// ────────────────────────────────────────────────────────────────
// 2. LOGGER
// ────────────────────────────────────────────────────────────────

const COLORS = {
    reset: "\x1b[0m", gray: "\x1b[90m", green: "\x1b[32m",
    yellow: "\x1b[33m", red: "\x1b[31m", cyan: "\x1b[36m",
    magenta: "\x1b[35m", blue: "\x1b[34m", bold: "\x1b[1m",
};

const LEVEL_COLOR = {
    INFO: COLORS.cyan, WARN: COLORS.yellow, ERROR: COLORS.red,
    ADDED: COLORS.green, REMOVED: COLORS.red, MODIFIED: COLORS.yellow,
    RENAMED: COLORS.magenta, GIT: COLORS.blue, DEP: COLORS.bold + COLORS.green,
};

fs.mkdirSync(path.dirname(CONFIG.logFile), { recursive: true });
const logStream = fs.createWriteStream(CONFIG.logFile, { flags: "a" });

function timestamp() {
    return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function log(level, message) {
    logStream.write(`[${timestamp()}] [${level}] ${message}\n`);
    if (CONFIG.quiet && level === "INFO") return;
    const color = LEVEL_COLOR[level] || COLORS.reset;
    console.log(
        `${COLORS.gray}[${timestamp()}]${COLORS.reset} ${color}${level.padEnd(8)}${COLORS.reset} ${message}`
    );
}

// ────────────────────────────────────────────────────────────────
// 3. IGNORE RULES  (defaults + best-effort .gitignore support)
// ────────────────────────────────────────────────────────────────

function loadGitignorePatterns(dir) {
    const gi = path.join(dir, ".gitignore");
    if (!fs.existsSync(gi)) return [];
    return fs.readFileSync(gi, "utf8")
        .split("\n")
        .map(l => l.trim())
        .filter(l => l && !l.startsWith("#"));
}

function globToRegex(pattern) {
    let p = pattern.replace(/\/$/, "");
    p = p.replace(/[.+^${}()|[\]\\]/g, "\\$&");
    p = p.replace(/\*\*/g, "§DOUBLESTAR§")
         .replace(/\*/g, "[^/]*")
         .replace(/§DOUBLESTAR§/g, ".*")
         .replace(/\?/g, ".");
    return new RegExp(`(^|/)${p}(/|$)`);
}

const GITIGNORE_PATTERNS = loadGitignorePatterns(CONFIG.projectDir).map(globToRegex);

function shouldIgnore(fullPath) {
    const relative = path.relative(CONFIG.projectDir, fullPath);
    if (!relative || relative.startsWith("..")) return false;
    if (relative === LOG_RELATIVE || relative.startsWith(LOG_RELATIVE + path.sep)) return true;

    const parts = relative.split(path.sep);
    if (parts.some(p => CONFIG.ignoreDirs.has(p))) return true;
    if (CONFIG.ignoreFiles.has(parts[parts.length - 1])) return true;

    const normalized = parts.join("/");
    return GITIGNORE_PATTERNS.some(re => re.test(normalized));
}

// ────────────────────────────────────────────────────────────────
// 4. SNAPSHOT ENGINE  (indexes every file under the project root)
// ────────────────────────────────────────────────────────────────

function hashFile(fullPath, size) {
    if (!CONFIG.hashEnabled || size > CONFIG.hashMaxBytes) return null;
    try {
        return crypto.createHash("sha1").update(fs.readFileSync(fullPath)).digest("hex");
    } catch {
        return null;
    }
}

function walk(dir, out) {
    let entries;
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (err) {
        log("ERROR", `Cannot read directory ${dir}: ${err.message}`);
        return out;
    }

    for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (shouldIgnore(fullPath)) continue;

        if (entry.isDirectory()) {
            walk(fullPath, out);
        } else if (entry.isFile()) {
            try {
                const stat = fs.statSync(fullPath);
                out.set(path.relative(CONFIG.projectDir, fullPath), {
                    size: stat.size,
                    mtimeMs: stat.mtimeMs,
                    hash: hashFile(fullPath, stat.size),
                });
            } catch {
                /* file vanished mid-scan — ignore */
            }
        }
    }
    return out;
}

function takeSnapshot() {
    return walk(CONFIG.projectDir, new Map());
}

// ────────────────────────────────────────────────────────────────
// 5. DIFF + RENAME/MOVE DETECTION
// ────────────────────────────────────────────────────────────────

function diffSnapshots(before, after) {
    const added = [];
    const removed = [];
    const modified = [];

    for (const [file, meta] of after) {
        if (!before.has(file)) {
            added.push(file);
        } else {
            const prev = before.get(file);
            if (
                prev.size !== meta.size ||
                prev.mtimeMs !== meta.mtimeMs ||
                (meta.hash && prev.hash && meta.hash !== prev.hash)
            ) {
                modified.push(file);
            }
        }
    }
    for (const file of before.keys()) {
        if (!after.has(file)) removed.push(file);
    }

    // Match removed <-> added by identical (non-empty) content hash.
    // This is what turns a raw "delete X, create Y" pair into a single
    // readable RENAMED/MOVED event.
    const renamed = [];
    if (CONFIG.hashEnabled) {
        const removedByHash = new Map();
        for (const file of removed) {
            const meta = before.get(file);
            if (meta.hash && meta.size > 0) removedByHash.set(meta.hash, file);
        }
        for (let i = added.length - 1; i >= 0; i--) {
            const file = added[i];
            const meta = after.get(file);
            if (meta.hash && meta.size > 0 && removedByHash.has(meta.hash)) {
                const oldFile = removedByHash.get(meta.hash);
                renamed.push({ from: oldFile, to: file });
                removedByHash.delete(meta.hash);
                added.splice(i, 1);
                const idx = removed.indexOf(oldFile);
                if (idx !== -1) removed.splice(idx, 1);
            }
        }
    }

    return { added, removed, modified, renamed };
}

function reportDiff(diff) {
    for (const { from, to } of diff.renamed) log("RENAMED", `${from}  →  ${to}`);
    for (const file of diff.added) log("ADDED", file);
    for (const file of diff.removed) log("REMOVED", file);
    for (const file of diff.modified) log("MODIFIED", file);
}

// ────────────────────────────────────────────────────────────────
// 6. FILE SYSTEM WATCHER  (native recursive, manual fallback)
// ────────────────────────────────────────────────────────────────

let snapshot = takeSnapshot();
let debounceTimer = null;
let usingNativeRecursive = false;
const activeWatchers = [];

function scheduleRescan() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(runRescan, CONFIG.debounceMs);
}

function runRescan() {
    const fresh = takeSnapshot();
    const diff = diffSnapshots(snapshot, fresh);
    if (diff.added.length || diff.removed.length || diff.modified.length || diff.renamed.length) {
        reportDiff(diff);
        checkDependencyChanges(snapshot, fresh);
    }
    snapshot = fresh;
}

function onRawEvent(eventType, changedPath) {
    if (changedPath && shouldIgnore(changedPath)) return;
    scheduleRescan();

    if (!usingNativeRecursive && changedPath) {
        try {
            if (fs.statSync(changedPath).isDirectory()) watchDirManual(changedPath);
        } catch {
            /* deleted before we could stat it — fine */
        }
    }
}

function watchDirManual(dir) {
    try {
        const watcher = fs.watch(dir, { persistent: true }, (eventType, filename) => {
            if (!filename) return;
            onRawEvent(eventType, path.join(dir, filename));
        });
        activeWatchers.push(watcher);
    } catch (err) {
        log("ERROR", `Cannot watch ${dir}: ${err.message}`);
    }
}

function attachManualWatchers(dir) {
    if (shouldIgnore(dir)) return;
    watchDirManual(dir);
    let entries;
    try {
        entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
        return;
    }
    for (const entry of entries) {
        if (entry.isDirectory()) {
            const full = path.join(dir, entry.name);
            if (!shouldIgnore(full)) attachManualWatchers(full);
        }
    }
}

function setupWatchers() {
    // Fast path: native recursive watching (macOS + Windows always;
    // Linux on recent Node versions). Falls back to a hand-rolled
    // recursive watch tree — the same technique the previous version
    // of this script used — if it's unsupported or errors at runtime.
    try {
        const watcher = fs.watch(
            CONFIG.projectDir,
            { persistent: true, recursive: true },
            (eventType, filename) => {
                if (!filename) return;
                onRawEvent(eventType, path.join(CONFIG.projectDir, filename));
            }
        );
        watcher.on("error", err => {
            log("WARN", `Recursive watch failed at runtime (${err.message}); switching to manual mode`);
            try { watcher.close(); } catch { /* already closed */ }
            usingNativeRecursive = false;
            attachManualWatchers(CONFIG.projectDir);
        });
        activeWatchers.push(watcher);
        usingNativeRecursive = true;
        log("INFO", "Using native recursive fs.watch");
    } catch (err) {
        log("WARN", `Native recursive watch unavailable (${err.code || err.message}); using per-directory watchers`);
        usingNativeRecursive = false;
        attachManualWatchers(CONFIG.projectDir);
    }
}

// ────────────────────────────────────────────────────────────────
// 7. DEPENDENCY / LIBRARY VERSION TRACKING
// ────────────────────────────────────────────────────────────────

function readJsonSafe(fullPath) {
    try {
        return JSON.parse(fs.readFileSync(fullPath, "utf8"));
    } catch {
        return null;
    }
}

function extractDeps(pkgJson) {
    if (!pkgJson) return {};
    return {
        ...(pkgJson.dependencies || {}),
        ...(pkgJson.devDependencies || {}),
        ...(pkgJson.optionalDependencies || {}),
    };
}

let lastDeps = extractDeps(readJsonSafe(path.join(CONFIG.projectDir, "package.json")));

function checkDependencyChanges(before, after) {
    const touchedDepFile = CONFIG.depFiles.some(
        f => after.has(f) && (!before.has(f) || before.get(f).mtimeMs !== after.get(f).mtimeMs)
    );
    if (!touchedDepFile) return;

    const pkgPath = path.join(CONFIG.projectDir, "package.json");
    if (!fs.existsSync(pkgPath)) return;

    const newDeps = extractDeps(readJsonSafe(pkgPath));
    const allNames = new Set([...Object.keys(lastDeps), ...Object.keys(newDeps)]);

    for (const name of allNames) {
        const oldV = lastDeps[name];
        const newV = newDeps[name];
        if (oldV === newV) continue;
        if (!oldV) log("DEP", `${name} added @ ${newV}`);
        else if (!newV) log("DEP", `${name} removed (was ${oldV})`);
        else log("DEP", `${name}  ${oldV}  →  ${newV}`);
    }
    lastDeps = newDeps;
}

// ────────────────────────────────────────────────────────────────
// 8. GIT ACTIVITY TRACKING
// ────────────────────────────────────────────────────────────────

const GIT_DIR = path.join(CONFIG.projectDir, ".git");
const isGitRepo = fs.existsSync(GIT_DIR) && CLI.git !== false;

let lastCommitHash = null;

function git(args) {
    return new Promise(resolve => {
        execFile("git", args, { cwd: CONFIG.projectDir, timeout: 5000 }, (err, stdout) => {
            resolve(err ? null : stdout.trim());
        });
    });
}

async function reportGitState(isInitial) {
    const hash = await git(["rev-parse", "HEAD"]);
    if (hash === null) return; // not a repo, or git isn't installed

    const branch = await git(["rev-parse", "--abbrev-ref", "HEAD"]);
    const subject = await git(["log", "-1", "--pretty=%s"]);
    const author = await git(["log", "-1", "--pretty=%an"]);
    const relDate = await git(["log", "-1", "--pretty=%ar"]);
    const dirty = await git(["status", "--porcelain"]);

    if (isInitial) {
        log("GIT", `Repo on branch "${branch}"`);
        log("GIT", `Last commit ${hash.slice(0, 7)} by ${author} (${relDate}): ${subject}`);
        if (dirty) log("GIT", "Working tree has uncommitted changes");
    } else if (hash !== lastCommitHash) {
        log("GIT", `New commit on "${branch}": ${hash.slice(0, 7)} by ${author} — ${subject}`);
    }
    lastCommitHash = hash;
}

function watchGit() {
    if (!isGitRepo) {
        log("INFO", "No .git directory found (or --no-git set) — git tracking disabled");
        return;
    }

    reportGitState(true);

    // HEAD/refs change on commit, checkout, merge, rebase, etc.
    try {
        const gitWatcher = fs.watch(GIT_DIR, { persistent: true }, (eventType, filename) => {
            if (!filename) return;
            if (filename === "HEAD" || filename.startsWith(path.join("refs", "heads"))) {
                reportGitState(false);
            }
        });
        activeWatchers.push(gitWatcher);
    } catch {
        /* fall back to polling below if .git can't be watched directly */
    }

    // Safety-net poll in case an editor/tool changes refs in a way
    // fs.watch misses on some filesystems.
    setInterval(() => reportGitState(false), CONFIG.gitPollMs);
}

// ────────────────────────────────────────────────────────────────
// 9. STARTUP / SHUTDOWN
// ────────────────────────────────────────────────────────────────

function printBanner() {
    const line = "═".repeat(58);
    console.log(COLORS.bold + line);
    console.log("             PROJECT MONITOR — production build");
    console.log(line + COLORS.reset);
    console.log(`Project     : ${CONFIG.projectDir}`);
    console.log(`Node        : ${process.version}`);
    console.log(`Platform    : ${os.platform()} ${os.release()}`);
    console.log(`Started     : ${timestamp()}`);
    console.log(`Log file    : ${CONFIG.logFile}`);
    console.log(`Hashing     : ${CONFIG.hashEnabled ? "on" : "off"}`);
    console.log(`Git track   : ${CLI.git === false ? "off" : "on"}`);
    console.log(COLORS.bold + line + COLORS.reset + "\n");
}

function shutdown(signal) {
    log("INFO", `Received ${signal} — shutting down`);
    for (const w of activeWatchers) {
        try { w.close(); } catch { /* already closed */ }
    }
    logStream.end(() => process.exit(0));
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("uncaughtException", err => {
    log("ERROR", `Uncaught exception: ${err.stack || err.message}`);
});

function main() {
    console.clear();
    printBanner();
    log("INFO", `Baseline snapshot: ${snapshot.size} file(s) indexed`);
    setupWatchers();
    watchGit();
    log("INFO", "Monitoring started — watching for file, rename and git activity");
}

main();