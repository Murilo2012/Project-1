"""Envia um Wake-on-LAN. Útil pra testar antes de montar o ESP32.

    python scripts/wol.py                 usa o MAC do config.json
    python scripts/wol.py AA:BB:CC:DD:EE:FF

Se isto não acordar o PC, o ESP32 também não vai — o problema está na BIOS ou
no Windows, não no código. Confira os quatro pontos do README.
"""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_mac(text: str) -> bytes:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", text)
    if len(cleaned) != 12:
        raise ValueError(f"MAC inválido: '{text}'. Esperado 6 bytes, ex: AA:BB:CC:DD:EE:FF")
    return bytes.fromhex(cleaned)


def send(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    payload = b"\xff" * 6 + parse_mac(mac) * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):  # UDP não garante entrega
            sock.sendto(payload, (broadcast, port))

    print(f"Magic packet enviado pra {mac} via {broadcast}:{port}")


def main() -> int:
    if len(sys.argv) > 1:
        mac, broadcast, port = sys.argv[1], "255.255.255.255", 9
    else:
        from apex import config as config_module

        cfg = config_module.load()
        mac = cfg.get("wol.mac", "")
        broadcast = cfg.get("wol.broadcast", "255.255.255.255")
        port = int(cfg.get("wol.port", 9))
        if not mac:
            print("Nenhum MAC no config.json (wol.mac) e nenhum passado por argumento.")
            print("Descubra o seu com: getmac /v")
            return 1

    try:
        send(mac, broadcast, port)
    except (ValueError, OSError) as exc:
        print(f"Erro: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
