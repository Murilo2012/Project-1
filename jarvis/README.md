# Kit de conexão JARVIS ↔ Claude

Arquivos prontos para instalar sobre o [Mark-L do FatihMakes](https://github.com/FatihMakes/Mark-L).
Nada aqui foi executado — o Mark-L precisa de microfone, GPU, PyQt6 e Windows,
nenhum deles disponível no container onde estes arquivos foram escritos.
Trate como código de primeira versão, para testar junto.

## O que tem aqui

| Arquivo | O que faz | Onde vai |
|---|---|---|
| `prompt-pt.txt` | Personalidade do assistente em português | substitui `core/prompt.txt` |
| `jarvis_mcp_server.py` | Expõe as ações do JARVIS como ferramentas do Claude | raiz do Mark-L |
| `claude_backend.py` | Troca o Gemini pelo Claude Code no agente de programação | raiz do Mark-L |

## Ordem de instalação

### 0. Fork (1 clique, só você pode fazer)

Abra https://github.com/FatihMakes/Mark-L e clique em **Fork**. Depois:

```bash
git clone https://github.com/Murilo2012/Mark-L.git
cd Mark-L
pip install -r requirements.txt
```

### 1. Português

```bash
cp prompt-pt.txt core/prompt.txt
```

Funciona sozinho, sem depender de mais nada. É a mudança de maior efeito pelo
menor esforço: o JARVIS passa a falar português naturalmente.

No `config/api_keys.json`, aproveite e ajuste:

```json
{
  "gemini_api_key": "sua-chave",
  "assistant_name": "JARVIS",
  "user_name": "Murilo"
}
```

### 2. Claude Code na máquina

Instale o Claude Code no PC e confirme:

```bash
claude --version
```

Esse passo destrava os dois seguintes. Sem ele, nada abaixo funciona.

### 3. Agente de programação com Claude

Copie `claude_backend.py` para a raiz do Mark-L. Em `actions/dev_agent.py`,
apague a função `_get_model` inteira (linhas 27-36) e ponha no lugar:

```python
from claude_backend import get_model as _get_model
```

Teste por voz: *"JARVIS, cria um programa que organiza minha pasta de downloads
por extensão."* Ele delega para o Claude Code, que escreve, roda e corrige até
funcionar. O projeto sai em `~/Desktop/JarvisProjects`.

Isso usa a assinatura do Claude Code — não é API paga por token.

### 4. JARVIS como ferramenta do Claude

```bash
pip install "mcp[cli]"
claude mcp add jarvis python C:\caminho\para\Mark-L\jarvis_mcp_server.py
```

Feito isso, numa conversa com o Claude você pode pedir "abre o VS Code",
"como está minha CPU?", "lista meu desktop" — e ele executa através do JARVIS.

Ferramentas expostas: `open_app`, `system_status`, `list_files`, `read_file`,
`find_files`, `set_volume`, `computer_action`, `web_search`.

Ficaram de fora de propósito: apagar arquivos, desligar e reiniciar. Continuam
funcionando por voz no JARVIS — só não ao alcance de uma chamada automática.

## O que ainda não está aqui

**Ollama como cérebro.** O `core/llm_client.py` do repositório já traz um
cliente Ollama completo (586 linhas, com streaming e tool calling), mas nenhum
arquivo o importa — é código órfão do Mark XL. Religá-lo exige reescrever o
laço principal do `main.py`, que hoje é construído inteiro em torno do stream
de áudio bidirecional da Gemini Live API (`JarvisLive.run`, linha ~1400).

Isso não é um patch — é uma refatoração, e precisa ser feita com a máquina na
frente, testando a cada passo. Fica para quando estivermos juntos.

Antes disso, duas informações são necessárias:

```bash
ollama list          # quais modelos você já baixou
```

E qual a sua GPU e RAM. Modelos abaixo de 7B erram demais na escolha de
ferramentas, e o JARVIS tem 23 delas. O padrão do código é `llama3.2` (3B),
que vai frustrar. `qwen2.5:7b` ou `llama3.1:8b` são o piso realista.

## Licença

O Mark-L é CC BY-NC 4.0: uso pessoal e não comercial, mantendo o crédito ao
autor original. Os arquivos deste kit seguem a mesma licença.
