# Homework project

- `main.tex` contains assignment metadata and selects the homework body.
- `config/preamble.tex` contains packages and the `problem` and `solution`
  environments.
- `homework/` contains one assignment body per file.
- `figures/` contains original figures from the problem source.

Problem statements between `BEGIN CANVAS-OVERLEAF PROBLEM` and
`END CANVAS-OVERLEAF PROBLEM` comments are managed from the source page. Keep
answers outside those markers, inside the matching `solution` environment.
