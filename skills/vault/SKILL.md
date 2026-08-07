# Vault

descricao: Como usar a memória de longo prazo — o que gravar, onde, e quando procurar.

## A regra
Se não está no vault, não aconteceu. Sua memória de conversa some quando a
janela fecha; o vault é o que sobrevive.

## Onde vai cada coisa

| Tipo | Pasta | Exemplo |
|---|---|---|
| Captura crua, com data | `raw/` | "ele mencionou que a reunião mudou pra quinta" |
| Conhecimento que vale reter | `wiki/` | "prefere respostas curtas", "trabalha com vôlei" |
| Coisa que você entregou | `outputs/` | briefings, planos, relatórios |

## Quando gravar sem pedirem

Grave na `wiki/` **por conta própria** quando o usuário:
- Contar uma preferência ("prefiro que você não fale tanto")
- Tomar uma decisão que vale lembrar ("vou usar Postgres nesse projeto")
- Dizer um fato sobre a vida dele que vai importar depois
- Corrigir você sobre algo — isso é o mais importante de todos. Se ele te
  corrigiu, você errou por falta de contexto, e o contexto agora existe.

Não anuncie que gravou. Só grave e siga a conversa.

## Quando procurar

Chame `vault_search` **antes** de dizer "não sei" sobre qualquer coisa
relacionada ao usuário, aos projetos dele ou a conversas passadas. É barato e
evita você parecer amnésico sobre algo que já te contaram.

## Como escrever

- Comece toda nota com `# Título`.
- Use `[[links]]` pra conectar notas. `[[projetos]]`, `[[preferencias]]`.
- Prefira anexar (`append: true`) a sobrescrever. Sobrescrever apaga contexto.
- Uma nota por assunto, não uma por conversa. `wiki/preferencias.md` cresce ao
  longo do tempo; não crie `preferencias-janeiro.md`.
- Escreva pra você mesmo daqui a seis meses, não pra impressionar ninguém.
