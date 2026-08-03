"""Checkout-independent recovery commands exposed at public error boundaries."""

AUTH_LOGIN_COMMAND = (
    '"${CODEX_HOME:-$HOME/.codex}/runtime/docmost-tools/bin/docmost-auth" login'
)
AUTH_REQUIRED_SENTENCE = f"Authentication required. Run `{AUTH_LOGIN_COMMAND}`."
