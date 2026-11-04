"""Abas isoladas do aplicativo: cada uma guarda o próprio estado e não conhece as outras.

- `comum`: premissas atuais, camadas do mapa, área de transferência, pasta de saída e autoteste.
- `lote`: Raio-X do lote (consultar, escolher, KMZ de terreno, croqui e exportações).
- `prospectar`: entorno em volta de um lote ou KMZ de região, e o CSV de oportunidades.
- `simulador`: esqueleto; o motor está sendo feito à parte.

A fachada `raiox.app.Api` chama as abas dentro de um envelope que transforma qualquer
exceção em `{"ok": False, "erro": ..., "aba": ...}`; assim um erro numa aba não derruba
a janela nem as outras abas.
"""
