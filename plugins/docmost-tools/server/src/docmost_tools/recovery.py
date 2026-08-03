"""Checkout-independent recovery commands exposed at public error boundaries."""

AUTH_LOGIN_COMMAND = (
    'CODEX_TOOLBOX_ROOT="${CODEX_TOOLBOX_ROOT:-$HOME/codes/codex-toolbox}" '
    '"$CODEX_TOOLBOX_ROOT/scripts/setup-docmost-tools.sh" --login'
)
AUTH_REQUIRED_SENTENCE = (
    f"Authentication required. Close the active task, run `{AUTH_LOGIN_COMMAND}`, "
    "then start a fresh task or reconnect Docmost."
)
