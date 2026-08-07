# Controle do PC

descricao: Como operar o Windows com segurança — abrir, fechar, achar e consertar coisas.

## Quando usar
Sempre que a tarefa envolver mexer no computador de verdade, e não só conversar.

## A ordem que funciona

1. **Olhe antes de agir.** Se a tarefa depende do que está na tela, chame
   `look_at_screen` primeiro. Adivinhar o estado da tela é como errado nasce.
2. **Foque antes de digitar.** `focus_window` antes de `type_text` ou
   `press_keys` — senão o texto vai parar na janela errada, e às vezes na
   janela errada com consequência.
3. **Confirme depois de agir.** Depois de uma ação com efeito visual, olhe a
   tela de novo pra ver se funcionou. Não diga "abri o Spotify" sem ter visto
   o Spotify.

## Escolha da ferramenta

| Tarefa | Ferramenta |
|---|---|
| Abrir programa, arquivo, pasta, site | `open_app` — não `run_shell` |
| Saber o que está aberto | `list_windows` ou `list_processes` |
| Achar um arquivo pelo nome | `search_files` — não `run_shell` com dir |
| Ler um arquivo de texto | `read_file` |
| Consultar estado do sistema | `system_status` |
| Qualquer coisa sem ferramenta própria | `run_shell` |

`run_shell` é o último recurso, não o primeiro. As ferramentas específicas
devolvem resultado limpo e passam pelo gate certo.

## Segurança

- Ações destrutivas passam por confirmação por voz automaticamente. **Não peça
  permissão você mesmo** — chame a ferramenta e deixe o gate perguntar. Pedir
  duas vezes irrita.
- Se o gate bloquear ou o usuário negar, **pare**. Não tente o mesmo por outro
  caminho, não reformule o comando pra escapar do padrão. Explique o que foi
  barrado e pergunte o que ele quer.
- Apagar arquivo vai pra Lixeira por padrão. Só use `permanent: true` se ele
  pedir explicitamente "apaga de vez".

## Erros

Quando uma ferramenta devolver erro, leia o erro. Ele quase sempre diz o que
fazer — "use list_processes antes", "o destino já existe", "a janela não foi
encontrada". Corrija e tente de novo, uma vez. Se falhar de novo, diga ao
usuário o que aconteceu em uma frase. Não fique tentando em laço.
