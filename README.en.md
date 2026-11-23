# Kang Twin

A record that remembers you, and an AI assistant that grows it and puts it to work.

[한국어](README.md)

Every night Kang Twin picks a gap in your notes and asks you one question on Telegram. Nothing is written until you tap **[Apply]**; then the answer becomes a line in a plain Markdown note. From those notes it shortlists contests and grants, drafts applications in your own voice, and has a second AI that did not write the draft check it for unsupported facts and missing criteria.

- Plain Markdown notes. Open them in Obsidian or any editor.
- Human approval before any note changes or anything leaves your machine.
- The LLM (`claude -p`) runs read-only, with no shell and access to your notes folder only.
- Python 3.9 standard library only. Nothing to `pip install`.

Requirements: macOS, Python 3.9+, a logged-in Claude Code CLI, a Telegram bot token. The scouts and prompts are written for Korean users and Korean contest and grant sources.

See the Korean README for setup; commands are the same. Without a config file it runs on `sample-vault/`, a fictional person.

License: MIT
