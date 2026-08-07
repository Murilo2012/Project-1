# Kit de conexão JARVIS ↔ Claude

Instala sobre o [Mark-L do FatihMakes](https://github.com/FatihMakes/Mark-L)
três coisas: personalidade em português, o Claude Code como motor de
programação, e um servidor MCP que dá ao Claude acesso às ações do JARVIS.

## Instalação

**No fork `Murilo2012/Mark-L`, branch `claude/connect-jarvis-github-3p1ler`, o
kit já vem aplicado.** Basta clonar e instalar as dependências:

```bash
git clone -b claude/connect-jarvis-github-3p1ler https://github.com/Murilo2012/Mark-L.git
cd Mark-L
pip install -r requirements.txt
```

Para aplicar em outra cópia do Mark-L, copie a pasta `jarvis/` para dentro dela
e rode:

```bash
python jarvis/instalar.py
```

O instalador faz backup (`.bak-jarvis`) de tudo que altera, pode ser rodado
mais de uma vez sem duplicar nada, e desfaz tudo com:

```bash
python jarvis/instalar.py --desfazer
```

Só o português, sem mexer no resto:

```bash
python jarvis/instalar.py --só-portugues
```

## Diagnóstico

```bash
python jarvis/diagnostico.py
```

Mostra SO, RAM, GPU, modelos do Ollama, versão do Claude Code e quais pacotes
faltam. Só lê — não altera nada. Cole a saída na conversa para calibrarmos a
migração para o Ollama.

## O que cada arquivo faz

| Arquivo | Função |
|---|---|
| `instalar.py` | Aplica o kit, com backup e desfazer |
| `diagnostico.py` | Lê o estado da máquina |
| `prompt-pt.txt` | Personalidade em português → `core/prompt.txt` |
| `claude_backend.py` | Motor de programação via `claude -p` |
| `jarvis_mcp_server.py` | Expõe as ações do JARVIS como ferramentas do Claude |

## Os três recursos

### Português

Substitui `core/prompt.txt`. Funciona sozinho, sem depender de mais nada — é a
mudança de maior efeito pelo menor esforço.

Aproveite e ajuste `config/api_keys.json`:

```json
{
  "gemini_api_key": "sua-chave",
  "assistant_name": "JARVIS",
  "user_name": "Murilo"
}
```

### Agente de programação com Claude

O `actions/dev_agent.py` e o `actions/code_helper.py` rodam em
`gemini-2.5-flash`, um modelo pequeno que erra bastante ao escrever código. O
instalador troca as fábricas `_get_model()` e `_get_gemini()` por chamadas ao
`claude -p`, usando a assinatura do Claude Code — sem chave de API, sem
cobrança por token.

Teste por voz: *"JARVIS, cria um programa que organiza minha pasta de downloads
por extensão."* O projeto sai em `~/Desktop/JarvisProjects`.

Requer `claude --version` respondendo.

### JARVIS como ferramenta do Claude

```bash
pip install "mcp[cli]"
claude mcp add jarvis python C:\caminho\para\Mark-L\jarvis_mcp_server.py
```

Depois disso, numa conversa com o Claude: "abre o VS Code", "como está minha
CPU?", "lista meu desktop" — executado através do JARVIS.

Ferramentas expostas: `open_app`, `system_status`, `list_files`, `read_file`,
`find_files`, `set_volume`, `computer_action`, `web_search`.

**Ficaram de fora de propósito:** apagar arquivos, desligar e reiniciar.
Continuam funcionando por voz no JARVIS — só não ao alcance de uma chamada
automática. Se quiser expor, é editar `jarvis_mcp_server.py`.

## O que foi testado, e o que não foi

Testado numa cópia real do Mark-L: o instalador aplica os patches, os arquivos
alterados continuam compilando, rodar duas vezes não duplica nada, e o
`--desfazer` restaura os originais byte a byte.

**Não testado:** o JARVIS rodando de fato. Isso precisa de microfone, GPU,
PyQt6 e uma chave do Gemini — nada disso existia no container onde o kit foi
escrito. O `claude_backend.py` e o `jarvis_mcp_server.py` passaram só por
verificação de sintaxe. São primeira versão; espere ajustes no primeiro teste
de verdade.

## O que ainda não está aqui: Ollama como cérebro

O `core/llm_client.py` do repositório já traz um cliente Ollama completo (586
linhas, com streaming e tool calling), mas **nenhum arquivo o importa** — é
código órfão do Mark XL. O mesmo vale para `core/stt.py` (Whisper) e
`core/tts.py` (Kokoro/EdgeTTS).

Religá-los exige reescrever o laço principal do `main.py`, hoje construído
inteiro em torno do stream de áudio bidirecional da Gemini Live API
(`JarvisLive.run`, linha ~1400). Isso é refatoração, não patch — precisa ser
feito com a máquina na frente, testando a cada passo.

Rode o `diagnostico.py` antes. Modelos abaixo de 7B erram demais na escolha de
ferramentas, e o JARVIS tem 23 delas. O padrão do `llm_client.py` é
`llama3.2` (3B), que vai frustrar. `qwen2.5:7b` ou `llama3.1:8b` são o piso.

## Licença

O Mark-L é CC BY-NC 4.0: uso pessoal e não comercial, mantendo o crédito ao
autor original. Este kit segue a mesma licença.
