# Official LaTeXiT and LinkBack

The qualified prototype uses official LaTeXiT through GUI automation. OmniGraffle's signed sandbox permits the original LaTeXiT service but denied the separately named automation service. Do not impersonate application identities, re-sign OmniGraffle, disable its sandbox, or describe the stock application as isolated.

New equations belong to official LaTeXiT. Preserve TeX source, preamble, mode, font size and equation identity with the native artifact. Read equation archives through their owning native application; Python must preserve opaque archive bytes rather than inventing Objective-C serialization. Existing LinkBack ownership migration must be explicit and limited to the selected equation.

New equations use official `.tex` import to initialize the requested preamble; GUI New documents protect their first two preamble lines. Linked updates support source, mode and font-size changes while retaining the existing preamble. Retrieve it with `equation-source` first. A different preamble requires a separately inserted equation; do not bypass LaTeXiT's protected lines or silently rewrite the requested preamble.

The editing cycle must select the inspected equation in OmniGraffle, invoke its actual LinkBack edit action, update the source in LaTeXiT, render, deliver the callback, and verify the changed native equation. Replacing PDF bytes or metadata alone is not this cycle. Invalid TeX must return a bounded error without saving a changed diagram; capture and dismiss only task-owned error UI.

GUI work requires an unlocked desktop and application automation/accessibility access. Preserve clipboard content and restore only if it has not changed since this operation. Do not close unrelated windows, alter preferences, or discard unsaved user documents as routine recovery. On interruption, reconcile the pending operation before editing again.

Text entry uses the selected editor field without changing the clipboard. Copy waits for both the `com.adobe.pdf` representation and the LinkBack envelope. Snapshots retain every readable format; an unreadable legacy plain-text alias may be omitted only when that item's complete UTF-8 representation is retained, with a receipt warning. Other unreadable formats stop the operation.

Acceptance requires insertion, two updates, save/reopen, both application restarts and another callback, source/settings retention and unrelated-object preservation. Prototype evidence is recorded in the repository's `scripts/omnigraffle/README.md`; production validation is separate.
