# Done — Confiabilidade do ciclo de vida (crash e vazamento de recursos)

O app crashava no uso normal (coredump `SIGABRT` reproduzido) e, ao falhar, deixava
o modelo ocupando 2 GB de VRAM, processos auxiliares vivos e o tray preso em
"gravando". Depois deste ciclo ele sobrevive ao uso repetido, encerra limpo em 1 s,
libera a GPU até quando é morto com `kill -9`, e explica toda falha de captura.

## Artefatos

| Step | Arquivo |
|---|---|
| 1 Problema | `docs/01-problem/crash-and-resource-leaks.md` |
| 2 User Stories | `docs/02-user-stories/crash-and-resource-leaks.md` |
| 3 Use Cases | `docs/03-use-cases/crash-and-resource-leaks.md` |
| 4 Spec | `docs/04-spec/crash-and-resource-leaks.md` |
| 5 Test Cases | `docs/05-test-cases/crash-and-resource-leaks.md` |
| 6 To Do | promovido para este card (deletado de `kanban/06-todo/`) |
| 7a Plano | `kanban/07-implementation/crash-and-resource-leaks.md` |
| 8 Code Review | `kanban/08-code-review/crash-and-resource-leaks.md` |
| 9 Run Test | `kanban/09-run-test/crash-and-resource-leaks.md` |

## Código alterado

| Arquivo | O que mudou |
|---|---|
| `vibe_rtts/proc.py` (novo) | `StderrTail` (últimas linhas de stderr de um `QProcess`) e `run_detached` (helper sem zumbis) |
| `vibe_rtts/transcriber.py` | Sinais renomeados para `transcribed`/`failed`, liberando o `finished` nativo do `QThread` — a causa do abort |
| `vibe_rtts/tray.py` | Referência do worker solta só no `finished` nativo; `recording_failed` desfaz RECORDING; TRANSCRIBING no ato do comando; espera o worker no Quit; clipboard e paste via `run_detached` |
| `vibe_rtts/recorder.py` | Reescrito assíncrono (nada de `waitForFinished` na GUI), com `recording_failed`, coleta de stderr do ffmpeg, `abort()` para o encerramento e guarda `_shutting_down` |
| `vibe_rtts/daemon.py` | Reúso do `StderrTail`, `--exit-with-parent` no spawn, `engine_stopped` uma única vez, orçamentos de espera curtos, referência local no `stop()` |
| `vibe_rtts/shortcut.py` | `dbus-monitor` passa a ter dono e é encerrado no `cleanup()` |
| `vibe_rtts/app.py` | `set_wakeup_fd` + `QSocketNotifier` no lugar do polling; encerramento ordenado via `app.quit()`; `recorder.abort()` no cleanup |
| `vibe_rtts/history_window.py` | Copy do histórico via `run_detached` |
| `daemon/voice_daemon.py` | `--exit-with-parent` (`prctl(PR_SET_PDEATHSIG)`), warmup em dois passes com políticas distintas |
| `Makefile` | Alvo de atalho idempotente, com o ícone do tema |
| `tests/` | `fakes.py` (fake compartilhado), `test_lifecycle.py` (novo), `test_engine_autostart.py` ajustado — 35 testes |
| `README.md` | Comportamento novo documentado |

## Status final dos TCs — 15/15 PASSED


- [x] TC-1: Ciclo de ditado repetido não derruba o app — ✅ (10/10 ciclos, app vivo, zumbis 0→0 — evidence/results3.txt)
- [x] TC-2: Falha de transcrição avisa e mantém o app vivo — ✅ (falha de transcrição avisada, tray em READY, motor intacto — evidence/results3.txt)
- [x] TC-3: Sair durante a transcrição encerra limpo — ✅ (encerrou em 1s, 0 coredump/0 órfão/0 aviso de QProcess — evidence/results3.txt)
- [x] TC-4: Morte violenta do app libera a GPU — ✅ (daemon morreu com o app (PDEATHSIG), VRAM 1 MiB — evidence/results3.txt)
- [x] TC-5: Daemon externo adotado é encerrado pelo Stop — ✅ (adotou com device=cuda; Stop em 0,101 s matou o externo e liberou a VRAM — evidence/results_tc5.txt)
- [x] TC-6: Gravação sem áudio não trava o estado — ✅ (avisou "No audio captured", destravou, ciclo seguinte ok — evidence/results_tc6_tr3.txt)
- [x] TC-7: Dispositivo de áudio indisponível reporta a causa real — ✅ (stderr real do ffmpeg na mensagem (Error opening input) — evidence/results3.txt)
- [x] TC-8: Parar de gravar não congela a interface — ✅ (pior latência 69 ms — evidence/results3.txt)
- [x] TC-9: Primeira ditada tem a mesma latência da segunda — ✅ (522 ms vs 523 ms — evidence/results3.txt)
- [x] TC-10: Reinstalar o atalho de menu preserva a personalização — ✅ (Icon preservado e idempotente — evidence/results3.txt)
- [x] TR-1: Atalhos globais sobrevivem a fechar e abrir — ✅ (atalhos voltam após reabrir — evidence/results3.txt)
- [x] TR-2: Menu do tray íntegro — ✅ (History com 200 itens, Copy levou o texto ao clipboard, Stop/Start Engine ok — evidence/results_tc5.txt)
- [x] TR-3: Paste (Numpad +) continua colando — ✅ (colou na janela em foco — evidence/results_tc6_tr3.txt)
- [x] TR-4: Preload e instância única seguem íntegros — ✅ (preload 11s + segunda instância recusada + AUTOSTART=0 em INACTIVE — evidence/results3.txt)
- [x] TR-5: Protocolo do socket íntegro para clientes externos — ✅ (status=ready device=cuda transcrição ok — evidence/results3.txt)


## Ledger de Follow-ups (final — zero ABERTO)

| # | Achado | Detectado em | Balde | Status | Resolução |
|---|--------|--------------|-------|--------|-----------|
| F5 | Import órfão `Path` em `vibe_rtts/history.py:2` | Step 7b (varredura estática) | C | DESCARTADO | Arquivo não aberto por este trabalho (nenhuma das 11 tasks toca `history.py`) e sem relação causal; remover seria refatoração de escopo alheio |
| F6 | Imports órfãos `QTimer`/`AppState` em `tests/test_tray_double_click.py:10,12` | Step 7b (varredura estática) | C | DESCARTADO | Arquivo de teste não tocado (o `FakeDaemon` extraído saiu de `test_engine_autostart.py`); os 6 testes dele seguem verdes |
| F1 | `ydotoold` roda como root com socket `0666` (qualquer processo local pode injetar teclas) | Step 1 | C | DESCARTADO | Serviço do sistema instalado pelo pacote, fora do repositório e não tocado por este trabalho; verificado que o paste funciona por ele (`/tmp/.ydotool_socket`) e nenhum arquivo desta feature o modifica |
| F2 | Sinal `recording_started` sem nenhum consumidor (código morto) | Step 4 | A | RESOLVIDO-NO-STEP | Removido no 7b (T2), junto da reescrita assíncrona do recorder |
| F11 | Cada cópia para o clipboard e cada paste deixavam um processo **zumbi** (`[wl-copy] <defunct>`, `[ydotool] <defunct>`): `subprocess.Popen` nunca era reaped | Step 9 (inspeção de processos do app durante TC-1) | A | RESOLVIDO-NO-STEP | Helper `run_detached` em `proc.py` (Qt reap automático), usado nos 3 pontos |
| F10 | `QProcess: Destroyed while process ("ffmpeg") is still running` no encerramento: um `finished` já enfileirado reiniciava a conversão depois do `abort()` | Step 9 (TC-3) | A | RESOLVIDO-NO-STEP | Guarda `_shutting_down` nos handlers do recorder |
| F9 | Encerrar com SIGTERM causava **SIGSEGV** (coredump): o handler Python rodava `cleanup()` + `sys.exit()` dentro do dispatch de slot do PySide. Introduzido por D9 | Step 9 (TC-3) | A | RESOLVIDO-NO-STEP | O handler não faz nada; o notifier chama `app.quit()` e o `aboutToQuit` roda o cleanup em ponto seguro |
| F8 | Ícone permanecia em RECORDING por ~0,39 s após o comando de parada (tempo da conversão do wav), contrariando US-5/UC-10 embora a GUI já não bloqueasse | Step 9 (TC-8) | A | RESOLVIDO-NO-STEP | O tray passa a TRANSCRIBING no ato do comando; o resultado da conversão só confirma ou reverte |
| F7 | Log e mensagem de falha poluídos pelo banner (~4 KB) e pelas linhas de progresso do ffmpeg — as "últimas 5 linhas" seriam `size=189KiB...` em vez da causa | Step 9 (TC-1) | A | RESOLVIDO-NO-STEP | `-hide_banner -loglevel error -nostats` nas duas invocações |
| F4 | `stop()` estourava `AttributeError` quando o handler `finished` zerava `self._process` durante o `terminate()` (introduzido em T3) | Step 7b (achado por TC-2 automatizado) | A | RESOLVIDO-NO-STEP | Referência local ao processo no bloco de parada |
| F3 | Step 6 não gerou task para D6 (`dbus-monitor` órfão), apesar de D6 ter UC-5 e TC-3 | Step 7b | A | RESOLVIDO-NO-STEP | Task T11 acrescentada ao card e ao checklist do plano, e implementada no 7b |

## Tasks concluídas (do card de to-do)

T1 `proc.py` · T2 recorder assíncrono · T3 daemon manager (reúso + emissão única + flag) · T4 sinais do worker · T5 tray · T6 sinais POSIX no app · T7 daemon (PDEATHSIG + warmup) · T8 Makefile · T9 testes · T10 TCs de regressão · **T11 `dbus-monitor`** (acrescentada no 7b: o Step 6 não gerou task para D6).

## Princípios — o que produziram

- **Reutilizado (DRY):** o `finished` nativo do `QThread` que estava desperdiçado pelo sombreamento; `DaemonManager._ask`, `AppState`, o padrão de notificação (`showMessage` + `Warning`), `QTimer.singleShot` e o `FakeDaemon` dos testes (movido para `tests/fakes.py` e usado por dois módulos); o buffer de stderr do daemon virou `StderrTail` com dois consumidores, e o `Popen` disperso virou `run_detached` com três.
- **Descartado (YAGNI):** estado `STARTING` no `AppState`, idle timeout de VRAM, unit systemd para o daemon, watchdog de `getppid()` por polling, retry automático de captura e de preload, camada de i18n, e a abstração genérica de "processo externo gerenciado" que unificaria daemon + ffmpeg (ciclos de vida diferentes).
- **Elevado (tocou = refatora):** literal `"ffmpeg"` e as flags de silêncio extraídos (`_FFMPEG`, `_FFMPEG_QUIET`); dois laços de polling copiados no `daemon.py` unificados em `_wait_for`; sinal morto `recording_started` removido; `shell=True` com `sleep` trocado por timer; `subprocess.Popen` sem dono eliminado dos três pontos; e o `recorder.py` saiu de dois métodos bloqueantes para um método por etapa do ciclo.

## Nota de processo

O loop 7b→8→9 rodou **cinco vezes**: a execução real encontrou cinco defeitos que a
leitura de código não pegou (F7 a F11), incluindo um **SIGSEGV no encerramento** que
a própria correção anterior havia introduzido. Cada fix invalidou o ciclo e forçou
re-teste completo. Duas rodadas foram descartadas por defeito do harness de teste
(documentadas em `kanban/09-run-test/`), e nenhum resultado delas foi usado para
marcar TC como aprovado.
