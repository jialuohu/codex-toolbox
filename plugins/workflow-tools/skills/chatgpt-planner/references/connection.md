# Bind and verify a planning conversation

Setup changes local state and runs harmless tests. Perform it in execution mode
on a user setup request, not as an automatic response to a missing binding.

1. Have the user create/select a dedicated ChatGPT conversation, select
   **GPT-6 Pro**, send an initial message, and provide its private conversation
   URL or ID. A shared conversation URL is not a writable destination. Do not
   create a ChatGPT Work task as a substitute or reuse a chat based on its title.
2. Verify the exact ID through native `list_threads`/`read_thread`. Confirm
   `thread.kind: chatgpt`. Explain that the native reader omits model metadata;
   model identity requires user confirmation from the UI, not the model saying
   what it is. An available Pro subscription alone does not verify this chat.
3. Resolve the helper relative to the skill and bind:

   ```text
   python3 scripts/planner_state.py bind --project <project-root> --conversation <conversation-url-or-id> --mode default
   ```

   Bind accepts `https://chatgpt.com/c/<id>` or a UUID and starts unverified.
   One conversation belongs to one project. Use the same canonical project root
   for a repository and its worktrees; supply the actual worktree evidence in
   each planning packet. Never put IDs or private state in the plugin source.
4. Read [native transport](transport.md) for the send/observe protocol. Use the
   following synthetic packet on stdin for a deliberately requested setup probe:

   ```json
   {"objective_key":"setup-initial","objective":"Verify native planning transport","requirements":"Return the requested markers and READY","context":"Synthetic setup check; no repository content","snapshot":"setup"}
   ```

   ```text
   python3 scripts/planner_state.py plan --project <project-root> --task-id <current-task-id> --mode default --setup-probe
   python3 scripts/planner_state.py observe --project <project-root> --request-id <request-id> --mode default --setup-probe
   ```

   `--setup-probe` emits a fixed harmless prompt, not the supplied task context.
   It is exclusively for explicit connection testing; never use it to bypass the
   Plan-mode gate. Send once through the native tool and validate the reply.
5. Ask the user to confirm Pro remains selected and restart the desktop app at
   a convenient point. Do not terminate the app or other active tasks. After the
   user confirms the restart, repeat the probe with `objective_key` changed to
   `setup-after-restart`. Keep both request IDs. If interrupted, recover through
   `status` and native reads, not a second send of the same request.
6. Only after both completed exchanges, user-confirmed model selection, and
   user-confirmed app restart, enable the binding:

   ```text
   python3 scripts/planner_state.py verify --project <project-root> --mode default --first-probe <first-id> --restart-probe <second-id> --model-confirmed --restart-confirmed
   ```

   These flags record actual user confirmation; they are not evidence created
   by the helper. If any check cannot run, leave the binding unverified and say
   which check remains. Do not substitute another model or API route.

`status` reports the verification basis and time. A verified binding means the
transport probes passed and the user confirmed the setup; it does not mean the
helper can attest to every response's model. Recheck if the user changes the
conversation's model or if an app update changes transport behavior.

To disable this workflow, remove its automatic routing during an authorized
configuration change or explicitly rebind to a new, unverified conversation.
Do not delete conversations or local history as part of setup or rollback.

## Private state location

The default is `${CODEX_HOME:-$HOME/.codex}/state/chatgpt-planner`; an unset or
empty `CODEX_HOME` uses `~/.codex`. `STATE_INSIDE_GIT` or `STATE_INSIDE_PROJECT`
means this directory would fall inside a checkout, including a Git-managed home
directory. Choose a private directory outside every Git checkout and pass
`--state-dir <absolute-private-directory>` consistently to every helper action.
`STATE_PATH_NOT_ABSOLUTE` requires an absolute path. `STATE_PERMISSIONS` requires
a private directory (mode 0700) and state file (0600); do not silently loosen or
rewrite existing permissions. Continue ordinary planning until the path issue
is resolved. Do not copy a conversation binding to multiple independent state
directories or hosts, where their locks cannot coordinate.
