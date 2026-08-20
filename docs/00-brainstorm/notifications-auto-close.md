# Notifications — auto-close applies to errors too

**Data:** 2026-04-21

## Decisão

Todas as notificações do tray (sucesso **e** erro) devem fechar automaticamente após o timeout em `msecs`. Não usar `QSystemTrayIcon.MessageIcon.Critical`.

- Sucesso / status normal → `MessageIcon.Information`
- Erro → `MessageIcon.Warning`
- `MessageIcon.Critical` → reservado para casos que genuinamente exigem dismissal manual (hoje: nenhum)

## Contexto do problema

Antes:

- `_on_transcription_done` → `Information`, 3000 ms → fechava sozinha ✅
- `_on_engine_error` → `Critical`, 5000 ms → **não** fechava sozinha ❌
- `_on_transcription_error` → `Critical`, 3000 ms → **não** fechava sozinha ❌

Usuário reportou: "Quando é sucesso, fecha sozinha depois de alguns segundos. Quando falha, não fecha por conta própria. Quero o mesmo comportamento para falha."

## Por quê `Critical` não fecha

Em daemons de notificação compatíveis com a spec do freedesktop (KDE Plasma incluído), urgency `Critical` é **sticky** por design — o campo `expire_timeout` é tratado apenas como dica e é ignorado quando urgency é Critical. É uma decisão de UX do próprio spec: erros críticos devem exigir atenção até o usuário dispensar.

Como o Qt mapeia `MessageIcon.Critical` para urgency crítica via `org.freedesktop.Notifications`, passar `3000` ou `5000` ms com Critical não tem efeito.

## Implementação

- `vibe_rtts/tray.py:207` (`_on_engine_error`): `Critical` → `Warning`
- `vibe_rtts/tray.py:238` (`_on_transcription_error`): `Critical` → `Warning`

## Regra para novas notificações

Ao adicionar `self.showMessage(...)` em qualquer lugar do app:

- Se for erro que deve sumir depois de alguns segundos → `Warning`
- Se for status informativo → `Information`
- Se precisar que o usuário leia e dispense manualmente → `Critical` (e então o timeout é ignorado; não passe número menor esperando que funcione)
