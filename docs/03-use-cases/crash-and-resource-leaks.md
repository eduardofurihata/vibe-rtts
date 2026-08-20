# Confiabilidade do ciclo de vida — Use Cases

## Tabela de assinaturas (única)

| UC | Story | Ator | Fluxo | Estado inicial |
|----|-------|------|-------|----------------|
| UC-1 | US-1 | Usuário | happy | READY |
| UC-2 | US-1 | Usuário | erro (falha na transcrição) | TRANSCRIBING |
| UC-3 | US-1 | Usuário | alternativo (sai durante a transcrição) | TRANSCRIBING |
| UC-4 | US-2 | Usuário / outra carga de GPU | erro (app morre sem cleanup) | READY |
| UC-5 | US-2 | Usuário | happy (fecha pelo menu) | READY |
| UC-6 | US-2 | Usuário | alternativo (daemon iniciado à mão, adotado) | READY adotado |
| UC-7 | US-3 | Usuário | erro (captura sem áudio) | RECORDING |
| UC-8 | US-3 | Usuário | erro (ffmpeg nem inicia) | READY → RECORDING |
| UC-9 | US-4 | Usuário | erro (dispositivo de áudio indisponível) | RECORDING |
| UC-10 | US-5 | Usuário | happy (para de gravar) | RECORDING |
| UC-11 | US-6 | Usuário | happy (primeira ditada após abrir) | READY |
| UC-12 | US-7 | Usuário | happy (reinstala o atalho de menu) | app instalado, `.desktop` personalizado |
| UC-13 | US-8 | Mantenedor | erro (motor falha no preload) | LOADING |

## UC-1 — Transcrever e continuar vivo
- **Ator**: Usuário
- **Precondição**: engine READY, modelo na GPU
- **Fluxo**: 1) aciona o atalho e fala; 2) aciona de novo para parar; 3) o texto vai para o clipboard e para o histórico; 4) repete o ciclo várias vezes seguidas
- **Resultado**: tray volta a READY após cada ciclo e o processo do app segue vivo indefinidamente

## UC-2 — Transcrição falha, app sobrevive
- **Ator**: Usuário
- **Precondição**: TRANSCRIBING, daemon indisponível ou devolvendo erro
- **Fluxo**: 1) o worker recebe erro/socket fechado; 2) o app avisa; 3) o usuário tenta de novo
- **Resultado**: aviso com a causa, tray de volta a READY, processo vivo

## UC-3 — Sair durante a transcrição
- **Ator**: Usuário
- **Precondição**: TRANSCRIBING
- **Fluxo**: 1) escolhe Quit no menu (ou o sistema encerra a sessão) enquanto o worker roda
- **Resultado**: o app aguarda o worker terminar (limite curto) e encerra sem abortar; atalhos desregistrados e daemon parado

## UC-4 — App morre sem cleanup
- **Ator**: Usuário / outra carga de GPU
- **Precondição**: READY, daemon iniciado pelo app
- **Fluxo**: 1) o app morre sem executar cleanup (SIGKILL, crash, OOM do sistema)
- **Resultado**: o daemon encerra sozinho em segundos e a VRAM volta a ficar livre; nenhum processo auxiliar sobrevive

## UC-5 — Fechar pelo menu
- **Ator**: Usuário
- **Precondição**: READY
- **Fluxo**: 1) escolhe Quit
- **Resultado**: daemon parado, VRAM livre, `dbus-monitor` encerrado, atalhos devolvidos ao comportamento normal

## UC-6 — Daemon adotado
- **Ator**: Usuário
- **Precondição**: daemon iniciado fora do app (linha de comando), app abre e adota
- **Fluxo**: 1) usuário escolhe Stop Engine
- **Resultado**: daemon externo encerrado, VRAM livre; se for um daemon que o app não reconhece como seu e não obedece, o app avisa em vez de matar às cegas

## UC-7 — Captura sem áudio
- **Ator**: Usuário
- **Precondição**: RECORDING
- **Fluxo**: 1) para a gravação; 2) a captura não produziu áudio utilizável (curta demais ou vazia)
- **Resultado**: aviso "nenhum áudio capturado", tray de volta a READY, próximo toggle funciona

## UC-8 — ffmpeg não inicia
- **Ator**: Usuário
- **Precondição**: READY, binário/serviço de áudio ausente
- **Fluxo**: 1) aciona o atalho para gravar; 2) o processo de captura falha ao iniciar
- **Resultado**: aviso imediato, tray permanece/volta a READY — nunca entra em RECORDING sem captura viva

## UC-9 — Dispositivo de áudio indisponível
- **Ator**: Usuário
- **Precondição**: RECORDING iniciado, dispositivo padrão mudou (fone Bluetooth conectou/desconectou)
- **Fluxo**: 1) a captura morre no meio; 2) o usuário para a gravação
- **Resultado**: aviso contendo a mensagem real do ffmpeg, tray de volta a READY

## UC-10 — Parar de gravar sem congelar
- **Ator**: Usuário
- **Precondição**: RECORDING com áudio válido
- **Fluxo**: 1) aciona o atalho para parar
- **Resultado**: a UI responde imediatamente (ícone muda sem espera perceptível) e a transcrição começa em seguida

## UC-11 — Primeira ditada após abrir
- **Ator**: Usuário
- **Precondição**: app aberto, preload concluído (READY)
- **Fluxo**: 1) grava e transcreve pela primeira vez na sessão
- **Resultado**: latência equivalente à segunda transcrição (sem custo escondido de inicialização)

## UC-12 — Reinstalar o atalho de menu
- **Ator**: Usuário
- **Precondição**: `.desktop` instalado e personalizado (ícone do tema)
- **Fluxo**: 1) roda o alvo de desenvolvimento que (re)instala o atalho
- **Resultado**: o atalho continua com a personalização; rodar de novo não muda mais nada (idempotente)

## UC-13 — Motor falha no preload
- **Ator**: Mantenedor
- **Precondição**: LOADING, GPU sem memória
- **Fluxo**: 1) o daemon morre ao carregar; 2) o mantenedor lê o log
- **Resultado**: uma única mensagem de falha com a causa (nenhum evento de "parada normal" competindo), tray em INACTIVE

## Verificação de Realidade

Cada passo do happy path das stories mapeado ao código atual (🔨 = lacuna a construir):

| Passo | Onde está hoje | Situação |
|-------|----------------|----------|
| Atalho global dispara toggle | `vibe_rtts/shortcut.py:109-170` | ✅ funciona |
| Estado do tray e ícones | `vibe_rtts/tray.py:108-147` (`AppState`) | ✅ funciona — reutilizar, não recriar |
| Início da captura | `vibe_rtts/recorder.py:16-36` | 🔨 sem confirmação de início nem stderr |
| Fim da captura → wav | `vibe_rtts/recorder.py:37-49` | 🔨 bloqueia a GUI e não sinaliza falha |
| Transcrição em thread | `vibe_rtts/transcriber.py:11-20` | 🔨 sinal `finished` sombreia o do `QThread` |
| Descarte do worker | `vibe_rtts/tray.py:235,242` | 🔨 solta a referência com o thread vivo (causa do abort) |
| Clipboard + histórico | `vibe_rtts/tray.py:222-233`, `history.py:30-38` | ✅ funciona |
| Preload / READY | `vibe_rtts/app.py:51-57`, `daemon.py:33-67` | ✅ funciona (de `a72dde0`) |
| Warmup do modelo | `daemon/voice_daemon.py:52-71` | 🔨 usa `beam_size=1, vad_filter=False`; produção usa 5 + VAD |
| Parada do daemon próprio | `vibe_rtts/daemon.py:87-110` + `:132-146` | 🔨 emite `engine_stopped` duas vezes |
| Parada de daemon adotado | `vibe_rtts/daemon.py:171-203` | ✅ encerra e libera (de `a72dde0`); ⚠️ bloqueia até ~7 s |
| Morte do app sem cleanup | — | 🔨 não existe nada que derrube o daemon |
| Encerramento do `dbus-monitor` | `vibe_rtts/shortcut.py:172-192` | 🔨 `cleanup()` só desregistra teclas |
| Sinais POSIX no loop Qt | `vibe_rtts/app.py:82-88` | 🔨 resolve por polling de 200 ms |
| Instalação do `.desktop` | `Makefile:12-16` | 🔨 sobrescreve a personalização |
