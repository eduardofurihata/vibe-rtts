# Confiabilidade do ciclo de vida (crash e vazamento de recursos)

## Problema

O vibe-rtts não é confiável: ele **crasha durante o uso normal** e, quando falha, **deixa recursos presos e o estado travado** — sem dizer ao usuário o que aconteceu.

## Contexto

O app é um tray de voz-para-texto de uso diário, com o modelo `large-v3` pré-carregado desde `a72dde0`. Quatro falhas distintas convergem no mesmo problema — o usuário perde a ferramenta no meio do trabalho e ainda paga o preço em VRAM:

- **Crash confirmado:** coredump `SIGABRT` (PID 1320313, 2026-08-20 18:20:30) imediatamente após uma transcrição bem-sucedida. `transcriber.py:12` declara `finished = Signal(str, str)`, sombreando o sinal nativo do `QThread`; a referência do worker é solta (`tray.py:235`, `tray.py:242`) com o thread ainda vivo, e o destrutor do `QThread` roda em execução → `qFatal`.
- **Recursos presos após a morte do app:** o daemon (2016 MiB de VRAM numa RTX 3060 de 6 GB compartilhada) e o `dbus-monitor` sobrevivem; os atalhos globais ficam registrados no kglobalaccel, então Numpad −/+ param de funcionar como teclas normais e como atalho.
- **Estado travado:** se a captura de áudio não produz arquivo (ffmpeg falha ao abrir o `default` do PulseAudio — cenário real ao trocar de fone Bluetooth), `recorder.py` não emite nada; o tray fica preso em RECORDING e o toggle vira inerte, sem saída a não ser reiniciar o app.
- **Diagnóstico impossível:** o stderr do ffmpeg vai para `/dev/null` (`recorder.py:33`) e a UI congela até 8 s em `waitForFinished` na thread da GUI, o que o usuário lê como "travou".

## Afetados

- **Usuário do app (dono da máquina)** — perde a transcrição em curso, perde os atalhos, fica sem saber por que parou, e precisa caçar processos órfãos à mão para recuperar VRAM.
- **Outros jobs de GPU na mesma máquina** (whisper one-shot, vibe-rtts em nova sessão) — ficam sem os 2 GB que o daemon órfão retém.
- **Quem mantém o código** — o crash é silencioso no log padrão e o estado travado não tem instrumentação.
