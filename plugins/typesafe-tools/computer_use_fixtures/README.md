# Disposable Computer Use fixtures

These browser and macOS fixtures contain synthetic records only. They have no
network calls, persistence, accounts, or external side effects. Each case shows
its goal and emits visible accessibility text `PASS <case_id>` only after the
requested end state. A wrong record click increments `Wrong actions: N` and can
be recovered within the same case.

## Cases

Use `<surface>-<category>-<variant>`, where surface is `browser` or `native`,
variant is `0` through `3`, and category is one of:

| Category | Required interaction |
| --- | --- |
| `navigation` | Open the named section, then the named record. |
| `search` | Search the record name, then open it. |
| `filter` | Select the named status, then open the record. |
| `tabs` | Select the named tab, then open the record. |
| `expand` | Expand the named group, then open the record. |
| `duplicate_label` | Choose the correct row among identical `Open` buttons. |
| `stale_index` | Reorder rows before choosing the correct `Open` button. |
| `missing_target` | Refresh state to reveal the target, then open it. |
| `recovery` | Search, retry after the first empty result, then open the record. |
| `dialog` | Open the picker and select the target inside the dialog. |
| `long_tree` | Choose the requested queue and status, then select the target among 37 rows with identical `Open` buttons. |

Variant targets are `0` Quartz, `1` Cedar, `2` Nimbus, and `3` Orchid. The UI
shows the exact goal, so a runner can use the case ID and verify the goal text
without hard-coding the target. Use variant `0` for tuning and variants `1`–`3`
for held-out cases.

`browser-long_tree-0` and `native-long_tree-0` are additional diagnostic
cases, separate from the frozen benchmark. They support only variant `0` and
require three decisions: queue, status, and row. The target button is disabled
until the queue and status are correct, while other `Open` buttons remain
available and count as wrong actions. The rows reorder as the selections
change, so the final button must be located from a fresh UI observation.

## Browser

From the repository root:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory plugins/typesafe-tools/computer_use_fixtures/browser
```

Open `http://127.0.0.1:8765/?case_id=browser-search-0` in the browser under
test. Reloading resets all state; changing `case_id` loads another case. The
visible result is in `#result`, with `data-result="pass"` only on success. The
page uses no remote resources.

## Native macOS app

Build into a disposable directory outside the checkout, then launch one case:

```sh
fixture_build_dir="$(mktemp -d "${TMPDIR:-/tmp}/jev-cu-fixture.XXXXXX")"
fixture_app="$(plugins/typesafe-tools/computer_use_fixtures/build-native.sh "$fixture_build_dir")"
open -n -a "$fixture_app" --args --case-id native-search-0
```

The window also has a `Case ID` field and `Load case` button. Loading a case
resets state, including the wrong-action counter. To reset the same case,
select `Load case` again or quit and relaunch the app. The result text has
accessibility identifier `fixture-result`. macOS accessibility may combine
the result and `Wrong actions: N` into one value; look for the exact
`PASS <case_id>` token within that value. Delete `fixture_build_dir` when
finished.
