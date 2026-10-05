# Confiabilidade do ciclo de vida — Test Cases

## Nota de complexidade: 10/10 → 10 TCs

Derivada dos Steps 3-4: 13 UCs (4 happy, 2 alternativos, 7 de erro) · 3 atores · 5 estados do `AppState` mais estados de processo (vivo, morto sem cleanup, externo adotado) · cross-cutting de ciclo de vida de thread, de processo filho e de recurso de GPU · 11 decisões de spec · raio de impacto em 8 arquivos. Teto do protocolo.

Plataforma é eixo de execução, não TC: escopo é desktop Linux/Wayland (Step 4), sem duplicação por plataforma.

### TC-1: Ciclo de ditado repetido não derruba o app
- Cobre: UC-1, UC-10, D1, D2 (parcial), D4
- Bug único: o app aborta ao descartar o worker de transcrição ainda em execução
- Pré-condição: app aberto em READY, modelo na GPU
- Passos: 1) gravar ~2 s e parar, repetir 10 ciclos seguidos sem pausa longa; 2) após cada ciclo, conferir o estado do tray; 3) ao fim, conferir `coredumpctl list` e se o processo do app segue vivo
- Resultado: 10 transcrições no clipboard/histórico, tray sempre de volta a READY, processo vivo, **nenhum novo SIGABRT de python** no coredumpctl
- Prova: log do app + `coredumpctl list` + `pgrep`

### TC-2: Falha de transcrição avisa e mantém o app vivo
- Cobre: UC-2, D1, D8
- Bug único: erro na transcrição derruba o app ou deixa o tray fora de READY
- Pré-condição: RECORDING com áudio válido; daemon derrubado antes de a transcrição concluir
- Passos: 1) iniciar gravação; 2) encerrar o daemon; 3) parar a gravação
- Resultado: notificação com a causa, tray de volta a READY, app vivo, uma única mensagem de falha no log
- Prova: log + notificação

### TC-3: Sair durante a transcrição encerra limpo
- Cobre: UC-3, UC-5, D2, D6, D9
- Bug único: encerrar durante a transcrição aborta o processo ou deixa órfãos
- Pré-condição: TRANSCRIBING (áudio longo, ~30 s)
- Passos: 1) parar a gravação de um áudio longo; 2) durante TRANSCRIBING, enviar SIGTERM ao app; 3) conferir processos e VRAM
- Resultado: encerra em <5 s sem abort, sem daemon vivo, sem `dbus-monitor` vivo, VRAM liberada, teclas do numpad devolvidas
- Prova: `pgrep`, `nvidia-smi`, `coredumpctl`

### TC-4: Morte violenta do app libera a GPU
- Cobre: UC-4, D3
- Bug único: daemon sobrevive ao app e retém VRAM indefinidamente
- Pré-condição: app em READY com daemon próprio (2 GB na GPU)
- Passos: 1) `kill -9` no app; 2) esperar até 10 s; 3) conferir daemon e VRAM
- Resultado: nenhum `voice_daemon.py` vivo, VRAM de volta a ~0, socket removido
- Prova: `pgrep` + `nvidia-smi` + `ls /tmp/voice-daemon.sock`

### TC-5: Daemon externo adotado é encerrado pelo Stop
- Cobre: UC-6, D3 (não afeta externo), D11
- Bug único: Stop Engine mostra INACTIVE enquanto o daemon externo continua com a VRAM
- Pré-condição: daemon iniciado à mão (sem `--exit-with-parent`), app aberto e adotando
- Passos: 1) subir o daemon manualmente; 2) abrir o app (adota, vai a READY); 3) Stop Engine; 4) medir o tempo de resposta da UI
- Resultado: processo externo encerrado, VRAM livre, UI responde em <2 s
- Prova: `pgrep` + `nvidia-smi` + log com timestamps

### TC-6: Gravação sem áudio não trava o estado
- Cobre: UC-7, D4, D5
- Bug único: tray fica preso em RECORDING e o toggle vira inerte
- Pré-condição: READY
- Passos: 1) acionar o toggle e parar quase imediatamente (áudio insuficiente); 2) observar o tray; 3) acionar o toggle novamente e fazer uma gravação normal
- Resultado: notificação de "nenhum áudio capturado", tray de volta a READY, e a gravação seguinte funciona normalmente
- Prova: log + notificação

### TC-7: Dispositivo de áudio indisponível reporta a causa real
- Cobre: UC-8, UC-9, D4, D5
- Bug único: falha de captura é silenciosa — sem causa e sem saída do estado de gravação
- Pré-condição: READY, com o dispositivo de captura inválido (`PULSE_SERVER`/device inexistente)
- Passos: 1) acionar o toggle para gravar; 2) parar; 3) ler a notificação e o log
- Resultado: mensagem contém texto do ffmpeg (não genérica), tray em READY, próximo toggle funciona
- Prova: log com o stderr do ffmpeg + notificação

### TC-8: Parar de gravar não congela a interface
- Cobre: UC-10, D4
- Bug único: a UI trava enquanto o ffmpeg é finalizado e o wav é convertido
- Pré-condição: RECORDING com ~10 s de áudio
- Passos: 1) parar a gravação; 2) medir o tempo entre o comando e a mudança de ícone/estado no log; 3) interagir com o menu do tray imediatamente após parar
- Resultado: mudança de estado imediata (<100 ms no log) e menu responsivo — nenhum `waitForFinished` na thread da GUI
- Prova: log com timestamps + interação com o menu

### TC-9: Primeira ditada tem a mesma latência da segunda
- Cobre: UC-11, D7
- Bug único: o custo do VAD/beam real é pago na primeira transcrição do usuário
- Pré-condição: app recém-aberto (preload concluído), daemon sem nenhuma transcrição
- Passos: 1) conferir no log os dois passes de warmup; 2) transcrever o mesmo áudio duas vezes seguidas; 3) comparar os tempos
- Resultado: log mostra warmup de VAD e de beam; primeira e segunda transcrição com tempos equivalentes (diferença < 25%)
- Prova: log + medição das duas chamadas

### TC-10: Reinstalar o atalho de menu preserva a personalização
- Cobre: UC-12, D10
- Bug único: o alvo de desenvolvimento sobrescreve o `.desktop` e apaga o ícone escolhido
- Pré-condição: `.desktop` instalado com `Icon=audio-input-microphone`
- Passos: 1) guardar cópia do `.desktop`; 2) rodar o alvo de instalação do atalho; 3) comparar o antes e o depois; 4) rodar de novo e comparar
- Resultado: `Icon=audio-input-microphone` preservado, e a segunda execução não muda mais nada (idempotente)
- Prova: `diff` do `.desktop`

## Rastreabilidade — cobertura completa

| UC / Decisão | Coberto por |
|---|---|
| UC-1 | TC-1 |
| UC-2 | TC-2 |
| UC-3 | TC-3 |
| UC-4 | TC-4 |
| UC-5 | TC-3 |
| UC-6 | TC-5 |
| UC-7 | TC-6 |
| UC-8 | TC-7 |
| UC-9 | TC-7 |
| UC-10 | TC-1, TC-8 |
| UC-11 | TC-9 |
| UC-12 | TC-10 |
| UC-13 | TC-2 (mensagem única de falha) |
| D1 | TC-1, TC-2 |
| D2 | TC-3 |
| D3 | TC-4, TC-5 |
| D4 | TC-6, TC-7, TC-8 |
| D5 | TC-7 |
| D6 | TC-3 |
| D7 | TC-9 |
| D8 | TC-2 |
| D9 | TC-3 |
| D10 | TC-10 |
| D11 | TC-5 |

## TCs de Regressão (raio de impacto do 7b)

Arquivos tocados e seus dependentes (grep no 7b): `proc.py`→(daemon, recorder) · `recorder.py`→(app) · `daemon.py`→(app) · `transcriber.py`→(tray) · `tray.py`→(app) · `app.py`→(`__main__`) · `shortcut.py`→(app) · `voice_daemon.py`→(daemon manager + o script legado `~/bin/voice-toggle`, fora do repo).

### TR-1: Atalhos globais sobrevivem a fechar e abrir
- Motivo: `shortcut.py` ganhou encerramento do listener no `cleanup()` — se o cleanup passar a derrubar algo demais, os atalhos param de funcionar no próximo start
- Passos: 1) fechar o app pelo menu; 2) conferir que Numpad − volta a digitar "−"; 3) abrir de novo; 4) acionar Ctrl+Alt+Space e Numpad −
- Resultado: os dois atalhos voltam a acionar a gravação após o reinício

### TR-2: Menu do tray íntegro
- Motivo: `tray.py` foi reescrito em torno do worker; History e Start/Stop Engine estão no mesmo arquivo e não eram alvo
- Passos: 1) abrir History pelo menu; 2) usar o botão Copy de um item; 3) Stop Engine; 4) Start Engine
- Resultado: janela abre com o histórico, Copy vira "Copied!", e o engine desliga/liga com o ícone acompanhando

### TR-3: Paste (Numpad +) continua colando
- Motivo: `tray.py` e `shortcut.py` tocados; o paste depende dos dois
- Passos: 1) transcrever algo; 2) focar um editor de texto; 3) acionar Numpad +
- Resultado: o texto é colado na janela em foco

### TR-4: Preload e instância única seguem íntegros
- Motivo: `app.py` mudou a mecânica de sinais e o cleanup — é o mesmo arquivo do preload entregue em `a72dde0`
- Passos: 1) abrir o app e aguardar; 2) tentar abrir uma segunda instância; 3) `VIBE_RTTS_AUTOSTART_ENGINE=0` numa terceira tentativa (após fechar)
- Resultado: primeira instância chega a READY sozinha; a segunda sai avisando que já está rodando; com a variável em 0 abre em INACTIVE

### TR-5: Protocolo do socket íntegro para clientes externos
- Motivo: `voice_daemon.py` mudou (flag nova e warmup), e há um cliente fora do repo (`~/bin/voice-toggle`) que faz poll de `status` esperando exatamente `ready`
- Passos: 1) com o engine ativo, enviar `status`, `device` e um caminho de wav pelo socket; 2) conferir as respostas
- Resultado: `ready`, `cuda` e `lang:texto` — sem mudança de formato para quem já consumia
