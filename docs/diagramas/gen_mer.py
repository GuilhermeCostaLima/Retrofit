import math
ANG = {'FABRICA':[135,165,195,225],'USUARIO':[165,135,105,75,45,15],'MAQUINA':[115,80,175,200,245,275,305],
 'REFUGO':[35,0,-35],'PARADA':[90,45,-45,-90],'MOTIVO_PARADA':[70,0,-70],'LEITURA':[80,40,5,-30,-70,-110],'ALERTA':[95,140,180,220,265]}
E = {  # entidade: (x, y, [atributos], pk)
 'FABRICA': (0, 6, ['id', 'nome', 'cnpj', 'cidade']),
 'USUARIO': (6, 10.5, ['id', 'nome', 'email', 'senha_hash', 'perfil', 'ativo']),
 'MAQUINA': (6, 1.5, ['id', 'nome', 'tipo', 'ciclo_padrao_seg', 'temp_max', 'token', 'ativa']),
 'REFUGO': (10, 6, ['id', 'data_hora', 'quantidade']),
 'PARADA': (15, 6, ['id', 'inicio', 'fim', 'observacao']),
 'MOTIVO_PARADA': (20.5, 6, ['id', 'descricao', 'planejada']),
 'LEITURA': (13, -1.8, ['id', 'data_hora', 'estado', 'pecas', 'temperatura', 'corrente']),
 'ALERTA': (0, -1.8, ['id', 'tipo', 'mensagem', 'criado_em', 'resolvido_em']),
}
R = [  # nome, x, y, e1, card1, e2, card2
 ('possui', 2.6, 8.6, 'FABRICA', '1', 'USUARIO', 'N'),
 ('possui ', 2.6, 3.6, 'FABRICA', '1', 'MAQUINA', 'N'),
 ('aponta', 8.3, 8.6, 'USUARIO', '1', 'REFUGO', 'N'),
 ('tem', 8.3, 3.6, 'MAQUINA', '1', 'REFUGO', 'N'),
 ('informa', 12.8, 8.9, 'USUARIO', '1', 'PARADA', 'N'),
 ('registra', 12.8, 3.3, 'MAQUINA', '1', 'PARADA', 'N'),
 ('classifica', 18, 6, 'MOTIVO_PARADA', '1', 'PARADA', 'N'),
 ('envia', 9.6, -0.4, 'MAQUINA', '1', 'LEITURA', 'N'),
 ('gera', 3, -0.4, 'MAQUINA', '1', 'ALERTA', 'N'),
]
L = ['graph MER {', 'layout=neato; overlap=true; splines=false; bgcolor=white; pad=0.4;',
     'node [fontname="Helvetica"]; edge [fontname="Helvetica", fontsize=12, color="#333333"];',
     'titulo [shape=plaintext, label="Modelo Entidade-Relacionamento (MER) — Retrofit", fontsize=18, pos="10,13.6!"];']
for nome, (x, y, attrs) in E.items():
    L.append(f'{nome} [shape=box, style=filled, fillcolor="#dfeaf7", color="#1f4e79", penwidth=1.6, fontsize=14, label="{nome}", width=1.9, height=0.55, pos="{x},{y}!"];')
    for a in attrs:
        aid = f'{nome}_{a}'
        lab = f'<<U>{a}</U>>' if a == 'id' else f'"{a}"'
        ang = math.radians(ANG[nome][attrs.index(a)])
        k = attrs.index(a) % 2
        ax, ay = x + (2.05 + 0.25*k) * math.cos(ang), y + (1.15 + 0.2*k) * math.sin(ang)
        L.append(f'{aid} [shape=ellipse, fontsize=11, label={lab}, height=0.35, margin="0.06,0.02", pos="{ax:.2f},{ay:.2f}!"];')
        L.append(f'{nome} -- {aid} [len=1.25, color="#777777"];')
for i, (r, x, y, e1, c1, e2, c2) in enumerate(R):
    rid = f'R{i}'
    L.append(f'{rid} [shape=diamond, style=filled, fillcolor="#fff4e8", color="#c25e10", fontsize=12, label="{r.strip()}", width=1.5, height=0.8, pos="{x},{y}!"];')
    L.append(f'{e1} -- {rid} [headlabel="", taillabel="{c1}", labeldistance=1.6];')
    L.append(f'{rid} -- {e2} [headlabel="{c2}", labeldistance=1.6];')
L.append('}')
open('mer.dot', 'w').write('\n'.join(L))
