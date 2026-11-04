"""Ponto de entrada do Raio-X empacotado (Raio-X.exe): abre a janela do programa."""
from __future__ import annotations

import multiprocessing

from raiox.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
