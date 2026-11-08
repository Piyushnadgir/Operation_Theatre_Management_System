#!/usr/bin/env bash
# Creates a clean `main` branch for the OTMS repo (run once, by Piyush).
# Run from INSIDE your clone:  bash create_main.sh
set -e

git fetch --all --prune

# 1. Start from the common ancestor of the feature branches (core models + DB setup).
BASE=$(git merge-base origin/feature/surgery-scheduling origin/feature/conflict-detection)
git checkout -b main "$BASE"

# 2. Put the three documents in docs/
mkdir -p docs
git mv OTMS_SAD.docx OTMS_SRS.docx OTMS_Test_Plan.docx docs/

# 3. .gitignore (identical to the one on the equipment branch, so it merges without conflict)
git show origin/feature/equipment-tracking:.gitignore > .gitignore

# 4. CI: runs the tests + coverage on every push and PR to main
mkdir -p .github/workflows
cat > .github/workflows/ci.yml <<'YML'
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt pytest-cov
      - name: Run tests with coverage
        run: |
          mkdir -p reports
          pytest --junitxml=reports/unit_tests.xml \
            --cov=app --cov-branch \
            --cov-report=term-missing --cov-report=xml:reports/coverage.xml --cov-report=html:reports/htmlcov
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: test-and-coverage-reports
          path: reports/
YML

# 5. PR template
cat > .github/pull_request_template.md <<'MD'
## What does this PR do?

## Jira ticket
OTMS-

## Checklist
- [ ] Developed on a separate branch (not main)
- [ ] Added test case(s) for this feature
- [ ] Ran `pytest` locally and all tests pass
- [ ] Only touched my own module's files (or told the owner)
- [ ] Pulled the latest main before pushing
MD

git add -A
git commit -m "chore: create main with docs folder, CI with coverage and PR template"
git push -u origin main

echo
echo "Done. Next: GitHub -> Settings -> Branches -> set 'main' as the default branch."
