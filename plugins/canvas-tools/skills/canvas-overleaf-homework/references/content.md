# Problem statements, solutions, and figures

For a scaffold-only edit, read the current file and preamble and apply
[Prepare blank solutions](#prepare-blank-solutions). Do not refresh statements or
figures unless requested. Other content work follows the relevant sections below.

## Transcribe the selected problems

1. Resolve each requested visible problem number or stable page anchor to one
   unique source block, then keep the selected blocks in source order.
   Ambiguous numbering blocks that problem.
2. Transcribe the complete statement in source order. Preserve wording,
   punctuation, spelling, numbering, notation, enumerated subparts, difficulty
   marks, and captions exactly. Never paraphrase, summarize, correct grammar, or
   silently expand an abbreviation.
3. Only make syntax-preserving conversions required for LaTeX rendering, such
   as decoding HTML entities, mapping MathML or source TeX to equivalent LaTeX,
   and escaping LaTeX-reserved characters. Do not change mathematical meaning.
4. Compare the assembled statement against the source before writing. If exact
   text or notation cannot be read reliably, stop and request a clearer source
   or user-provided text instead of reconstructing it.
5. Wrap each statement in stable managed comments. Keep the solution outside
   the managed region:

   ```tex
   % BEGIN CANVAS-OVERLEAF PROBLEM 2
   \begin{problem}{2.}
   <exact source statement>
   \end{problem}
   % END CANVAS-OVERLEAF PROBLEM 2

   \begin{solution}
   \end{solution}
   ```

   Pass the complete visible problem label, including its punctuation and any
   difficulty mark, as the `problem` environment argument.

   On a rerun, replace only the matching managed statement region. Preserve its
   existing `solution` environment byte-for-byte. If an older unmarked block
   cannot be isolated uniquely, stop instead of risking solution loss.

   Keep generated comments concise: retain the managed boundary markers, but do
   not insert `% Source:` URL lines or visible source/license paragraphs unless
   requested or required by the source license. Retain provenance in the working
   record or receipt. Remove existing source comments only when requested, and
   do not remove unrelated attribution or notices.

## Prepare blank solutions

- For a new multipart problem, put one blank `\item` per source subpart in its
  `solution` environment, matching the order and labels. For a problem without
  subparts, leave the solution empty. Do not add answers, hints, distribution
  names, or repeated instructions to start typing.
- Follow `$overleaf`'s LaTeX editing guidance and the project's current preamble.
  Reuse an existing `parts` environment, or use `enumitem`'s `enumerate` options
  when that package is loaded. Match labels such as a., b. or (a), (b) through
  list options, not manually typed text. Add no new package for an existing list.
- An explicit request to prepare an existing solution authorizes only that
  scaffold change. Preserve all answer text; do not reset a partially completed
  solution. Statement refresh, figure repair, and metadata updates still leave
  existing solutions untouched.

## Preserve every source figure

- Inspect the complete selected source block for images, diagrams, plots, and
  figure captions. Include every figure that belongs to the question.
- Prefer the original linked asset. Preserve its file format, pixel dimensions,
  and source resolution; record its MIME type and SHA-256 before import. Never
  redraw, trace, screenshot, or generate a replacement.
- Stage the file below an Overleaf-configured allowed import root and name it
  `figures/problem-<NUMBER>-<INDEX>.<EXT>`. Use a stable one-based index when a
  problem has multiple figures.
- Put `\includegraphics` at the corresponding logical location in the statement.
  Preserve a source caption exactly; do not invent one when none exists.
- If a required original asset is missing, inaccessible, or fails validation,
  stop before writing that problem. Do not omit the figure silently.
