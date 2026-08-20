# Confiabilidade do ciclo de vida — Spec

## Referências de qualidade (baseline)

- **Apps de ditado líderes** (Wispr Flow, Superwhisper, MacWhisper): o motor fica quente para a primeira ditada, a falha de microfone aparece como aviso acionável, e o estado nunca fica preso — o botão sempre volta ao repouso.
- **Ciclo de vida de processo filho em apps grandes** (Chrome/Electron/VS Code): filho amarrado à vida do pai via `PR_SET_PDEATHSIG` no Linux, para que crash do pai não deixe filho segurando recurso.
- **Qt/KDE**: `QThread` nunca é destruído em execução; ownership resolvido pelo sinal `finished`. `qFatal` em destrutor de thread ativa é considerado bug de ciclo de vida, não condição de corrida aceitável.
- **Padrão do próprio projeto** (prioridade 1): sinais nomeados por domínio (`recording_stopped`, `engine_ready`), estado único em `AppState`, coleta de stderr em `DaemonManager` (`daemon.py:124-130`), diálogo com o daemon centralizado em `_ask()` (`daemon.py:153-166`).

## Escopo de plataforma (derivado, não declarado)

Verificação de Realidade (Step 3) + varredura do repositório: só existe Python + PySide6/Qt6 rodando em KDE/Wayland; nenhum diretório `android/`, `ios/`, nenhum projeto web. **A feature não tem superfície mobile nem web** — a execução do Step 9 é desktop Linux, e "front" para efeito de evidência é o tray + notificação do KDE, o log do app e o estado observável do sistema (`nvidia-smi`, `pgrep`, `coredumpctl`).

## Autonomous Decision Loop

### Round 1 — decisões estruturais

**D1 — `TranscribeWorker` deixa de sombrear `QThread.finished`; a referência só cai no `finished` nativo.**
Renomear para `transcribed = Signal(str, str)` e `failed = Signal(str)`; em `tray.py`, conectar `worker.finished` (nativo, emitido quando o thread realmente encerrou) a um slot que limpa `self._transcribe_worker`.
- *Exige*: UC-1, UC-2 · *Referência*: Qt (ownership por `finished`) + padrão do projeto (sinais por domínio, como `recording_stopped`)
- *Reúso (DRY)*: nenhuma peça nova — o `finished` nativo já existia e estava sendo desperdiçado pelo sombreamento
- *Alternativas descartadas*: `worker.deleteLater()` (com PySide o wrapper Python sobrevive ao objeto C++ deletado, criando armadilha de `RuntimeError` sem ganho — soltar a referência já é suficiente); migrar para `QThreadPool`/`QRunnable` (reescrita sem UC que a exija)

**D2 — Encerrar esperando o worker.**
`cleanup()` (`app.py`) e o Quit do tray aguardam o worker com `wait(3000)` antes de sair.
- *Exige*: UC-3 · *Referência*: Qt · *Alternativas descartadas*: matar o thread (`terminate()`) — corrompe estado e não é necessário: a transcrição é curta

**D3 — Daemon amarrado à vida do app: `--exit-with-parent`.**
O daemon, quando iniciado pelo app, chama `prctl(PR_SET_PDEATHSIG, SIGTERM)` via `ctypes` e, contra a corrida do pai morrer antes disso, verifica `os.getppid() == 1` e sai. `DaemonManager` passa a flag; daemon iniciado à mão continua independente.
- *Exige*: UC-4 (e preserva UC-6) · *Referência*: Chrome/systemd; decisão do usuário nesta sessão (libertar VRAM > adoção rápida)
- *Alternativas descartadas*: `QProcess.setChildProcessModifier` (**verificado: não existe no PySide6 6.10.2**); unit systemd própria para o daemon (muda o modelo de deploy, nenhum UC pede); watchdog por polling de `getppid()` (o kernel já entrega o sinal — polling é desperdício); idle timeout de VRAM (nenhum UC pede, muda semântica de READY)

**D4 — `RecordingEngine` assíncrono, guiado pelos sinais do `QProcess`.**
Nada de `waitForFinished` na thread da GUI: `stop_recording()` pede `terminate()` e retorna; o `finished` do ffmpeg dispara a conversão, cujo `finished` emite `recording_stopped(wav)` ou o novo `recording_failed(motivo)`. Um `QTimer` de guarda promove para `kill()` se o ffmpeg não sair.
- *Exige*: UC-7, UC-8, UC-9, UC-10 · *Referência*: apps de ditado (UI sempre responsiva) + padrão do projeto (`DaemonManager` já é assíncrono por sinais de `QProcess`)
- *Reúso (DRY)*: mesma forma do `DaemonManager` (start assíncrono + `finished`/`errorOccurred`), não um mecanismo novo
- *Alternativas descartadas*: mover a conversão para uma `QThread` (processo externo já é assíncrono — thread só adicionaria ciclo de vida para gerenciar, ver D1); manter bloqueante com timeout menor (não resolve UC-10)

**D5 — Falha de captura é observável: coletar stderr do ffmpeg.**
Trocar `setStandardErrorFile(os.devnull)` por coleta das últimas linhas, entregues em `recording_failed` (toast) e no log.
- *Exige*: UC-9, UC-8 · *Referência*: padrão do projeto — `DaemonManager._stderr_tail` já faz exatamente isso
- *Reúso (DRY)*: o padrão passa a ter **dois** consumidores concretos, então extrair `vibe_rtts/proc.py` com um coletor `StderrTail` (módulo folha: depende só de PySide6, ninguém do projeto depende dele em sentido inverso) e usar nos dois — sem duplicar o buffer manual

**D6 — `dbus-monitor` é encerrado no cleanup.**
Guardar o `Popen` em `self._monitor_proc` e finalizá-lo (`terminate` → `kill`) no `cleanup()` de `ShortcutHandler`, junto do desregistro das teclas.
- *Exige*: UC-5 · *Referência*: boa prática de ciclo de vida (todo processo criado tem um dono que o encerra)
- *Alternativas descartadas*: reescrever a escuta com QtDBus nativo (o próprio código documenta em `shortcut.py:41-49` que PySide6 não emite a assinatura `ai` exigida; nenhum UC pede a troca)

**D7 — Warmup espelha o caminho de produção.**
Dois passes antes de anunciar READY: (a) `vad_filter=True` para materializar o Silero VAD — `get_vad_model()` é `functools.lru_cache` e abre duas `InferenceSession` ONNX na primeira chamada (`faster_whisper/vad.py:247`); (b) `beam_size` igual ao de produção com `vad_filter=False`, para aquecer encoder/decoder.
- *Exige*: UC-11 · *Referência*: `faster_whisper/vad.py:247` + apps de ditado (primeira ditada não é a mais lenta)
- *Alternativas descartadas*: um passe só (é o estado atual e não cobre o VAD); sintetizar voz para passar o VAD (dependência nova para nada — o objetivo é carregar o modelo, não medir detecção)

**D8 — `engine_stopped` uma única vez.**
`stop()` não reemite quando `_on_process_finished` já emitiu.
- *Exige*: UC-13 · *Referência*: princípio de sinal idempotente · *Alternativa descartada*: deixar o consumidor deduplicar (empurra o defeito para quem escuta)

**D9 — Sinais POSIX sem polling.**
`signal.set_wakeup_fd` com um `socketpair` + `QSocketNotifier` substitui o `QTimer` de 200 ms.
- *Exige*: UC-3, UC-5 · *Referência*: padrão canônico Qt+Python · *Alternativa descartada*: manter o timer (acorda a CPU 5×/s num laptop para nada)

**D10 — `make dev` idempotente.**
`ICON := audio-input-microphone` (nome do freedesktop icon naming spec, presente em qualquer tema) para o alvo escrever exatamente o que já está instalado.
- *Exige*: UC-12 · *Referência*: personalização já feita pelo usuário no `.desktop` instalado (prioridade 1: padrão do projeto na prática)
- *Alternativas descartadas*: não sobrescrever se existir (deixa o arquivo divergir da fonte para sempre); manter o PNG do repo (contraria a escolha já feita e ignora o tema do sistema)

**D11 — Orçamento de espera do stop de daemon adotado.**
Reduzir para ~1,5 s de espera do `shutdown` + ~1 s por sinal no fallback.
- *Exige*: UC-6 · *Referência*: medição desta sessão (o `shutdown` responde em <300 ms)
- *Alternativa descartada*: tornar assíncrono com máquina de estados (complexidade sem UC — o caminho comum é imperceptível)

### Round 2 — re-análise do zero (contradições e dimensões não cobertas)

1. **D3 × UC-6**: PDEATHSIG só é armado quando o app inicia o daemon; daemon externo segue independente — sem contradição, e o aviso de "daemon externo não obedeceu" continua válido.
2. **D3 × liberação de VRAM**: o handler de SIGTERM do daemon já remove o socket antes de sair (`voice_daemon.py:81-90`), então o app seguinte não encontra socket órfão.
3. **D4 × UC-8**: com a captura assíncrona, o tray entra em RECORDING de forma otimista e o `errorOccurred(FailedToStart)` chega em milissegundos → volta a READY com aviso. **Decisão**: manter o otimismo em vez de criar um estado STARTING — cumprir UC-8 como "não permanece em RECORDING sem captura viva" (rollback imediato) evita um sexto estado que nenhuma story pede (YAGNI).
4. **Sinal morto**: `recording_started` (`recorder.py:9`) não tem nenhum consumidor. Com o otimismo de D4 ele continua sem dono → **remover** (YAGNI/KISS). Isso é limpeza do arquivo que estamos abrindo ("tocou = refatora"), não escopo novo.
5. **D1 × UC-2**: `failed` também precisa deixar a referência viva; a limpeza acontece só no `finished` nativo, um caminho único para sucesso e erro (SRP).
6. **Concorrência**: dois toggles rápidos durante TRANSCRIBING já são ignorados por `_on_toggle` (`tray.py:190`); a limpeza no `finished` nativo não abre janela nova, porque `start_engine`/`_on_toggle` só agem em estados definidos.
7. **Segurança/permissões**: nada novo — o socket do daemon segue `0600` (`voice_daemon.py:78`) e o `kill` do fallback continua restrito a PIDs do nosso próprio script.
8. **Rollback**: todas as mudanças são locais a processos do próprio app; nenhuma migração de dado, o SQLite do histórico não é tocado.
9. **i18n**: o projeto não tem camada de i18n (strings inglesas literais na UI) — manter o padrão existente, sem introduzir mecanismo novo (DRY/YAGNI).

### Round 3 — re-análise final

10. **D5 × D4**: `StderrTail` precisa funcionar para um `QProcess` que pode ser recriado a cada gravação → a instância é criada junto do processo e descartada com ele; nenhum estado global (SRP).
11. **D9 × threads**: `set_wakeup_fd` só pode ser chamado na main thread — é onde `main()` roda; o `QSocketNotifier` também vive lá. Sem conflito com a thread do `dbus-monitor` (que é Python puro, não Qt).
12. **Testabilidade**: D3 e D10 não são unitariamente testáveis em processo (dependem de fork real e de `make`) → viram TCs de execução real no Step 9, com evidência de sistema (`nvidia-smi`, conteúdo do `.desktop`). D1, D4, D5, D8 são testáveis com `pytest` + os fakes já existentes em `tests/test_engine_autostart.py`.
13. **Fronteiras (SRP)**: `recorder.py` = captura e conversão de áudio; `transcriber.py` = transporte para o daemon; `daemon.py` = ciclo de vida do motor; `tray.py` = estado e UI; `proc.py` = utilitário de processo (folha). Direção de dependências: `tray → {recorder, transcriber, daemon, shortcut, history}` e `{recorder, daemon} → proc`; nenhuma dependência reversa, nenhum ciclo.

✅ **Spec completo — 3 rounds, 11 decisões + 13 pontos de re-análise, zero ambiguidades**
