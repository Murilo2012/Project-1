# Revisão do dia

descricao: Fecha o dia — destila o que foi capturado em raw/ para a wiki/ e escreve o log.

## Quando usar
Fim do dia, quando o usuário pedir pra fechar o dia, ou quando o job agendado
`fechamento-noite` disparar.

## Procedimento

1. Liste as capturas de hoje: `vault_list` com seção `raw`, e olhe as de
   `raw/<hoje>/`.
2. Leia cada captura. Para cada uma, decida:
   - **Vale reter?** → destile pra `wiki/`, numa nota que já exista sobre o
     assunto (procure antes com `vault_search`) ou numa nota nova.
   - **Era momentâneo?** → deixe em `raw/`. Não apague nada.
3. Ao escrever na wiki, **una com o que já está lá** em vez de criar duplicata.
   Se `wiki/preferencias.md` já existe, anexe; não crie `preferencias-2.md`.
4. Use links `[[assim]]` pra conectar notas relacionadas. É o que faz o grafo
   do Obsidian funcionar.
5. Escreva o fechamento em `outputs/dia-<AAAA-MM-DD>.md`: o que aconteceu, o
   que ficou pendente, o que foi aprendido.
6. Fale **duas frases**: o que foi feito e o que ficou pendente. Só isso.

## Regras
- Nunca apague nada de `raw/`. É o registro cru, e registro cru não se edita.
- Se um dia não teve captura nenhuma, escreva o log mesmo assim, dizendo que
  não houve captura. O buraco no histórico é informação.
- Não destile pra wiki uma coisa que a wiki já sabe. Se não muda nada, não
  escreva.
