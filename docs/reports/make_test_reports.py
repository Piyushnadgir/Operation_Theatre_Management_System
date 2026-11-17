"""Build docs/Unit_Test_Report.md, docs/Code_Coverage_Report.md and docs/Branch_Coverage_Report.md
from the raw files of one pytest run (docs/reports/unit_tests.xml and coverage.xml).

Every figure is copied from those files: rates are coverage.xml's own line-rate / branch-rate
attributes (shown x100), counts are counted from its <line> elements. Nothing is typed by hand
except the short "notes" paragraphs, which describe what the uncovered code is.

Run from the repository root with the same environment as the test run:
    python docs/reports/make_test_reports.py
"""
import ast
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "docs" / "reports"
JUNIT = ET.parse(REPORTS / "unit_tests.xml").getroot()
COV = ET.parse(REPORTS / "coverage.xml").getroot()
SUITE = JUNIT if JUNIT.tag == "testsuite" else JUNIT.find("testsuite")

# Test case IDs from the Test Plan, section 13 (docs/OTMS_Test_Plan.docx).
TEST_PLAN_IDS = [
    "TC-Sched-01", "TC-Sched-02", "TC-Sched-03", "TC-Sched-04", "TC-Sched-05",
    "TC-Emg-01", "TC-Emg-02", "TC-Emg-03", "TC-Emg-04", "TC-Emg-05",
    "TC-Staff-01", "TC-Staff-02", "TC-Staff-03", "TC-Auth-01", "TC-Auth-02",
    "TC-Eq-01", "TC-Eq-02", "TC-Eq-03", "TC-Rpt-01", "TC-Rpt-02", "TC-Rpt-03",
    "TC-Perf-01", "TC-Rel-01", "TC-UX-01", "TC-OPS-01",
    "TC-Sec-01", "TC-Sec-02", "TC-Sec-03", "TC-Sec-04", "TC-Sec-05", "TC-Sec-06",
]
CANON = {i.lower(): i for i in TEST_PLAN_IDS}
ID_PATTERN = re.compile(r"tc[-_ ]?(sched|emg|staff|auth|eq|rpt|perf|rel|ux|ops|sec)[-_ ]?(\d+)", re.I)
EXIT_CRITERION = ("100% of planned test cases executed, 0 critical defects open, all acceptance criteria "
                  "satisfied and CI green on main.")


def ids_in(text):
    found = []
    for m in ID_PATTERN.finditer(text or ""):
        key = f"tc-{m[1].lower()}-{int(m[2]):02d}"
        if key in CANON and CANON[key] not in found:
            found.append(CANON[key])
    return found


def pct(rate):
    """coverage.xml rate attribute -> percent string (a decimal shift, no rounding of our own)."""
    return f"{float(rate) * 100:.2f}%"


def ranges(numbers):
    out, nums = [], sorted(numbers)
    for n in nums:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in out)


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- header
RUN_AT = SUITE.get("timestamp", "")[:16].replace("T", " ")
COMMIT, BRANCH = git("rev-parse", "--short", "HEAD"), git("branch", "--show-current")
ENV = (f"Python {platform.python_version()}, pytest {version('pytest')}, pytest-cov {version('pytest-cov')}, "
       f"coverage.py {COV.get('version')}, {platform.system()} {platform.release()} (conda env `otms`)")


def header(title, measured):
    return [
        f"# {title}: OTMS v1.0", "",
        "| Item | Value |", "|---|---|",
        "| Project | Operation Theatre Management System (OTMS) |",
        "| Team | Team 01: Pulkit Handa, Piyush Nadgir, Poorvi Rangaswamy, Riyana K |",
        f"| Date of run | {RUN_AT} IST (timestamp in `unit_tests.xml`) |",
        f"| Commit | `{COMMIT}` on branch `{BRANCH}` |",
        f"| Environment | {ENV} |",
        f"| Command | `{measured}` |", "",
        f"**All numbers in this report come from the single test run on commit `{COMMIT}` shown above.** "
        "They were copied by `docs/reports/make_test_reports.py` from `docs/reports/unit_tests.xml` and "
        "`docs/reports/coverage.xml`; none were typed or rounded by hand.", "",
    ]


COMMAND = ("pytest --junitxml=docs/reports/unit_tests.xml --cov=app --cov-branch --cov-report=term-missing "
           "--cov-report=xml:docs/reports/coverage.xml --cov-report=html:docs/reports/htmlcov")

THRESHOLD_NOTE = (f"**Threshold:** the Test Plan sets no coverage threshold. Its exit criterion (section 5) is: "
                  f"\"{EXIT_CRITERION}\" No coverage figure is therefore claimed as meeting or missing a target.")

# ================================================================ Unit Test Report
cases = []
for tc in SUITE.iter("testcase"):
    outcome, detail = "passed", ""
    for tag in ("failure", "error", "skipped"):
        node = tc.find(tag)
        if node is not None:
            outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
            detail = (node.get("message") or "") + "\n" + (node.text or "")
    cases.append({"file": tc.get("classname").replace(".", "/") + ".py", "name": tc.get("name"),
                  "time": float(tc.get("time") or 0), "outcome": outcome, "detail": detail})

# IDs per test: from the test's own name or docstring only. Module docstrings are listed per file.
own_ids, module_ids = {}, {}
for path in sorted((ROOT / "tests").glob("test_*.py")):
    tree = ast.parse(path.read_text())
    rel = f"tests/{path.name}"
    module_ids[rel] = ids_in(ast.get_docstring(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            own_ids[(rel, node.name)] = ids_in(node.name + " " + (ast.get_docstring(node) or ""))
for c in cases:
    c["ids"] = own_ids.get((c["file"], c["name"].split("[")[0]), [])

count = Counter(c["outcome"] for c in cases)
by_file = defaultdict(list)
for c in cases:
    by_file[c["file"]].append(c)

u = header("Unit Test Report", COMMAND)
u += ["## Scope", "",
      f"The automated test suite in `tests/` ({len(by_file)} test files): unit and integration tests of the services, "
      "the REST API (FastAPI test client on a temporary SQLite database), the security rules, the record-retention "
      "rules, and the static checks of the web UI. Browser-driven and manual system tests are not part of this suite; "
      "they are reported in the System Validation Report.", "",
      "## Summary", "",
      "| Total | Passed | Failed | Errors | Skipped | Duration |", "|---|---|---|---|---|---|",
      f"| {SUITE.get('tests')} | {count['passed']} | {SUITE.get('failures')} | {SUITE.get('errors')} | "
      f"{SUITE.get('skipped')} | {SUITE.get('time')} s |", "",
      "## Results per test file", "",
      "| Test file | Tests | Passed | Failed | Errors | Skipped | Time (s) | Test Plan IDs named in the file's docstring |",
      "|---|---|---|---|---|---|---|---|"]
for f, cs in sorted(by_file.items()):
    k = Counter(c["outcome"] for c in cs)
    u.append(f"| `{f}` | {len(cs)} | {k['passed']} | {k['failed']} | {k['error']} | {k['skipped']} | "
             f"{sum(c['time'] for c in cs):.3f} | {', '.join(module_ids.get(f, [])) or '—'} |")
u += ["", "Time per file is the sum of the per-test times in `unit_tests.xml`; it excludes collection and "
      "start-up, so it is less than the total duration.", "",
      "## Failures", ""]
bad = [c for c in cases if c["outcome"] in ("failed", "error")]
if not bad:
    u += ["None. No test failed or raised an error in this run.", ""]
for c in bad:
    lines = [l for l in c["detail"].strip().splitlines() if l.strip()]
    u += [f"### `{c['file']}::{c['name']}` ({c['outcome']})", "", "```", *lines[-15:], "```", ""]

u += ["## Traceability: Test Plan IDs to automated tests", "",
      "A test counts as covering an ID only when the ID is in **the test's own name or docstring**. Files whose "
      "module docstring names an ID for the file as a whole are listed separately, because that does not say "
      "which of their tests covers it.", "",
      "| Test Plan ID | Tests naming it | Tests (file::test) | Files naming it in the module docstring |",
      "|---|---|---|---|"]
none_at_all, file_only = [], []
for tid in TEST_PLAN_IDS:
    named = sorted({f"{c['file'].removeprefix('tests/')}::{c['name'].split('[')[0]}" for c in cases if tid in c["ids"]})
    n_named = sum(1 for c in cases if tid in c["ids"])
    files = [f.removeprefix("tests/") for f, ids in module_ids.items() if tid in ids]
    if not named and not files:
        none_at_all.append(tid)
    elif not named:
        file_only.append(tid)
    shown = "<br>".join(f"`{n}`" for n in named[:6]) + (f"<br>… and {len(named) - 6} more" if len(named) > 6 else "")
    u.append(f"| {tid} | {n_named} | {shown or '—'} | {', '.join(f'`{f}`' for f in files) or '—'} |")
u += ["", '"Tests naming it" counts parametrised tests once per parameter set (as pytest does); the "Tests (file::test)" column lists each test function once.', "",
      f"**No automated test names these Test Plan IDs, in a test or a module docstring:** {', '.join(none_at_all) or 'none'}.",
      "",
      f"**Named only in a module docstring, not by any single test:** {', '.join(file_only) or 'none'}.", "",
      "Note: `tests/test_surgery_service.py` and `tests/test_conflict_detection.py` test scheduling and conflict "
      "detection but carry no Test Plan ID, so they are not mapped above.", "",
      "## Conclusion", "",
      f"On commit `{COMMIT}`: {SUITE.get('tests')} tests ran; {count['passed']} passed, {SUITE.get('failures')} failed, "
      f"{SUITE.get('errors')} errors, {SUITE.get('skipped')} skipped, in {SUITE.get('time')} s. "
      f"{sum(1 for t in TEST_PLAN_IDS if t not in none_at_all and t not in file_only)} of {len(TEST_PLAN_IDS)} Test Plan IDs "
      f"are named by at least one test, {len(file_only)} only in a module docstring, and {len(none_at_all)} nowhere.", "",
      "## Appendix: every test and its result", "",
      "| # | Test file | Test | Test Plan ID | Result | Time (s) |", "|---|---|---|---|---|---|"]
for i, c in enumerate(cases, 1):
    name = c["name"].replace("|", "\\|")
    code = f"`` {name} ``" if "`" in name else f"`{name}`"   # a name holding backticks needs a double-backtick span
    u.append(f"| {i} | `{c['file'].removeprefix('tests/')}` | {code} | {', '.join(c['ids']) or '—'} | "
             f"{c['outcome']} | {c['time']:.3f} |")
(ROOT / "docs" / "Unit_Test_Report.md").write_text("\n".join(u) + "\n")

# ================================================================ coverage data
files = []
for cls in COV.iter("class"):
    path = "app/" + cls.get("filename")
    src = (ROOT / path).read_text().splitlines()
    lines = list(cls.iter("line"))
    missed = [int(l.get("number")) for l in lines if l.get("hits") == "0"]
    br_total = br_cov = partial = 0
    missed_branches = []
    for l in lines:
        cc = l.get("condition-coverage")
        if not cc:
            continue
        got, of = map(int, re.search(r"\((\d+)/(\d+)\)", cc).groups())
        br_total += of; br_cov += got
        if 0 < got < of:
            partial += 1
        if l.get("missing-branches"):
            n = int(l.get("number"))
            missed_branches.append((n, cc, l.get("missing-branches"), src[n - 1].strip(), l.get("hits") != "0"))
    files.append({"path": path, "stmts": len(lines), "miss": len(missed), "missed": missed,
                  "line_rate": cls.get("line-rate"), "branch_rate": cls.get("branch-rate"),
                  "br_total": br_total, "br_cov": br_cov, "partial": partial, "missed_branches": missed_branches})

LV, LC = int(COV.get("lines-valid")), int(COV.get("lines-covered"))
BV, BC = int(COV.get("branches-valid")), int(COV.get("branches-covered"))
assert LV == sum(f["stmts"] for f in files) and BV == sum(f["br_total"] for f in files), "per-file counts do not add up"
TERMINAL_TOTAL = next((l for l in (REPORTS / "pytest_output.txt").read_text().splitlines() if l.startswith("TOTAL")), "")

# Short notes written after reading the uncovered lines (descriptions only; no figures).
LINE_NOTES = {
    "app/utils/seed.py": "The command-line script that creates the first user (`python -m app.utils.seed`). It is run by hand when setting up; no test runs it.",
    "app/core/database.py": "`get_db()`, the per-request database session. The tests replace it with a temporary test database (dependency override), so the real function never runs.",
    "app/api/v1/surgeries.py": "The whole body of the reschedule endpoint `PUT /surgeries/{id}` (lines 49–67) and the 404 for cancelling a surgery that does not exist. Rescheduling is tested only at service level, never through the API.",
    "app/api/v1/emergencies.py": "Error paths of the helpers that read the caller's user id from the token: a token without a subject, a non-numeric subject, and the refusals when no user id can be found.",
    "app/services/conflict_detection.py": "The messages for doctor, nurse and equipment clashes in `detect_all_conflicts`, nurse double-booking itself, and the \"ignore this surgery\" filter used when rescheduling with staff. Through this function the suite reaches only the theatre-clash and the retired/under-maintenance equipment messages.",
    "app/services/surgery_service.py": "Reschedule of a surgery that does not exist, replacing the doctors and nurses while rescheduling, cancelling a surgery that does not exist, and listing surgeries filtered by theatre or with the date given as text.",
    "app/core/security.py": "Creating a token with a custom expiry time. The only caller in `app/` (login) uses the default expiry.",
    "app/main.py": "Adding the HTTPS middleware when `ENFORCE_HTTPS=true`; the tests import the app with the default (false).",
    "app/schemas/staff.py": "The name validator's branches for a missing value and for a name that is blank after trimming.",
    "app/services/emergency_service.py": "An emergency that reserves equipment, the fallback that notifies the person who logged the emergency when nobody else is affected, and an empty staff list.",
}
BRANCH_NOTES = {
    "app/api/v1/surgeries.py": "Both outcomes of the reschedule endpoint's result check (conflict or not found, and success) are untested, because the endpoint is never called; the cancel endpoint's not-found branch is also untested.",
    "app/services/conflict_detection.py": "The `True` side of the doctor, nurse and equipment clash loops in `detect_all_conflicts` (a clash found), the nurse clash check, and the `exclude_surgery_id` filter for staff. Only the theatre-clash check and the equipment-status loop are driven through both sides here.",
    "app/services/surgery_service.py": "Not-found branches in reschedule and cancel; reschedule with a new staff list; list without a date and with a theatre filter or a text date.",
    "app/api/v1/emergencies.py": "The `None` sides of the user-id checks (token without a usable user id).",
    "app/services/emergency_service.py": "The search loop for the next free slot never meets a busy period that ends at or before the candidate start; an emergency with equipment; the notify-the-logger fallback; an empty staff list.",
    "app/schemas/staff.py": "The validator's `None` and blank-name sides.",
    "app/core/security.py": "The custom-expiry side of `if expires_delta`.",
    "app/main.py": "The `ENFORCE_HTTPS=true` side of the start-up check.",
    "app/utils/seed.py": "Both sides of the password-length check and of `if __name__ == \"__main__\"`, because the script never runs in the tests.",
}

# ================================================================ Code Coverage Report
c = header("Code Coverage Report", COMMAND)
c += ["## How it was measured", "",
      "pytest-cov with `--cov=app` measured which lines of the application package `app/` ran during the test "
      "suite. Tests, the web UI's static files (HTML, CSS, JavaScript) and third-party code are not measured. "
      "Line coverage = covered statements / statements, taken from `coverage.xml`.", "",
      "## Total line coverage", "",
      "| Statements | Covered | Missed | Line coverage |", "|---|---|---|---|",
      f"| {LV} | {LC} | {LV - LC} | **{pct(COV.get('line-rate'))}** |", "",
      f"For reference, the terminal report's TOTAL row is `{' '.join(TERMINAL_TOTAL.split())}`. Its 95% \"Cover\" "
      "combines lines and branches, so it differs from the line-only figure above.", "",
      THRESHOLD_NOTE, "",
      "## Per file (sorted by line coverage, lowest first)", "",
      "| File | Statements | Missed | Line coverage |", "|---|---|---|---|"]
for f in sorted(files, key=lambda f: (float(f["line_rate"]), f["path"])):
    c.append(f"| `{f['path']}` | {f['stmts']} | {f['miss']} | {pct(f['line_rate'])} |")
under = [f for f in sorted(files, key=lambda f: (float(f["line_rate"]), f["path"])) if f["miss"]]
c += ["", f"{len(files) - len(under)} of {len(files)} files are at 100%.", "",
      "## Uncovered lines (files under 100%)", "",
      "| File | Line coverage | Uncovered lines |", "|---|---|---|"]
for f in under:
    c.append(f"| `{f['path']}` | {pct(f['line_rate'])} | {ranges(f['missed'])} |")
c += ["", "## Main gaps", "",
      "Written after reading the uncovered lines listed above, lowest coverage first.", ""]
for f in under:
    c.append(f"- **`{f['path']}` ({pct(f['line_rate'])}):** {LINE_NOTES.get(f['path'], '(no note)')}")
c += ["", "The HTML report with every file's source highlighted is in `docs/reports/htmlcov/index.html`.", ""]
(ROOT / "docs" / "Code_Coverage_Report.md").write_text("\n".join(c) + "\n")

# ================================================================ Branch Coverage Report
b = header("Branch Coverage Report", COMMAND)
b += ["## How it was measured", "",
      "pytest-cov with `--cov=app --cov-branch` recorded, for every decision point in `app/` (an `if`, a loop, a "
      "`while`, and so on), which of its possible next lines actually ran. Each possible next line is one branch. "
      "Branch coverage = branches taken / branches, from `coverage.xml`. A **partial** line ran, but not all of "
      "its branches; a missed branch on a line that never ran is counted as missed but not as partial.", "",
      "## Total branch coverage", "",
      "| Branches | Taken | Missed | Partial lines | Branch coverage |", "|---|---|---|---|---|",
      f"| {BV} | {BC} | {BV - BC} | {sum(f['partial'] for f in files)} | **{pct(COV.get('branch-rate'))}** |", "",
      THRESHOLD_NOTE, "",
      "## Per file (files with branches, lowest branch coverage first)", "",
      "| File | Branches | Taken | Missed | Partial lines | Branch coverage |", "|---|---|---|---|---|---|"]
with_branches = sorted([f for f in files if f["br_total"]], key=lambda f: (float(f["branch_rate"]), f["path"]))
for f in with_branches:
    b.append(f"| `{f['path']}` | {f['br_total']} | {f['br_cov']} | {f['br_total'] - f['br_cov']} | {f['partial']} | "
             f"{pct(f['branch_rate'])} |")
b += ["", f"{len(files) - len(with_branches)} files have no branches and are not listed. "
      f"{sum(1 for f in with_branches if f['br_cov'] == f['br_total'])} of {len(with_branches)} files with branches "
      "are at 100%.", "",
      "## Missed branches", "",
      "From `coverage.xml`: the line holding the decision, how many of its branches were taken, and the line(s) "
      "it can jump to that never ran (`exit` = leaving the function or module). The condition is the source line.", "",
      "| File | Line | Taken | Never-taken jump to | Line ran? | Condition (source line) |", "|---|---|---|---|---|---|"]
for f in with_branches:
    for n, cc, to, srcline, ran in f["missed_branches"]:
        b.append(f"| `{f['path']}` | {n} | <span class='nowrap'>{cc}</span> | {to} | {'yes' if ran else 'no'} | `{srcline.replace('|', '¦')}` |")
b += ["", "## Main untested branches", "", "Written after reading the code at the lines above.", ""]
for f in with_branches:
    if f["missed_branches"]:
        b.append(f"- **`{f['path']}` ({pct(f['branch_rate'])}):** {BRANCH_NOTES.get(f['path'], '(no note)')}")
b.append("")
(ROOT / "docs" / "Branch_Coverage_Report.md").write_text("\n".join(b) + "\n")
print("written; tests", SUITE.get("tests"), "line", pct(COV.get("line-rate")), "branch", pct(COV.get("branch-rate")))
