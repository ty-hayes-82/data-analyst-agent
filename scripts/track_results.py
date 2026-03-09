"""Track test results and code quality metrics over time."""
import json
import subprocess
import datetime
import re
from pathlib import Path

RESULTS_FILE = Path("/data/data-analyst-agent/data/validation/iteration_results.jsonl")
SCOREBOARD_FILE = Path("/data/data-analyst-agent/data/validation/SCOREBOARD.md")
CWD = "/data/data-analyst-agent"
PYTHON = "/data/data-analyst-agent/.venv/bin/python"

def run_cmd(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=CWD)
    return (r.stdout + r.stderr).strip()

commit = run_cmd("git log --oneline -1")

# Run full test suite
test_output = run_cmd(f"{PYTHON} -m pytest --tb=no -q 2>&1")
passed = failed = errors = skipped = 0
for line in test_output.split("\n"):
    m = re.search(r"(\d+) passed", line)
    if m: passed = int(m.group(1))
    m = re.search(r"(\d+) failed", line)
    if m: failed = int(m.group(1))
    m = re.search(r"(\d+) error", line)
    if m: errors = int(m.group(1))
    m = re.search(r"(\d+) skipped", line)
    if m: skipped = int(m.group(1))

# Run e2e trade data tests
e2e_passed = e2e_failed = 0
e2e_path = Path(CWD) / "tests/e2e/test_trade_data_e2e.py"
if e2e_path.exists():
    e2e_output = run_cmd(f"{PYTHON} -m pytest tests/e2e/test_trade_data_e2e.py --tb=no -q 2>&1")
    for line in e2e_output.split("\n"):
        m = re.search(r"(\d+) passed", line)
        if m: e2e_passed = int(m.group(1))
        m = re.search(r"(\d+) failed", line)
        if m: e2e_failed = int(m.group(1))

# Code metrics
file_lines = run_cmd("find data_analyst_agent -name '*.py' -exec wc -l {} + | sort -rn")
total_lines = 0
largest_name = "?"
largest_lines = 0
files_over_200 = 0
file_count = 0
for line in file_lines.split("\n"):
    parts = line.strip().split()
    if len(parts) >= 2:
        n = int(parts[0])
        f = parts[-1]
        if f == "total":
            total_lines = n
        else:
            file_count += 1
            if n > largest_lines:
                largest_lines = n
                largest_name = f.replace("data_analyst_agent/", "")
            if n > 200:
                files_over_200 += 1

entry = {
    "timestamp": datetime.datetime.now().isoformat(),
    "commit": commit[:40],
    "tests_passed": passed,
    "tests_failed": failed,
    "tests_errors": errors,
    "e2e_passed": e2e_passed,
    "e2e_failed": e2e_failed,
    "total_lines": total_lines,
    "file_count": file_count,
    "largest_file": f"{largest_name} ({largest_lines}L)",
    "files_over_200": files_over_200,
}

with open(RESULTS_FILE, "a") as f:
    f.write(json.dumps(entry) + "\n")

results = []
with open(RESULTS_FILE) as f:
    for line in f:
        if line.strip():
            try: results.append(json.loads(line))
            except: pass

sb = "# Iteration Scoreboard\n\n"
sb += f"**Last updated:** {entry['timestamp'][:19]}\n\n"
sb += "## Current State\n"
sb += f"- **Unit Tests:** {passed} passed, {failed} failed, {errors} errors\n"
sb += f"- **E2E Trade Data:** {e2e_passed} passed, {e2e_failed} failed\n"
sb += f"- **Codebase:** {file_count} files, {total_lines:,} lines, **{files_over_200} files >200L**\n"
sb += f"- **Largest:** {entry['largest_file']}\n"
sb += f"- **Commit:** `{commit[:50]}`\n\n"

sb += "## Progress Over Time\n\n"
sb += "| # | Time | Commit | Pass | Fail | Err | E2E | >200L | Largest |\n"
sb += "|---|------|--------|------|------|-----|-----|-------|----------|\n"
for i, r in enumerate(results):
    ts = r["timestamp"][11:16]
    cm = r["commit"][:7]
    e2e = f"{r['e2e_passed']}/{r['e2e_passed']+r['e2e_failed']}"
    sb += f"| {i+1} | {ts} | `{cm}` | {r['tests_passed']} | {r['tests_failed']} | {r['tests_errors']} | {e2e} | {r['files_over_200']} | {r['largest_file'][:25]} |\n"

if len(results) >= 2:
    f0, last = results[0], results[-1]
    sb += f"\n## Cumulative Improvement\n"
    sb += f"- Tests: {f0['tests_passed']} → **{last['tests_passed']}** (+{last['tests_passed']-f0['tests_passed']})\n"
    sb += f"- Failures: {f0['tests_failed']} → **{last['tests_failed']}**\n"
    sb += f"- Files >200L: {f0['files_over_200']} → **{last['files_over_200']}** ({last['files_over_200']-f0['files_over_200']:+d})\n"
    sb += f"- Iterations: {len(results)}\n"

with open(SCOREBOARD_FILE, "w") as f:
    f.write(sb)

print(sb)
