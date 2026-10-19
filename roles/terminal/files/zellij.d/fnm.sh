test -n "$VSCODE_INJECTION" && return
export FNM_DIR="${HOME}/.fnm"
command -v fnm >/dev/null 2>&1 && eval "$(fnm env --shell bash)"
