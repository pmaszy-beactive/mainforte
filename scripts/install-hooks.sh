#!/bin/sh
# Installs this repo's git hooks. Hooks live in .git/, which never travels
# with a clone — run this once after cloning (also wired as `postinstall`
# below so a fresh `pnpm install` / `npm install` in frontend/ does it too).
set -e

hooks_dir="$(git rev-parse --git-common-dir)/hooks"
hook="$hooks_dir/pre-commit"

mkdir -p "$hooks_dir"

cat > "$hook" <<'EOF'
#!/bin/sh
bash "$(git rev-parse --show-toplevel)/scripts/bump-version.sh"
EOF

chmod +x "$hook"
echo "Installed pre-commit hook -> $hook"
