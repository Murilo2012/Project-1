# Briefing da manhã

descricao: Monta o resumo da manhã — agenda, pendências e o que ficou aberto ontem.

## Quando usar
Quando o usuário pedir o briefing, perguntar "como tá meu dia", ou quando o job
agendado `briefing-manha` disparar.

## Procedimento

1. Leia o log de ontem em `raw/<data-de-ontem>/_log.md`. Se não existir, siga.
2. Rode `vault_search` por "pendente", "amanhã" e "fazer" pra achar o que ficou
   em aberto.
3. Leia `wiki/projetos.md` se existir, pra saber o que está em andamento.
4. Chame `system_status` — se o disco estiver acima de 90% ou a memória acima
   de 85%, isso entra no briefing.
5. Monte o briefing com estas seções, nesta ordem:
   - **Aberto de ontem** — no máximo 3 itens
   - **Foco de hoje** — no máximo 3 itens, os mais importantes
   - **Alertas** — só se houver algo do passo 4
6. Salve em `outputs/briefing-<AAAA-MM-DD>.md` com `vault_write`.
7. **Fale só o essencial**: no máximo 4 frases. O documento tem o detalhe, a
   fala tem o que importa. Não leia o arquivo em voz alta.

## Regras
- Se não houver nada em aberto, diga isso em uma frase em vez de inventar
  tarefa. Um briefing honesto e curto vale mais que um cheio de enrolação.
- Nunca invente compromisso. Se você não tem acesso a um calendário, diga que
  não tem, uma vez, e siga.
