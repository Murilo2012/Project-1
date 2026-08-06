"""Desktop: ver a tela, controlar janelas, teclado e mouse.

look_at_screen é a ferramenta mais poderosa daqui: devolve a imagem da tela
como bloco de imagem de verdade, então o modelo enxerga o que está acontecendo
em vez de adivinhar. É o que permite "o que tá escrito nessa janela?" e
"clica no botão azul".
"""

from __future__ import annotations

import base64
import io
import platform
import time

from apex.tools.registry import ToolContext, integer, obj, string, tool

IS_WINDOWS = platform.system() == "Windows"

# Limite do lado maior da imagem. Tela cheia em 4K viraria uma conta de tokens
# desnecessária; 1920 já é mais que suficiente pra ler texto de interface.
MAX_IMAGE_EDGE = 1920


def _screenshot_blocks(region: tuple[int, int, int, int] | None, caption: str) -> list[dict]:
    import pyautogui  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    shot = pyautogui.screenshot(region=region)

    if max(shot.size) > MAX_IMAGE_EDGE:
        ratio = MAX_IMAGE_EDGE / max(shot.size)
        new_size = (int(shot.width * ratio), int(shot.height * ratio))
        shot = shot.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    shot.save(buffer, format="PNG", optimize=True)
    encoded = base64.standard_b64encode(buffer.getvalue()).decode("ascii")

    return [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": encoded},
        },
        {"type": "text", "text": f"{caption} Resolução da imagem: {shot.width}x{shot.height}."},
    ]


@tool(
    name="look_at_screen",
    description=(
        "Tira um print da tela e OLHA pra ela. Use sempre que precisar saber o "
        "que está acontecendo visualmente: ler uma mensagem de erro, ver qual "
        "janela está aberta, conferir se uma ação funcionou, ou localizar um "
        "botão antes de clicar. Depois de executar algo com efeito visual, "
        "olhar a tela é a forma de confirmar que deu certo."
    ),
    schema=obj(
        {
            "region": string(
                "Região opcional 'x,y,largura,altura'. Vazio captura a tela toda."
            ),
        }
    ),
)
def look_at_screen(ctx: ToolContext, region: str = "") -> list[dict]:
    parsed = None
    caption = "Print da tela inteira."
    if region.strip():
        try:
            x, y, width, height = (int(v.strip()) for v in region.split(","))
            parsed = (x, y, width, height)
            caption = f"Print da região {region}."
        except ValueError:
            return [{"type": "text", "text": f"Região inválida: '{region}'. Use 'x,y,larg,alt'."}]

    return _screenshot_blocks(parsed, caption)


@tool(
    name="list_windows",
    description=(
        "Lista as janelas abertas com título e posição. Use antes de focar ou "
        "mover uma janela, e pra saber o que o usuário está fazendo."
    ),
    schema=obj({}),
)
def list_windows(ctx: ToolContext) -> str:
    if not IS_WINDOWS:
        return "Controle de janelas só está implementado no Windows."
    import pygetwindow as gw  # noqa: PLC0415

    windows = [w for w in gw.getAllWindows() if w.title.strip() and w.width > 0]
    if not windows:
        return "Nenhuma janela visível."

    lines = []
    for window in windows[:30]:
        state = " [minimizada]" if window.isMinimized else ""
        active = " [ativa]" if window.isActive else ""
        lines.append(f"{window.title} — {window.width}x{window.height} em ({window.left},{window.top}){state}{active}")
    return "\n".join(lines)


@tool(
    name="focus_window",
    description=(
        "Traz uma janela pra frente e dá foco pra ela. Use antes de digitar ou "
        "clicar em algo, pra garantir que a entrada vá pro lugar certo. Casa "
        "por parte do título, sem diferenciar maiúsculas."
    ),
    schema=obj(
        {"title": string("Parte do título da janela, ex: 'chrome', 'bloco de notas'.")},
        required=["title"],
    ),
)
def focus_window(ctx: ToolContext, title: str) -> str:
    if not IS_WINDOWS:
        return "Controle de janelas só está implementado no Windows."
    import pygetwindow as gw  # noqa: PLC0415

    needle = title.lower()
    matches = [w for w in gw.getAllWindows() if needle in w.title.lower() and w.title.strip()]
    if not matches:
        return f"Nenhuma janela com '{title}' no título. Use list_windows pra ver as abertas."

    window = matches[0]
    try:
        if window.isMinimized:
            window.restore()
        window.activate()
    except Exception:  # noqa: BLE001 - a API do Windows falha por motivos variados
        try:
            window.minimize()
            window.restore()
        except Exception:  # noqa: BLE001
            return f"Achei '{window.title}' mas não consegui trazer pra frente."

    time.sleep(0.25)
    return f"Foquei em '{window.title}'."


@tool(
    name="type_text",
    description=(
        "Digita um texto na janela que está em foco, como se fosse o teclado. "
        "Use pra preencher campo, escrever mensagem, digitar num editor. Foque "
        "a janela certa antes, com focus_window."
    ),
    schema=obj(
        {
            "text": string("O texto a digitar."),
            "press_enter": {
                "type": "boolean",
                "description": "Aperta Enter no fim. Padrão false.",
                "default": False,
            },
        },
        required=["text"],
    ),
)
def type_text(ctx: ToolContext, text: str, press_enter: bool = False) -> str:
    import pyautogui  # noqa: PLC0415
    import pyperclip  # noqa: PLC0415

    # Colar em vez de digitar tecla a tecla: pyautogui erra com acento em
    # teclado ABNT, e "não" vira "nao" ou pior.
    try:
        previous = pyperclip.paste()
    except Exception:  # noqa: BLE001
        previous = None

    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
    except Exception:  # noqa: BLE001 - sem clipboard, digita mesmo assim
        pyautogui.typewrite(text, interval=0.01)
    finally:
        if previous is not None:
            time.sleep(0.15)
            try:
                pyperclip.copy(previous)
            except Exception:  # noqa: BLE001
                pass

    if press_enter:
        time.sleep(0.1)
        pyautogui.press("enter")
    return f"Digitei {len(text)} caracteres{' e apertei Enter' if press_enter else ''}."


@tool(
    name="press_keys",
    description=(
        "Aperta uma combinação de teclas. Use pra atalhos: 'ctrl+s' pra salvar, "
        "'alt+tab', 'win+d', 'ctrl+shift+esc'. Separe com +."
    ),
    schema=obj(
        {
            "keys": string("Combinação, ex: 'ctrl+s', 'alt+f4', 'win'."),
            "repeat": integer("Quantas vezes repetir. Padrão 1.", default=1),
        },
        required=["keys"],
    ),
)
def press_keys(ctx: ToolContext, keys: str, repeat: int = 1) -> str:
    import pyautogui  # noqa: PLC0415

    parts = [k.strip().lower() for k in keys.replace(" ", "").split("+") if k.strip()]
    if not parts:
        return "Nenhuma tecla informada."

    for _ in range(max(1, min(repeat, 50))):
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
        time.sleep(0.05)
    return f"Apertei {keys}{f' {repeat} vezes' if repeat > 1 else ''}."


@tool(
    name="click_at",
    description=(
        "Clica numa coordenada da tela. Use DEPOIS de look_at_screen, pra saber "
        "onde clicar. Se a imagem foi redimensionada, as coordenadas que você "
        "vê já são as reais — esta ferramenta ajusta a escala automaticamente."
    ),
    schema=obj(
        {
            "x": integer("Coordenada X na imagem que você viu."),
            "y": integer("Coordenada Y na imagem que você viu."),
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Qual botão. Padrão left.",
                "default": "left",
            },
            "clicks": integer("Quantos cliques. 2 pra duplo clique. Padrão 1.", default=1),
        },
        required=["x", "y"],
    ),
)
def click_at(ctx: ToolContext, x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    import pyautogui  # noqa: PLC0415

    screen_width, screen_height = pyautogui.size()

    # A imagem enviada pro modelo pode ter sido reduzida. Reconvertemos as
    # coordenadas pra escala real da tela.
    if max(screen_width, screen_height) > MAX_IMAGE_EDGE:
        ratio = max(screen_width, screen_height) / MAX_IMAGE_EDGE
        x, y = int(x * ratio), int(y * ratio)

    x = max(0, min(x, screen_width - 1))
    y = max(0, min(y, screen_height - 1))

    pyautogui.click(x=x, y=y, button=button, clicks=max(1, min(clicks, 3)))
    return f"Cliquei em ({x}, {y}) com o botão {button}."


@tool(
    name="scroll",
    description="Rola a tela pra cima ou pra baixo na janela em foco.",
    schema=obj(
        {
            "amount": integer("Positivo rola pra cima, negativo pra baixo. Ex: -5."),
        },
        required=["amount"],
    ),
)
def scroll(ctx: ToolContext, amount: int) -> str:
    import pyautogui  # noqa: PLC0415

    pyautogui.scroll(amount * 120)
    direction = "cima" if amount > 0 else "baixo"
    return f"Rolei pra {direction}."
