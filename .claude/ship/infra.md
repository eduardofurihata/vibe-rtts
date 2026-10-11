# Infra — vibe-rtts

## Produção (app local do macOS)
- Branch que publica: `main` (push em origin).
- Onde roda: agente launchd `com.github.furihata.vibe-rtts`. O bundle `~/Applications/Vibe RTTS.app` dá `exec` em `.venv/bin/python -m vibe_rtts` direto do repo.
- Workflow/runner: nenhum, não tem CI.
- Configurar/deploy: `launchctl kickstart -k gui/$(id -u)/com.github.furihata.vibe-rtts`. Só precisa de `make install-mac` quando mudam o launcher/bundle (`scripts/`, `Makefile`).
- Sem migrations, secrets ou env. O histórico fica em `~/Library/Application Support/vibe-rtts/history.db`.
- Checar: `~/Library/Logs/vibe-rtts.log` mostra `[SHORTCUT] Registered …` sem `failed`, e o processo `python -m vibe_rtts` precisa ter começado depois do último commit.
- Testes: `.venv/bin/python -m pytest tests -q`.
- Rollback: `git revert <sha>` + push, depois o kickstart.
