# APEX

Um copiloto de voz para Windows. Você fala, ele ouve, pensa e mexe no seu PC.

*Apex* é o ponto de tangência de uma curva — onde o piloto passa mais perto do
vértice pra sair mais rápido. Nome original, sem dono.

```
   você fala ──> microfone ──> transcrição local ──> Claude ──> ferramentas
                                                        │            │
                                              vault de markdown   seu PC
                                                        │            │
                                                        └──> voz ────┘
```

## O que ele é

Seis camadas. Quatro vêm do desenho clássico de "assistente pessoal com IA";
duas foram acrescentadas porque sem elas ele não faz o que promete.

| Camada | Onde mora | O que faz |
|---|---|---|
| **Cérebro** | `apex/brain.py`, `skills/` | Claude Opus 5 com laço agêntico e uma pasta de skills carregadas sob demanda |
| **Memória** | `apex/vault.py`, `vault/` | Markdown puro. Sem banco de dados. Abre no Obsidian |
| **Voz** | `apex/audio/` | Transcrição e síntese locais |
| **Rosto** | `apex/hud.py` | HUD de terminal: estado, vitais, vault, agenda, atividade |
| **Controle** ⁺ | `apex/tools/` | Shell, programas, janelas, teclado, mouse e **visão de tela** |
| **Gatilho** ⁺ | `apex/scheduler.py`, `hardware/` | Palmas, agendador, e Wake-on-LAN por ESP32 |
| **Consciência** ⁺ | `apex/awareness.py` | **Ele fala primeiro.** Observa e decide quando te interromper |

⁺ As três que faltavam. Um assistente que só lê e escreve markdown é um bloco
de notas caro; um HUD que mostra "09:30 — briefing" é decoração se nada dispara
aquilo; e um assistente que só responde é a Alexa.

## Por que ele fala primeiro

Repara nas falas do JARVIS no filme: quase nenhuma responde a uma pergunta.
*"Sir, the suit's power is at 15%."* Ele observa e decide interromper. **Essa é
a diferença de sensação** — o resto é polimento.

`apex/awareness.py` roda sensores baratos em laço e emite uma observação quando
algo muda:

| Sensor | Fala quando |
|---|---|
| Bateria | Cruza 20% e 10% — **na travessia**, não enquanto estiver abaixo |
| Disco | Sobra menos que o limite. Abaixo da metade dele, vira urgente |
| CPU | Alta **e sustentada** por minutos. Pico de dois segundos não é notícia |
| Foco | Você está há 90 minutos grudado na mesma janela |
| Retorno | Você sumiu por 45 minutos e voltou |

### As duas regras que impedem ele de virar praga

**1. Interromper custa atenção, não token.** Um assistente que fala a cada
cinco minutos é mutado no primeiro dia. Por isso: no máximo 4 interrupções por
hora, horário de silêncio (23h–8h), cooldown por assunto, uma interrupção por
ciclo, e **detecção de tela cheia** — jogo, chamada de vídeo e apresentação
nunca são interrompidos.

Só a prioridade alta (bateria acabando, disco quase cheio) fura tudo isso.

**2. A maioria das interrupções não custa chamada de API.** "Bateria em 15 por
cento" é frase pronta. Só sobe pro modelo o que exige julgamento — quando o
disco está crítico, ele investiga o que está ocupando espaço antes de falar.

Ajuste tudo em `awareness` no `config.json`. Pra desligar:
`"awareness": { "enabled": false }`.

## Dois cérebros, mesmo corpo

O consenso de 2026 para assistente de voz local é **faster-whisper + Piper +
Ollama**. As duas primeiras peças o APEX já usava. A terceira agora existe: o
cérebro é trocável numa linha do `config.json`.

```json
"brain": "claude"    // API da Anthropic — mais esperto, custa por comando
"brain": "ollama"    // modelo local — de graça, offline, mais burro
```

Ou sem editar nada: `.\rodar.bat --local`.

| | Claude Opus 5 | Ollama local |
|---|---|---|
| Custo | por comando | zero |
| Internet | obrigatória | nenhuma |
| Seus dados | vão pra API | não saem da máquina |
| Escolher a ferramenta certa | acerta quase sempre | erra bastante |
| Ver a tela | sim | só com modelo de visão |
| Hardware | qualquer um | 8 GB de RAM no mínimo, GPU ajuda muito |

### Rodando local

```powershell
winget install Ollama.Ollama
ollama pull qwen3:8b
.\rodar.bat --testar-cerebro --local
```

Qwen3 é a família com melhor tool calling entre os que rodam em casa. Escolha
pelo hardware: `qwen3:4b-instruct` com 8 GB, `qwen3:8b` no meio termo,
`qwen3:30b` se você tem 24 GB de VRAM.

Pra ele enxergar a tela, adicione um modelo de visão:

```powershell
ollama pull qwen2.5vl:7b
```

e preencha `ollama.vision_model` no config. **Sem isso, `look_at_screen` é
removida da lista** em vez de falhar no meio de uma tarefa.

### Três coisas que mudam no modo local

**Ele recebe menos ferramentas.** 28 schemas degradam a escolha de um modelo de
8B. Em modo local ele vê 15 por padrão — as que importam. Ajuste em
`ollama.tools`.

**O prompt fica mais mandão.** É o inverso do que vale pro Opus 5, onde
instrução muito prescritiva atrapalha. Modelo pequeno precisa de regra dura.

**A saída é limpa antes de virar voz.** Modelo local vaza `<think>`, markdown e
bloco de código mesmo mandado não vazar. Blocos de código são removidos
inteiros — ler código em voz alta é pior que não dizer nada.

## Privacidade, sem enrolação

Você vai ver por aí a frase *"seu áudio nunca sai da máquina"*. É verdade — e é
meia verdade.

- ✅ **O áudio fica.** A transcrição roda local (faster-whisper) e a voz também
  (Piper). Nenhum arquivo de som sai do seu PC.
- ⚠️ **O texto vai.** O que você falou, transcrito, é enviado pra API da
  Anthropic — senão não existe raciocínio. O mesmo vale pro que as ferramentas
  devolvem: trecho de arquivo que ele leu, saída de comando, e **prints de tela**
  quando ele usa `look_at_screen`.
- 🔒 Se você mandar "lê meu arquivo de senhas", o conteúdo vai junto. O APEX não
  tem como saber que aquilo era sensível.

Quer 100% local? Troque o cérebro por um modelo via Ollama. Fica muito mais
burro, e as ferramentas vão errar mais — mas nada sai da máquina.

## Instalação

Precisa de **Windows 10/11** e **Python 3.10+**.

```powershell
git clone <este-repo>
cd Project-1
powershell -ExecutionPolicy Bypass -File scripts\instalar.ps1
```

O script cria o `.venv`, instala tudo, pede sua chave da API
([console.anthropic.com](https://console.anthropic.com/settings/keys)) e baixa a
voz pt-BR e os modelos de transcrição.

Depois:

```powershell
.\rodar.bat
```

### Antes de confiar no microfone

```powershell
.\rodar.bat --testar-audio
```

Mostra o nível em tempo real. Fale — a barra tem que passar do limiar. Bata
palmas — tem que aparecer `PALMAS!`. Se não aparecer, ajuste
`clap.threshold_db_above_noise` no `config.json`: menor = mais sensível.

### Sem microfone, só pra testar o comportamento

```powershell
.\rodar.bat --texto
```

Mesmo cérebro, mesmas ferramentas, sem áudio. É assim que se depura.

## Como se usa

**Chamando pelo nome.** O microfone fica ouvindo, mas só reage quando a frase
*começa* com o nome:

> "**Apex**, abre o Spotify"
> "**Apex**, o que tá escrito nessa janela?"
> "**Apex**, acha meu currículo"

Falar "chegamos no apex da curva" não ativa nada — o nome tem que abrir a
frase. Só um vocativo pode vir antes ("ei, Apex").

**Batendo palmas.** Duas palmas abrem a conversa sem falar o nome.

**A janela fica aberta.** Depois da primeira interação você tem 30 segundos pra
continuar sem repetir o nome. Passou disso, a conversa é zerada e ele volta a
esperar o nome.

## Segurança

Um modelo interpretando áudio pode errar. "Limpa a pasta de downloads" e "limpa
o disco C" ficam parecidos com o ventilador ligado. Por isso existe
`apex/safety.py`.

| Modo | O que faz |
|---|---|
| `permissive` | Só a lista de bloqueio permanente |
| `confirm` | **Padrão.** Ações destrutivas viram uma pergunta falada |
| `paranoid` | Todo comando de shell e toda escrita são confirmados |

Quando algo precisa de confirmação, ele **pergunta em voz alta** e espera sim ou
não. Silêncio por 12 segundos = não. Resposta que ele não entendeu = ele
pergunta de novo, e depois cancela.

Alguns comandos (`format`, `diskpart`, `bcdedit`, apagar shadow copies) estão
numa lista de bloqueio que **nenhum modo libera**.

Apagar arquivo vai pra Lixeira por padrão.

## Palmas ligando o PC

Com o PC **desligado**, nenhum software roda pra ouvir palma. Nos vídeos por aí
isso é quase sempre suspensão, ou edição.

Pra funcionar de verdade: um **ESP32 com microfone** (~R$ 55 no total) fica
ligado 24h ouvindo, e quando reconhece o padrão manda um magic packet.

Sketch pronto em `hardware/esp32_clap_wol/`. Antes de montar, teste se o seu PC
sequer aceita Wake-on-LAN:

```powershell
getmac /v                                      # descubra o MAC da placa de rede
python scripts\wol.py AA:BB:CC:DD:EE:FF        # com o PC suspenso, de outra máquina
```

Se isso não acorda, o ESP32 também não vai. Quatro coisas precisam estar certas:

1. **BIOS** — ative "Wake on LAN" / "Power On By PCI-E"
2. **Placa de rede** — Gerenciador de Dispositivos > Propriedades > Gerenciamento
   de Energia > "Permitir que este dispositivo reative o computador"
3. **Inicialização Rápida do Windows** — precisa estar **desligada**, ela corta a
   energia da placa de rede
4. **Cabo** — WoL por WiFi quase nunca funciona

## Agendador

É o que faz ele agir sem ser chamado. No `config.json`:

```json
"scheduler": {
  "enabled": true,
  "jobs": [
    { "name": "briefing-manha", "at": "08:00",
      "days": ["mon","tue","wed","thu","fri"],
      "prompt": "Rode a skill 'briefing'...", "speak": true }
  ]
}
```

Jobs agendados rodam **sem gate interativo** — não tem ninguém ali pra
confirmar, então qualquer ação destrutiva é negada automaticamente.

## O vault

```
vault/
  raw/2026-08-06/*.md   tudo que foi capturado, cru, com hora
  wiki/*.md             conhecimento destilado, o que vale reter
  outputs/*.md          tudo que o APEX entrega
```

Markdown puro, de propósito. Você lê e edita tudo que ele sabe com qualquer
editor, abre direto no Obsidian (os `[[links]]` viram um grafo), e se este
projeto morrer amanhã sua memória continua sendo uma pasta.

A busca é grep com pontuação, não embeddings. Pra centenas de notas isso é
rápido, previsível e não precisa manter índice nenhum.

## Skills

Cada skill é um `SKILL.md` com um procedimento. O APEX lê quando a tarefa pede.

| Skill | Pra quê |
|---|---|
| `briefing` | Resumo da manhã |
| `revisao` | Fecha o dia, destila `raw/` pra `wiki/` |
| `plano-do-dia` | Escolhe três coisas e escreve o primeiro passo de cada |
| `controle-pc` | Como operar o Windows com segurança |
| `vault` | O que gravar, onde, e quando procurar |

Criar uma nova é fazer uma pasta em `skills/` com um `SKILL.md` dentro. A
segunda linha precisa ser `descricao: ...` — é ela que aparece no `list_skills`.

Regra que vale mais que o resto: **skills pequenas e de um assunto só ganham de
um prompt gigante.**

## Ferramentas

28 no total. As que importam:

| | |
|---|---|
| `look_at_screen` | Tira print e **enxerga** — lê erro na tela, acha botão, confirma que funcionou |
| `run_shell` | PowerShell, com o gate na frente |
| `open_app` | Programa, arquivo, pasta ou URL |
| `focus_window` / `type_text` / `click_at` | Opera a interface |
| `vault_search` / `vault_write` | Memória |
| `web_search` | Busca na web (roda no servidor da Anthropic) |
| `system_status` | CPU, RAM, disco, bateria |

`type_text` cola pelo clipboard em vez de digitar tecla a tecla — `pyautogui`
erra com acento em teclado ABNT, e "não" vira "nao" ou coisa pior.

## Configuração

Tudo em `config.json` (criado do `config.example.json` na primeira execução).

| Chave | Padrão | O que faz |
|---|---|---|
| `effort` | `low` | Quanto o modelo pensa. `low` é rápido; `high` acerta mais em tarefa complexa |
| `stt.model` | `small` | `tiny`→`large`. Maior = melhor e mais lento |
| `stt.wake_model` | `tiny` | Modelo barato só pra checar o nome |
| `tts.engine` | `piper` | `piper` (offline) · `edge` (melhor voz, precisa de net) · `pyttsx3` |
| `wake.conversation_timeout` | `30` | Segundos sem precisar repetir o nome |
| `audio.silence_threshold_db` | `-38` | Ajustado sozinho na calibração |
| `safety.mode` | `confirm` | `permissive` · `confirm` · `paranoid` |
| `hud.accent` | `red` | `red` · `green` · `cyan` · `violet` |
| `awareness.enabled` | `true` | Se ele pode falar primeiro |
| `awareness.max_interrupts_per_hour` | `4` | Teto de interrupções |
| `awareness.quiet_hours_start` / `_end` | `23` / `8` | Janela de silêncio |

O `config.json` está no `.gitignore` — é onde mora sua chave de API.

## Sobre o nome

Chamar isso de "Jarvis" seria mais fácil de explicar, mas Jarvis é da
Marvel/Disney, e o Relâmpago McQueen também. Enquanto for um programa no seu PC
que você nunca publica, ninguém nunca vai saber nem se importar. O risco aparece
quando o repositório vai pro GitHub, o vídeo vai pro Instagram, ou aquilo vira
produto.

APEX não tem dono. Fica com você.

## Limitações, honestamente

- **Windows.** As ferramentas de janela, volume e energia dependem da API do
  Windows. O resto roda em qualquer lugar, mas o alvo é o Windows.
- **Não roda como administrador.** Coisa que pede UAC vai travar num prompt que
  ele não consegue clicar.
- **Custa dinheiro.** Cada comando é uma chamada de API. Prints de tela são os
  mais caros — uma imagem vale alguns milhares de tokens. O histórico é podado
  automaticamente e só o print mais recente fica no contexto.
- **A transcrição erra.** Nome próprio, sigla, gíria. Com `stt.model` em
  `medium` melhora bastante, ao custo de CPU.
- **Wake word não é perfeito.** Ambiente barulhento gera falso negativo. As
  palmas são mais confiáveis.
