# Plano de Implementação — Confiabilidade do ciclo de vida

## 1. Contexto Consolidado

**Problema** (01): o app crasha no uso normal e, ao falhar, deixa recursos presos e o estado travado, sem informar a causa.
**Stories** (02): 8 — não crashar (US-1), liberar recursos (US-2), sair do estado de gravação (US-3), saber a causa (US-4), UI responsiva (US-5), READY que é READY (US-6), não perder a personalização do atalho (US-7), falha única e com causa no log (US-8).
**Use Cases** (03): 13, com a Verificação de Realidade apontando 10 lacunas no código atual.
**Spec** (04): 11 decisões (D1-D11) em 3 rounds. Escopo desktop Linux/Wayland; sem superfície mobile/web.

## 2. Código Existente Relevante

| Arquivo | O que faz hoje | Impacto |
|---|---|---|
| `vibe_rtts/transcriber.py` | `QThread` que fala com o socket do daemon; declara `finished`/`error` | **Sombreia `QThread.finished`** — origem do abort (D1) |
| `vibe_rtts/tray.py` | Estado (`AppState`) + UI + orquestração dos componentes | Solta a referência do worker cedo (`:235`, `:242`); precisa tratar falha de gravação (D1, D2, D4) |
| `vibe_rtts/recorder.py` | Captura via ffmpeg e conversão para wav, ambas bloqueantes | Congela a GUI e engole falhas (D4, D5) |
| `vibe_rtts/daemon.py` | Ciclo de vida do motor, assíncrono por sinais de `QProcess`; buffer manual de stderr (`:26,127-130`) | Fonte do padrão a extrair (D5) + emissão dupla (D8) + orçamento de espera (D11) + passar a flag (D3) |
| `vibe_rtts/shortcut.py` | Registra atalhos e escuta `dbus-monitor` numa thread | `Popen` sem dono (D6) |
| `vibe_rtts/app.py` | Wiring, single-instance, cleanup, sinais POSIX | Polling de 200 ms (D9) e cleanup que não espera o worker (D2) |
| `daemon/voice_daemon.py` | Servidor do modelo no socket; warmup de um passe | Warmup não espelha produção (D7); sem amarra de vida ao pai (D3) |
| `Makefile` | `dev` reescreve o `.desktop` | Destrói a personalização (D10) |

**i18n**: grep por `i18n|gettext|locale|translations|babel` em `vibe_rtts/`, `daemon/`, `Makefile`, `requirements.txt` → **nada**. O projeto não tem camada de i18n; strings literais em inglês são o padrão vigente e serão mantidas (DRY com o padrão existente).

**Consistência de UI**: o único canal de feedback do app é `QSystemTrayIcon.showMessage` (`tray.py:208,231,239`) com `MessageIcon.Warning` para falha e `Information` para sucesso — decidido em `docs/00-brainstorm/notifications-auto-close.md` porque `Critical` é sticky e ignora `msecs`. As novas mensagens de falha de gravação seguem exatamente esse padrão: `Warning`, 3-5 s, texto curto com a causa. Nenhum estilo novo.

**Referência big apps (UX)**: apps de ditado líderes (Wispr Flow, Superwhisper) nunca deixam o botão preso em "gravando": falha de microfone volta ao repouso com aviso acionável. É o comportamento que D4 implementa.

## 3. Estratégia de Implementação

Ordem: T1 (coletor) → T7 (daemon: flag + warmup) → T2 (recorder assíncrono) e T3 (daemon manager) → T4 (sinais do worker) → T5 (tray) → T6 (app) → T8 (Makefile) → T9 (testes) → T10 (regressão).

**Responsabilidade por arquivo (SRP), uma frase cada:**
- `vibe_rtts/proc.py` (novo) — guarda as últimas linhas de stderr de um `QProcess` e as devolve como texto.
- `vibe_rtts/recorder.py` — captura áudio e entrega um wav ou uma falha explicada, sem bloquear a GUI.
- `vibe_rtts/transcriber.py` — leva um wav ao daemon e devolve texto ou erro.
- `vibe_rtts/daemon.py` — administra o ciclo de vida do motor de transcrição.
- `vibe_rtts/tray.py` — mantém o estado visível e conecta as peças.
- `vibe_rtts/app.py` — monta o app e garante encerramento limpo.
- `daemon/voice_daemon.py` — serve o modelo pronto no socket, e só enquanto o dono existir.
- `Makefile` — instala e roda o app de forma idempotente.

**Abordagem por task:**

- **T1** `StderrTail(process, keep=5)`: conecta `readyReadStandardError`, ecoa no log com prefixo e mantém uma lista curta; `text()` devolve o join. Sem estado global, uma instância por processo.
- **T7** No daemon: `--exit-with-parent` chama `ctypes.CDLL("libc.so.6").prctl(1, SIGTERM)` (`PR_SET_PDEATHSIG=1`) e, contra a corrida, sai se `os.getppid() == 1`. Warmup em dois passes: `vad_filter=True` (materializa o Silero/ONNX) e `beam_size=args.beam_size, vad_filter=False` (encoder/decoder). Falha de warmup em CUDA continua fatal.
- **T2** `RecordingEngine` vira máquina de estados por sinais: `start_recording` conecta `errorOccurred`→`recording_failed` e guarda o `StderrTail`; `stop_recording` chama `terminate()` e arma um `QTimer` de 3 s para `kill()`; o `finished` do ffmpeg dispara `_convert()`, cujo `finished` emite `recording_stopped(wav)` ou `recording_failed(motivo)`. Remove `recording_started` (F2).
- **T3** `DaemonManager` passa a usar `StderrTail`, ganha `--exit-with-parent` nos argumentos, deixa de reemitir `engine_stopped` quando `_on_process_finished` já emitiu, e reduz o orçamento de espera do stop adotado.
- **T4/T5** `transcribed`/`failed` no worker; no tray, `_on_worker_finished` (ligado ao `finished` nativo) é o **único** lugar que solta a referência; `_on_recording_failed` mostra o toast e volta a READY; Quit aguarda o worker (`wait(3000)`).
- **T6** `socket.socketpair()` + `signal.set_wakeup_fd` + `QSocketNotifier` no lugar do `QTimer`; `cleanup()` aguarda o worker antes de parar o daemon.
- **T11** `ShortcutHandler` guarda o `Popen` do `dbus-monitor` e o encerra no `cleanup()` (desvio registrado: task ausente no Step 6, D6 já estava no spec).
- **T8** `ICON := audio-input-microphone` no Makefile.

## 3.1 Reúso antes de criar (DRY)

Grep executado em `vibe_rtts/`, `daemon/`, `tests/` (resultados no chat do Step 7a):

| Preciso de | Já existe? | Decisão |
|---|---|---|
| Coletar stderr de processo | `daemon.py:26,127-130` (buffer manual) | **Extrair** para `proc.py` e reutilizar nos dois consumidores (daemon + recorder) |
| Falar com o socket do daemon | `daemon.py:153-166` (`_ask`) | Reutilizar como está — nenhuma nova rotina de socket |
| Estado da UI | `tray.py:108-147` (`AppState` + `_update_state`) | Reutilizar; **não** criar estado novo (ver § 3.2) |
| Notificar o usuário | `tray.py:208,231,239` (`showMessage` + `Warning`) | Reutilizar o padrão, mesmos ícone e duração |
| Timer de guarda | `QTimer.singleShot` usado em `app.py:56`, `history_window.py:49` | Reutilizar o mesmo mecanismo para o kill do ffmpeg |
| Daemon fake para teste | `tests/test_engine_autostart.py` (`FakeDaemon`) | Reutilizar/estender — não criar outro fake |
| Camada de i18n | não existe | Manter literais (padrão do projeto) |
| Amarrar filho à vida do pai | não existe no projeto | **Criar** (T7) — `QProcess.setChildProcessModifier` não existe no PySide6 6.10.2 (verificado), e nada equivalente existe no repo |

## 3.2 O que NÃO vamos construir (YAGNI)

- **Estado `STARTING` no `AppState`** — considerado para UC-8; descartado: o rollback otimista via `recording_failed` cobre o caso sem um sexto estado.
- **Idle timeout que descarrega o modelo da VRAM** — nenhum UC pede; mudaria o significado de READY.
- **Unit systemd própria para o daemon** — resolveria UC-4, mas muda o modelo de deploy; `prctl` resolve dentro do processo.
- **Watchdog de `getppid()` por polling** — o kernel entrega o sinal; polling seria desperdício.
- **Retry automático de captura ou de preload** — nenhuma story pede; a decisão fica com o usuário.
- **Camada de i18n** — projeto não tem; introduzi-la aqui seria escopo inventado.
- **Abstração genérica de "processo externo gerenciado"** unificando daemon + ffmpeg + conversão — os dois ciclos de vida são diferentes (servidor longo vs. comando curto); só o **coletor de stderr** é genuinamente comum, e é o que será extraído.

## 4. Mapa de Test Cases → Código

| TC | Código que atende | Edge cases |
|---|---|---|
| TC-1 | `transcriber.py` (sinais), `tray.py` (`_on_worker_finished`) | ciclos consecutivos rápidos; worker que termina antes do slot rodar |
| TC-2 | `transcriber.py` (`failed`), `tray.py`, `daemon.py` (emissão única) | daemon morto no meio; resposta vazia |
| TC-3 | `app.py` (`set_wakeup_fd`, espera do worker), `shortcut.py` (`cleanup`), `daemon.py` (`stop`) | SIGTERM durante TRANSCRIBING; app ocioso |
| TC-4 | `voice_daemon.py` (`--exit-with-parent`), `daemon.py` (passa a flag) | pai morto antes do `prctl` (guarda `getppid()==1`) |
| TC-5 | `daemon.py` (`_kill_external_daemon`, orçamento) | daemon externo que ignora `shutdown` |
| TC-6 | `recorder.py` (`recording_failed` quando não há wav), `tray.py` | raw < 1000 bytes; stop chamado com processo já morto |
| TC-7 | `recorder.py` (`StderrTail` + `errorOccurred`), `proc.py` | ffmpeg ausente; device inválido; falha depois de iniciar |
| TC-8 | `recorder.py` (assíncrono) | ffmpeg que não responde ao `terminate` (guarda de 3 s) |
| TC-9 | `voice_daemon.py` (dois passes de warmup) | falha de warmup no VAD (não deve derrubar em CPU; fatal em CUDA) |
| TC-10 | `Makefile` | rodar duas vezes seguidas (idempotência) |

## 5. Riscos e Pontos de Atenção

- **`os._exit` no daemon**: o handler de `shutdown` já usa `os._exit(0)` porque roda em thread de atendimento; o caminho do `prctl` (SIGTERM) cai no mesmo handler — nada muda.
- **`set_wakeup_fd`**: só funciona na main thread e exige fd non-blocking; se levantar exceção em algum ambiente, cair para o comportamento anterior seria complexidade especulativa — em vez disso, falhar alto no desenvolvimento (o app é de uma plataforma só, e o TC-3 cobre).
- **Remoção de `recording_started`**: grep confirma zero consumidores (`app.py` conecta apenas `recording_stopped`).
- **Guarda de kill do ffmpeg**: `terminate()` no ffmpeg é o que fecha o arquivo raw corretamente; o `kill()` só entra se ele travar, com risco de raw truncado — que é exatamente o caminho de `recording_failed`.
- **Ordem T7 antes de T3**: a flag precisa existir no daemon antes de o manager passá-la, senão o daemon morre por argumento desconhecido.

## 6. Checklist de Implementação

- [x] T1 — `vibe_rtts/proc.py`
- [x] T7 — `daemon/voice_daemon.py` (flag + warmup)
- [x] T2 — `vibe_rtts/recorder.py`
- [x] T3 — `vibe_rtts/daemon.py`
- [x] T4 — `vibe_rtts/transcriber.py`
- [x] T5 — `vibe_rtts/tray.py`
- [x] T6 — `vibe_rtts/app.py`
- [x] T11 — `vibe_rtts/shortcut.py` (encerrar o `dbus-monitor`) — *acrescentada durante o 7b: o Step 6 não gerou task para D6*
- [x] T8 — `Makefile`
- [x] T9 — `tests/`
- [x] T10 — `docs/05-test-cases/` (regressão)
