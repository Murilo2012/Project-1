"""APEX — copiloto de voz para Windows.

Quatro camadas:
  cérebro   API da Claude + pasta de skills (apex/brain.py, skills/)
  memória   vault de markdown, sem banco de dados (apex/vault.py)
  voz       STT e TTS locais (apex/audio/)
  rosto     HUD de terminal (apex/hud.py)

Mais duas que o desenho original não tinha:
  controle  shell, programas, janelas, teclado, mouse e visão (apex/tools/)
  gatilho   palmas e agendador, pra ele agir sem ser chamado
"""

__version__ = "0.1.0"
