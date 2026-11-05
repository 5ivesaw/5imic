#!/usr/bin/env bash
# 5imic source setup and optional GitHub publication.
# Usage:
#   bash install.sh            # install into .venv and start the GUI
#   bash install.sh tui        # install and run the terminal interface
#   bash install.sh --publish  # commit & push project source to 5ivesaw/5imic
#   bash install.sh --all      # publish, then install and run locally
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

REPO_URL="https://github.com/5ivesaw/5imic.git"

fail() {
  printf '5imic setup: %s\n' "$*" >&2
  exit 1
}

require_project() {
  [[ -f pyproject.toml && -f README.md && -d src/fiveimic ]] ||
    fail "Put install.sh in the extracted 5imic project directory first."
}

install_local() {
  command -v python3 >/dev/null 2>&1 ||
    fail "Python 3.10+ is required. Install Python, then try again."
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' ||
    fail "Python 3.10+ is required."

  if [[ ! -x .venv/bin/python ]]; then
    printf 'Creating private Python environment...\n'
    python3 -m venv .venv ||
      fail "Could not create .venv. On Debian/Ubuntu, install python3-venv."
  fi

  printf 'Installing/updating 5imic dependencies...\n'
  .venv/bin/python -m pip install -e .

  printf '\nStarting 5imic. First model download may take a while.\n'
  exec .venv/bin/python -m fiveimic "$@"
}

publish_github() {
  command -v git >/dev/null 2>&1 ||
    fail "Git is required to publish. Install git and try again."
  [[ -f .github/workflows/release.yml ]] ||
    fail "Missing .github/workflows/release.yml; unpack the complete source ZIP."

  if [[ ! -e .git ]]; then
    printf 'Initializing this project as a Git repository on main...\n'
    git init -b main
  fi

  branch="$(git branch --show-current)"
  [[ "$branch" == "main" ]] ||
    fail "Current Git branch is '$branch', not main. Switch branches deliberately and retry."

  if git remote get-url origin >/dev/null 2>&1; then
    existing="$(git remote get-url origin)"
    case "$existing" in
      "$REPO_URL"|"git@github.com:5ivesaw/5imic.git") ;;
      *) fail "Origin points to '$existing'. Refusing to change or push to another repository." ;;
    esac
  else
    git remote add origin "$REPO_URL"
  fi

  # Stage only project files, not downloaded speech, private models, or .venv.
  git add -- README.md PROJECT.md BUILD_STATUS.md LICENSE pyproject.toml \
    run_5imic.py install.sh launch.sh launch.cmd .gitignore \
    .github/workflows/release.yml assets src tests

  if ! git diff --cached --quiet; then
    git config user.name >/dev/null ||
      fail "Set your Git author name: git config --global user.name 'Your Name'"
    git config user.email >/dev/null ||
      fail "Set your Git author email: git config --global user.email 'you@example.com'"
    git commit -m "Build 5imic Borrowed Voice Studio"
  else
    printf 'No new project changes to commit.\n'
  fi

  printf '\nPushing main to %s (never force-pushing)...\n' "$REPO_URL"
  git push -u origin main ||
    fail "Push declined. Authenticate with GitHub or reconcile remote changes first; nothing was force-overwritten."

  printf '\nPublished! GitHub Actions should now test and build both platforms.\n'
  printf 'Watch: https://github.com/5ivesaw/5imic/actions\n'
}

require_project

case "${1:-}" in
  --publish)
    [[ "$#" -eq 1 ]] || fail "Use only: bash install.sh --publish"
    publish_github
    ;;
  --all)
    shift
    publish_github
    install_local "$@"
    ;;
  *)
    install_local "$@"
    ;;
esac
