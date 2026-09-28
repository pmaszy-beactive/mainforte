#!/usr/bin/env bash
#
# Sets up the git hooks for this project.
# Run once after cloning: bash scripts/src/setup-hooks.sh
#
set -e

echo "Configuring git to use .githooks directory..."
git config core.hooksPath .githooks

echo "Git hooks configured successfully."
echo ""
echo "Available hooks:"
echo "  pre-commit: Auto-increments build number in version.ini"
echo ""
echo "To manually bump version components, edit version.ini directly:"
echo "  major= (breaking changes)"
echo "  minor= (new features)"
echo "  patch= (bug fixes)"
echo "  build= (auto-incremented on every commit)"
