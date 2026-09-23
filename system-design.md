# Review Guidelines & System Design

Repo Agent reads this file before every code review and flags any change that
violates the rules below (it cites the rule it broke). Replace the examples with
your project's real design and rules, then commit this file.

## System design / architecture

> Describe how the code is meant to be structured so the reviewer can judge each
> change in its intended context. A few lines is enough.

- Layers: UI → services → data access. UI must not import data-access modules directly.
- Dependencies flow inward only; no service may import from the UI layer.
- New collaborators are wired through the dependency-injection container, not constructed ad hoc.

## Review rules

> Each bullet is an enforceable rule. Keep them concrete and checkable.

- **No debug output**: no `console.log` (or language equivalent) in committed code — use the logger.
- **Error handling**: every `await` / external call that can fail is wrapped or its rejection handled; never swallow an error silently.
- **Naming**: functions are verbs, types/classes are PascalCase nouns; match the surrounding file's style.
- **Tests**: every new exported function or bug fix ships with at least one test covering the change.
- **No secrets**: never hard-code API keys, tokens, or passwords; read them from config/secret storage.
- **Public API**: exported functions have a doc comment describing inputs, outputs, and failure modes.
- **Performance**: no O(n²) loops or per-iteration I/O on data that can be large; batch or precompute instead.

<!-- Add, remove, or rewrite any rule above. Leave this file empty (or delete it)
     to fall back to Repo Agent's default review rubric. -->
