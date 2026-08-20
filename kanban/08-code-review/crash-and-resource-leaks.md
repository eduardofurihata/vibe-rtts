# Relatório de Code Review — Confiabilidade do ciclo de vida

## Resumo
- **Branch**: `main` (sem worktree novo, sem branch nova) · **Iterações do loop**: 5 · **Data**: 2026-08-20 · **PR existente**: não
- Base de comparação: `a72dde0` (último commit) até o working tree

## Arquivos Analisados

| Arquivo | Linhas ± | Tipo | Veredicto |
|---|---|---|---|
| `vibe_rtts/proc.py` | +37 (novo) | utilitário folha | ✅ Limpo |
| `vibe_rtts/recorder.py` | +122/-33 | reescrita assíncrona | ⚠️ Corrigido (Issues #1, #3, #5) |
| `vibe_rtts/daemon.py` | +45/-23 | ciclo de vida do motor | ⚠️ Corrigido (Issue #6) |
| `vibe_rtts/transcriber.py` | +17/-6 | transporte | ✅ Limpo |
| `vibe_rtts/tray.py` | +27/-7 | estado/UI | ⚠️ Corrigido (Issues #1, #2) |
| `vibe_rtts/app.py` | +14/-6 | wiring/encerramento | ⚠️ Corrigido (Issue #1) |
| `vibe_rtts/shortcut.py` | +18/-2 | atalhos/listener | ⚠️ Corrigido (Issue #4) |
| `daemon/voice_daemon.py` | +50/-9 | servidor do modelo | ⚠️ Corrigido (Issues #7, #8) |
| `Makefile` | +3/-1 | instalação | ✅ Limpo |
| `tests/` (3 arquivos) | +260/-60 | testes | ✅ Limpo |

## Problemas Encontrados e Corrigidos

### Issue #1 — Quit durante a gravação deixava o ffmpeg órfão gravando
- Arquivos: `vibe_rtts/tray.py:_on_quit`, `vibe_rtts/app.py:cleanup`, `vibe_rtts/recorder.py` · 🔴 Alta · Categoria: regressão introduzida no 7b
- **Descrição**: ao tornar `stop_recording()` assíncrono (D4), o encerramento passou a retornar antes de o ffmpeg morrer. O app fechava e deixava a captura rodando indefinidamente em `/tmp` — trocando um vazamento (daemon) por outro (ffmpeg).
- **Correção**: novo `RecordingEngine.abort()` síncrono e silencioso (terminate → kill, sem emitir sinais), chamado no `_on_quit` e no `cleanup()`. Coberto por teste (`TestAbortOnShutdown`).
- Iteração 1

### Issue #2 — Caminho de falha consultava o daemon pela rede na thread da GUI
- Arquivo: `vibe_rtts/tray.py:_on_recording_failed` · 🟡 Média · Categoria: performance/consistência
- **Descrição**: decidia o estado com `daemon_manager.is_running()`, que para daemon adotado abre socket com timeout de 2 s — exatamente o congelamento que este trabalho existe para eliminar. Pior: contrariava a decisão do Spec de tratar `AppState` como fonte única de verdade.
- **Correção**: a transição usa o estado corrente (`RECORDING`/`TRANSCRIBING` → `READY`); se o motor caiu, `engine_stopped` já levou a INACTIVE e nada é sobrescrito. Teste ajustado para a regra correta (`test_failure_does_not_resurrect_a_dead_engine`).
- Iteração 1

### Issue #3 — Processo pendurado após `FailedToStart`
- Arquivo: `vibe_rtts/recorder.py:_on_capture_error` · 🟡 Média · Categoria: bug de estado
- **Descrição**: o Qt não emite `finished` para um processo que nunca iniciou, então `self._process` ficava preenchido com um QProcess morto e o próximo `stop_recording` reportava "not active" em vez de gravar.
- **Correção**: limpar `self._process` no ramo `FailedToStart`.
- Iteração 1

### Issue #4 — Corrida deixava o `dbus-monitor` órfão mesmo com o fix
- Arquivo: `vibe_rtts/shortcut.py:_start_dbus_monitor_listener` · 🟡 Média · Categoria: ciclo de vida
- **Descrição**: o `Popen` era atribuído a `self._monitor_proc` **dentro** da thread. Um encerramento rápido rodaria `cleanup()` antes disso e o processo escaparia — o mesmo defeito que a task pretendia corrigir, só com janela menor.
- **Correção**: criar o processo na thread principal (quem cria é o dono) e passar para a thread apenas a leitura.
- Iteração 2

### Issue #5 — `_force_kill` ignorava um ffmpeg travado em `Starting`
- Arquivo: `vibe_rtts/recorder.py:_force_kill` e `stop_recording` · 🟡 Média · Categoria: edge case
- **Descrição**: a guarda só matava processo em `Running`; um ffmpeg travado subindo escaparia do `terminate` e do `kill`. Pelo mesmo motivo, `stop_recording` tratava `Starting` como "não ativo" e devolvia falha enquanto a captura ainda ia subir.
- **Correção**: as duas condições passaram a considerar tudo que não é `NotRunning`.
- Iteração 2

### Issue #6 — `AttributeError` no Stop Engine
- Arquivo: `vibe_rtts/daemon.py:stop` · 🔴 Alta · Categoria: bug introduzido no 7b
- **Descrição**: `waitForFinished` bombeia eventos, então `_on_process_finished` zerava `self._process` no meio do bloco e a chamada seguinte estourava. Encontrado pelo teste automatizado de emissão única, não por leitura.
- **Correção**: referência local ao processo durante a parada. Registrado como F4 no ledger.
- Iteração 1

### Issue #7 — Política de warmup fatal aplicada ao passe errado
- Arquivo: `daemon/voice_daemon.py` · 🔴 Alta · Categoria: risco de indisponibilidade
- **Descrição**: os dois passes de warmup estavam num único `try`, sob a política "falha em CUDA = fatal". Essa política existe para detectar GPU sem memória; o passe do VAD roda em ONNX/CPU, então uma falha ali (pacote, modelo, formato) derrubaria o daemon sem nenhuma relação com a GPU.
- **Correção**: passes separados com políticas próprias — VAD falha = aviso; encoder/decoder falha em CUDA = fatal. Validado rodando o daemon de verdade: `Loading → Warming up → Model loaded. Ready.`
- Iteração 3

### Issue #8 — `prctl` sem verificação de retorno
- Arquivo: `daemon/voice_daemon.py:_die_with_parent` · 🟢 Baixa · Categoria: observabilidade
- **Descrição**: `prctl` devolve -1 em falha; sem checar, o daemon anunciaria proteção que não tem.
- **Correção**: checar o retorno e avisar em stderr.
- Iteração 3

### Issue #9 — Coleta de stderr do ffmpeg era inútil na prática
- Arquivo: `vibe_rtts/recorder.py` · 🔴 Alta · Categoria: o defeito que D5 devia resolver
- **Descrição**: encontrado ao executar o TC-1 (não por leitura). O ffmpeg escreve um banner de configuração de ~4 KB e uma linha de progresso duas vezes por segundo, então (a) o log do app ficou ilegível e (b) as "últimas 5 linhas" — que viram a mensagem de falha para o usuário — seriam `size=189KiB time=...`, nunca a causa real. A feature de diagnóstico existia e não diagnosticava nada.
- **Correção**: `-hide_banner -loglevel error -nostats` nas duas invocações, extraídos para `_FFMPEG_QUIET` (as flags apareciam duas vezes, mesmo caso do literal `_FFMPEG`). Registrado como F7 no ledger; o checklist de QA foi resetado e todos os TCs re-executados do zero, conforme o loop 7→8→9.
- Iteração 4

### Issue #10 — Cada cópia e cada paste deixavam um processo zumbi
- Arquivos: `vibe_rtts/tray.py`, `vibe_rtts/history_window.py`, `vibe_rtts/proc.py` · 🟡 Média · Categoria: vazamento de recurso (o tema da feature)
- **Descrição**: encontrado inspecionando os filhos do app durante o TC-1 — `[wl-copy] <defunct>` e `[ydotool] <defunct>`. `subprocess.Popen` só é reaped se alguém esperar por ele, e ninguém esperava; o app acumulava um PID zumbi por transcrição e outro por paste. O paste ainda usava `shell=True` com `sleep 0.1`, o que criava um shell inteiro só para esperar.
- **Correção**: helper `run_detached()` em `proc.py` (o Qt reap seus filhos detached), usado nos três pontos; o `sleep` virou `QTimer.singleShot(100, ...)`, sem shell.
- Iteração 5

## Análise de Cobertura
- **Stories atendidas**: 8/8 (US-1 a US-8)
- **Use cases cobertos**: 13/13 — os de execução real (UC-4, UC-6, UC-11, UC-12) vão ao Step 9
- **TCs preparados**: 10 + 5 de regressão; 4 automatizados em `tests/test_lifecycle.py` (30 testes verdes)
- **Gaps**: nenhum. O que não é automatizável (fork real, `make`, notificação do KDE) está nos TCs de execução do Step 9.

## Análise de Segurança
- **Input validation**: N/A — não há entrada de usuário nova; o socket segue aceitando só `status`/`device`/`shutdown`/caminho
- **Auth**: N/A (app local, sem rede)
- **Dados sensíveis**: ✅ o stderr coletado é de ffmpeg/daemon e não carrega credenciais; nada é enviado para fora da máquina
- **Injection**: ✅ nenhum `shell=True` novo; o `kill` do fallback continua restrito a PIDs obtidos por `pgrep` do nosso próprio script
- **Novo vetor de processo**: ✅ `prctl(PR_SET_PDEATHSIG)` só reduz privilégio de sobrevivência do filho — não amplia nada

## Análise de Qualidade (por princípio)

| Princípio | Veredicto | Evidência |
|---|---|---|
| SRP (responsabilidade única, camadas) | ✅ | `proc.py` faz uma coisa; o recorder ficou com um método por etapa do ciclo (captura → conversão → resultado); `abort()` separado de `stop_recording()` porque encerrar e parar têm contratos diferentes (um é silencioso, o outro reporta) |
| DRY (duplicação, reúso do § 3.1) | ✅ | `StderrTail` com dois consumidores reais; `_wait_for` substituiu dois laços de polling idênticos; `FakeDaemon` extraído para `tests/fakes.py` e usado por dois módulos; literal `"ffmpeg"` que eu havia duplicado virou `_FFMPEG` |
| KISS (complexidade) | ✅ | `_die_with_parent` são 12 linhas contra um watchdog; nenhuma máquina de estados nova — o `AppState` existente resolveu |
| YAGNI (§ 3.2 respeitado) | ✅ | Nada do que o plano descartou entrou: sem estado `STARTING`, sem idle timeout, sem retry, sem abstração de "processo gerenciado". O único acréscimo não planejado (`abort()`) veio de defeito real, não de especulação |
| Law of Demeter / acoplamento | ✅ | `proc.py` é folha (só PySide6); dependências só descem (`tray → {recorder, transcriber, daemon}`, `{recorder, daemon} → proc`); nenhum ciclo, nenhum `a.b.c.d` |
| Naming + consistência com o codebase | ✅ | `transcribed`/`failed`/`recording_failed` seguem a convenção de domínio já usada em `recording_stopped`/`engine_ready`; toasts mantêm `MessageIcon.Warning` conforme `docs/00-brainstorm/notifications-auto-close.md` |
| Nível vs. referência #1 | ✅ | Comportamento equivalente ao dos apps de ditado líderes: UI que nunca prende, falha com causa acionável, motor quente na primeira ditada, e recurso de GPU liberado por três caminhos independentes (Quit, crash via PDEATHSIG, Stop de daemon adotado) |

## Follow-ups Emitidos

| # | Achado | Balde | Status | Destino |
|---|---|---|---|---|
| F2 | Sinal `recording_started` morto | A | RESOLVIDO-NO-STEP | removido no 7b |
| F3 | Step 6 sem task para D6 | A | RESOLVIDO-NO-STEP | T11 criada e implementada |
| F4 | `AttributeError` no `stop()` | A | RESOLVIDO-NO-STEP | referência local (Issue #6) |
| F5 | Import órfão em `history.py` | C | DESCARTADO | arquivo não tocado por nenhuma task |
| F6 | Imports órfãos em `test_tray_double_click.py` | C | DESCARTADO | arquivo não tocado |
| F1 | `ydotoold` root com socket `0666` | C | DESCARTADO | serviço do sistema, fora do repo, sem relação causal |

As 8 issues deste review eram todas balde A (dentro do escopo documentado) e foram corrigidas nas 3 iterações — nenhuma ficou como follow-up.

## Veredicto Final
- **Status**: ✅ APROVADO
- **Confiança**: Alta — 30 testes automatizados verdes, o warmup validado com daemon real, e as duas correções mais graves (Issues #1 e #6) foram achadas por teste e por leitura adversarial, não por sorte
- **Notas para o teste**: TC-4 (PDEATHSIG) precisa de `kill -9` real; TC-7 depende de forçar um device de áudio inválido; TC-9 compara latências e exige daemon recém-iniciado; TC-5 precisa de daemon iniciado à mão (sem a flag) para provar que o externo não é afetado.
