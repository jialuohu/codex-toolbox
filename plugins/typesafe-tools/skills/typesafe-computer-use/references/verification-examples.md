# Synthetic fixture verification examples

These examples use the helpers from [observation and binding](observation.md).
Read that procedure and initialize its helpers before using the examples.
Adapt fixture markers to the authorized task; do not treat them as a generic
success check.

The browser recipe binds one action and checks the exact fixture result:

```javascript
var cuBefore = await target.getAXState({ emit: false, disableDiffing: true });
var cuBinding = cuMatchUnique(cuBefore, { stateKind: "full", role: "button", label: "Open",
  context: ["Quartz"], operation: "click", preconditions: ["present", "enabled"] });
if (cuBinding.status !== "bound") {
  nodeRepl.write(JSON.stringify({ binding: cuBinding, state: cuBefore, verified: false }));
} else {
  var cuActionError = null, cuAfter = null, cuObservationError = null;
  try { await target.click(cuBinding.index); } catch (error) { cuActionError = String(error); }
  try { cuAfter = await target.getAXState({ emit: false }); } catch (error) { cuObservationError = String(error); }
  if (cuAfter !== null) {
    var cuView = cuSelectExcerpt(cuAfter, { terms: ["PASS", "Wrong actions"],
      required: ["PASS browser-duplicate_label-0", "Wrong actions"] });
    if (cuView.needsFull) {
      try {
        cuAfter = await target.getAXState({ emit: false, disableDiffing: true });
        cuView = cuSelectExcerpt(cuAfter, { terms: ["PASS", "Wrong actions"],
          required: ["PASS browser-duplicate_label-0", "Wrong actions"], full: true });
      } catch (error) {
        cuObservationError = String(error);
        cuView = { direct: true, text: cuAfter };
      }
    }
    var cuVerified = !cuObservationError && !cuView.incomplete &&
      /^\s*\d+\s+text PASS browser-duplicate_label-0\s*$/m.test(cuAfter) &&
      /^\s*\d+\s+text Wrong actions: 0\s*$/m.test(cuAfter);
    nodeRepl.write(JSON.stringify({ action_error: cuActionError, observation_error: cuObservationError,
      verified: cuVerified, result: cuView.direct && !cuView.incomplete ? cuView.text : cuView }));
  } else nodeRepl.write(JSON.stringify({ action_error: cuActionError, observation_error: cuObservationError,
    verified: false }));
}
```

Confirm the exact fixture goal marker and wrong-action count in the observed
result; text in a candidate or
Jev response is not verification. The browser example requires a complete
result state. In a native virtualized list, a partial list still blocks unique
target binding, but an independent, complete result subtree may verify the
exact marker and counter even while the unrelated list remains virtualized.
For this synthetic native fixture, the result is one element outside the list:

```javascript
// cu-native-result-begin
var cuNativeState = await target.getAXState({ emit: false, disableDiffing: true });
var cuNativeLines = cuNativeState.split("\n");
var cuNativeScrolls = cuNativeLines.filter(line => /^\s*\d+ scroll area .*showing \d+-\d+ of \d+ items/.test(line));
var cuNativeResults = cuNativeLines.filter(line => /, ID: fixture-result\s*$/.test(line));
var cuNativeVerified = cuNativeScrolls.length === 1 && cuNativeResults.length === 1 &&
  cuNativeScrolls[0].match(/^\s*/)[0] === cuNativeResults[0].match(/^\s*/)[0] &&
  /^\s*\d+ text Value: PASS native-long_tree-0 Wrong actions: 0, ID: fixture-result\s*$/.test(cuNativeResults[0]);
nodeRepl.write(JSON.stringify({ verified: cuNativeVerified, result: cuNativeResults[0] ?? null }));
// cu-native-result-end
```

Use task-specific exact markers and result structure elsewhere. A partial
result element, missing counter, or wrong case ID is unverified.
