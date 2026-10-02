# Repository scope

- Keep this repository focused on the standalone ComfyUI-ChickTools package.
- Describe its node interfaces, supported behavior, installation and reproducible tests.
- Use synthetic examples and generic installation paths in all tracked files.
- Keep private integrations, unrelated projects, machine-specific troubleshooting and operational records outside this repository.
- Keep ChickHideNode and NotifyMeNode independent; compose them only through standard ComfyUI connections.
- Run the existing unit tests for code changes and use only small, model-free workflows for local validation.
- Commit and push only files that belong to this package.
