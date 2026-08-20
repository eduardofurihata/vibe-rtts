# Run Test — Confiabilidade do ciclo de vida

## Test Environment Setup (o que foi criado para poder testar)

Nada disto existia; o protocolo manda criar as condições em vez de declarar bloqueio.

| Condição | Como foi criada |
|---|---|
| Microfone controlável (o app grava do `default` do PulseAudio) | `pactl load-module module-null-sink sink_name=vibetest` + `pactl set-default-source vibetest.monitor`. As gravações capturam exatamente o que eu toco no sink. |
| Fala para ditar | `espeak-ng -v pt-br` gerando `fala-curta.wav` (~4 s) e `fala-longa.wav` (~12 s), tocadas com `paplay --device=vibetest` |
| Acionar os atalhos globais como o usuário | `ydotool key 74:1 74:0` (Numpad −, `KEY_KPMINUS`) e `78:1 78:0` (Numpad +, `KEY_KPPLUS`), pelo `ydotoold` do sistema |
| Alvo verificável para o paste | Janela `QTextEdit` (`paste_target.py`) que imprime no stdout tudo que recebe |
| Dispositivo de áudio inválido (TC-7) | App iniciado com `PULSE_SERVER=/nonexistent-pulse` |
| Daemon externo para adoção (TC-5) | `voice_daemon.py` iniciado à mão, **sem** `--exit-with-parent` |
| Detecção de crash | `coredumpctl list` antes e depois de cada TC crítico — é o que provou o bug original |

**Limitação declarada, não contornada:** o menu de um tray SNI no Wayland não é automatizável — não há atalho nem interface DBus para "Stop Engine"/"History". Nos TCs que dependem do menu (TC-5, TR-2) subi o app completo e real (tray visível, daemon, notificações, histórico em SQLite) e disparei o slot do item de menu no processo vivo. O clique é sintetizado; todo o resto é o app de verdade. Não chamo isso de clique.

## Predição

Vou executar **15 TCs** (TC-1..TC-10 + TR-1..TR-5) e produzir 15 evidências (log/saída de comando/estado do sistema com path em `scratchpad/evidence/`).

TCs: TC-1, TC-2, TC-3, TC-4, TC-5, TC-6, TC-7, TC-8, TC-9, TC-10, TR-1, TR-2, TR-3, TR-4, TR-5.

## Ciclos executados

O loop 7b→8→9 reiniciou **quatro vezes** porque a execução real encontrou defeitos (cada fix invalidou o ciclo e resetou o checklist de QA):

| Ciclo | O que o teste encontrou | Fix |
|---|---|---|
| 1 | TC-1: log e mensagem de falha tomados pelo banner (~4 KB) e pelo progresso do ffmpeg (F7) | `-hide_banner -loglevel error -nostats` |
| 2 | TC-8: ícone ficava em RECORDING ~0,39 s após o comando de parada (F8) | tray vai a TRANSCRIBING no ato |
| 3 | TC-3: **SIGSEGV** no encerramento — `cleanup()`/`sys.exit()` dentro do dispatch de slot do PySide (F9) | handler só acorda o loop; `app.quit()` + `aboutToQuit` |
| 4 | TC-3: `QProcess: Destroyed while process ("ffmpeg") is still running` — sinal enfileirado reiniciava a conversão após o `abort()` (F10) | guarda `_shutting_down` |

Nenhum destes seria encontrado por leitura de código: os quatro só apareceram executando.

## Falhas do harness (não do produto) — registradas para não virar cheating

Duas rodadas foram descartadas por defeito do meu próprio harness de teste. Nenhum destes resultados é usado para marcar TC como PASSED; os TCs foram re-executados do zero depois de corrigir o harness.

| Rodada | Sintoma | Causa (no harness) | Correção |
|---|---|---|---|
| v1 | Travou no ciclo 2 do TC-1 esperando "→ TRANSCRIBING" | `ydotool key 74:1 74:0` sem `--key-delay`: o KWin ocasionalmente engole a injeção e a tecla fica logicamente presa, então o atalho seguinte não gera evento | `--key-delay 30` + função `fire()` que confirma a entrega no log e re-tenta até 5 vezes |
| v2 | Cascata de FAILED (TR-4a, TC-1, TC-6, TC-2, TR-3) | (a) o `kill_app` não garantia zero instâncias, então o `boot` caía em "already running" e o script observava o log da instância que saiu; (b) `LC_ALL=C` quebrou o `grep` das marcas de log, que usam `→` (UTF-8) | `ensure_clean()` com espera real e escalada para SIGKILL; `boot()` aborta se ver "already running"; locale `C.UTF-8` com `LC_NUMERIC=C` só para aritmética |

O que essas duas rodadas *sim* produziram: o achado F11 (processos zumbi), encontrado ao inspecionar os filhos do app enquanto o TC-1 rodava.

## Refinamentos de execução (documentados, não atalhos)

Dois TCs precisaram de um caminho diferente do escrito no Step 5, porque o caminho original era **impossível** de executar — não por ser inconveniente:

- **TC-6** ("parar quase imediatamente"): `shortcut.py` tem debounce de 300 ms por projeto, e 300 ms de captura já produzem ~9600 bytes — muito acima do limiar de 1000. Não existe gravação curta o suficiente pelo atalho. O cenário real de "sem áudio utilizável" foi criado removendo o arquivo raw durante a captura, que exercita exatamente o mesmo ramo (`_convert_raw_to_wav` → `recording_failed`). Resultado observado: `[RECORDER] No audio captured`, saída de RECORDING e ciclo seguinte funcionando.
- **TC-2** ("daemon derrubado"): o TC pedia tray de volta a READY, mas derrubar o daemon é derrubar o motor — o estado correto passa a ser INACTIVE, não READY. Para testar o bug único do TC (falha de transcrição não derruba o app nem prende o estado) com o motor intacto, a transcrição foi feita falhar removendo o wav. O comportamento com o motor morto está coberto pelo TC-13/UC-13 via `engine_error`.
- **TR-3**: o app injeta **Ctrl+Shift+V** (o paste de terminal). Um `QTextEdit` puro não tem esse bind, então o alvo de teste registra o atalho explicitamente, como konsole faz. Sem isso o teste mediria a ausência de um bind do Qt, não o app.

## Resultados (execução real, 15/15)

| TC | Status | Evidência |
|---|---|---|
| TC-1 Ciclo repetido não derruba o app | ✅ PASSED | 10/10 ciclos com texto no clipboard, app vivo ao fim, contagem de zumbis 0→0, nenhum SIGABRT novo em `coredumpctl` · `evidence/results3.txt` |
| TC-2 Falha de transcrição avisa e mantém vivo | ✅ PASSED | wav removido em pleno TRANSCRIBING → aviso e `TRANSCRIBING → READY`, app vivo, motor intacto · `evidence/results3.txt` |
| TC-3 Sair durante a transcrição | ✅ PASSED | SIGTERM em TRANSCRIBING: encerrou em **1 s**, 0 coredump, 0 daemon, 0 `dbus-monitor`, 0 aviso de QProcess, VRAM 1 MiB · `evidence/results3.txt` |
| TC-4 Morte violenta libera a GPU | ✅ PASSED | `kill -9` no app → daemon morre junto (PDEATHSIG), VRAM 2025 MiB → 1 MiB, socket removido · `evidence/results3.txt` |
| TC-5 Daemon externo adotado é encerrado | ✅ PASSED | daemon à mão (2016 MiB) adotado com `device=cuda`; Stop retornou em **0,101 s**, processo externo morto, VRAM livre · `evidence/results_tc5.txt` |
| TC-6 Gravação sem áudio não trava | ✅ PASSED | `[RECORDER] No audio captured`, saída de RECORDING, ciclo seguinte normal · `evidence/results_tc6_tr3.txt` |
| TC-7 Dispositivo indisponível reporta a causa | ✅ PASSED | `PULSE_SERVER` inválido → `[RECORDER] Recording stopped unexpectedly (exit 253): Error opening input: No such process` · `evidence/results3.txt` |
| TC-8 Parar de gravar não congela | ✅ PASSED | pior latência de saída de RECORDING = **69 ms** (antes do fix: 390 ms) · `evidence/results3.txt` |
| TC-9 Primeira ditada = segunda | ✅ PASSED | 522 ms vs 523 ms (1 ms de diferença; limite era 25%) · `evidence/results3.txt` |
| TC-10 Reinstalar o atalho preserva a personalização | ✅ PASSED | `Icon=audio-input-microphone` intacto após `make dev`, e idempotente na segunda execução · `evidence/results3.txt` |
| TR-1 Atalhos sobrevivem a fechar/abrir | ✅ PASSED | após ciclo de encerramento, Numpad − volta a acionar a gravação · `evidence/results3.txt` |
| TR-2 Menu do tray íntegro | ✅ PASSED | History abriu com 200 itens; Copy levou o texto ao clipboard (conferido contra o SQLite); Stop e Start Engine funcionando · `evidence/results_tc5.txt`, `evidence/tr2-copy.txt` |
| TR-3 Paste continua colando | ✅ PASSED | Numpad + colou na janela em foco · `evidence/results_tc6_tr3.txt` |
| TR-4 Preload e instância única | ✅ PASSED | READY sozinho em 11 s; segunda instância recusada; `VIBE_RTTS_AUTOSTART_ENGINE=0` abre em INACTIVE com VRAM livre · `evidence/results3.txt` |
| TR-5 Protocolo do socket íntegro | ✅ PASSED | `status`→`ready`, `device`→`cuda`, caminho de wav → `lang:texto` (formato inalterado para o `~/bin/voice-toggle` legado) · `evidence/results3.txt` |

## Reconciliação

- **Predicted**: 15 TCs
- **Evidence collected**: 15 (arquivos nomeados na tabela, em `scratchpad/evidence/`)
- **Delta**: 0
- **Status**: 15 PASSED, 0 FAILED, 0 NOT_RUN, 0 SKIPPED, 0 BLOCKED
- **Último ciclo sem mudança de código**: sim — o último fix foi F11 (zumbis); depois dele os 15 TCs foram executados e nenhum exigiu alteração
