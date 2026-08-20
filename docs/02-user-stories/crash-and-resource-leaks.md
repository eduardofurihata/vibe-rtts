# Confiabilidade do ciclo de vida — User Stories

Personas do Step 1: **Usuário do app** (dono da máquina, usa por voz todo dia), **Outros jobs de GPU** (representados pelo mesmo dono da máquina quando roda outra carga na 3060), **Mantenedor** (quem lê o log e corrige).

- **US-1** — Como usuário do app, quero que ele continue vivo depois de transcrever, para não perder o atalho e a ferramenta no meio do trabalho.
- **US-2** — Como usuário do app, quero que a VRAM e os processos auxiliares sejam liberados quando o app deixa de existir, para a GPU ficar disponível sem eu ter que caçar processo à mão.
- **US-3** — Como usuário do app, quero sair do estado de gravação mesmo quando a captura falha, para poder tentar de novo sem reiniciar o app.
- **US-4** — Como usuário do app, quero saber por que a captura ou a transcrição falhou, para corrigir a causa (por exemplo o fone Bluetooth que virou o dispositivo padrão).
- **US-5** — Como usuário do app, quero que a interface responda na hora ao parar de gravar, para não achar que travou.
- **US-6** — Como usuário do app, quero que "pronto" signifique pronto de verdade, para a primeira ditada do dia não ser mais lenta que as outras.
- **US-7** — Como usuário do app, quero que reinstalar o atalho de menu não apague a personalização que eu fiz nele, para não ter que refazer a configuração.
- **US-8** — Como mantenedor, quero que toda falha do motor apareça uma única vez e com a causa no log, para diagnosticar sem adivinhar.
