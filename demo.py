"""Modo demonstração do Retrofit: tudo com dados fictícios.

    python demo.py          (no Windows: py demo.py)

1. Recria o banco com a fábrica, 5 usuários e as 7 máquinas do protótipo 3D.
2. Gera 24 h de histórico fictício (leituras, paradas com motivo, refugo e alertas).
3. Sobe o sistema em http://localhost:5000 e continua gerando leituras a cada 10 s,
   como se as peças estivessem instaladas. O login tem botões de um clique.

Nenhum dado aqui é medição real.
"""
import os
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import app as retrofit

HORAS_HISTORICO = 24
INTERVALO_AO_VIVO = 10  # segundos

# Comportamento de cada máquina: chance de parar e de voltar por minuto, temperatura normal
PERFIL = {
    'Torno 01':      {'parar': 0.020, 'voltar': 0.12, 'temp': 48},
    'Injetora 02':   {'parar': 0.012, 'voltar': 0.15, 'temp': 66},
    'Prensa 03':     {'parar': 0.030, 'voltar': 0.10, 'temp': 44},
    'Compressor 04': {'parar': 0.008, 'voltar': 0.20, 'temp': 72},
    'Serra 05':      {'parar': 0.040, 'voltar': 0.09, 'temp': 41},
    'Tear 06':       {'parar': 0.018, 'voltar': 0.14, 'temp': 38},
    'Forno 07':      {'parar': 0.006, 'voltar': 0.10, 'temp': 176},
}
PADRAO = {'parar': 0.02, 'voltar': 0.12, 'temp': 40}  # máquina cadastrada durante a demo
# Peso de cada motivo (ids do schema.sql): setup, preventiva, intervalo, material, quebra, operador, qualidade, outro
MOTIVOS = [1, 2, 3, 4, 5, 6, 7, 8]
PESOS = [18, 5, 10, 20, 15, 10, 12, 10]
FICAM_SEM_MOTIVO = {'Prensa 03', 'Serra 05'}  # para a demo mostrar alertas abertos
PARADA_AGORA = 'Serra 05'  # para a demo mostrar uma máquina parada


def passo(rng, est, m, segundos):
    """Sorteia a próxima leitura a partir do estado atual da máquina."""
    perfil = PERFIL.get(m['nome'], PADRAO)
    fator = segundos / 60
    if est['estado'] == 'rodando' and rng.random() < perfil['parar'] * fator:
        est['estado'] = 'parada'
    elif est['estado'] == 'parada' and rng.random() < perfil['voltar'] * fator:
        est['estado'] = 'rodando'
    alvo = perfil['temp'] if est['estado'] == 'rodando' else 28
    est['temp'] += (alvo - est['temp']) * 0.05 * fator + rng.uniform(-0.6, 0.6)
    if est['estado'] == 'rodando':
        est['acumulado'] += segundos / m['ciclo_padrao_seg'] * rng.uniform(0.80, 0.97)
        pecas = int(est['acumulado'])
        est['acumulado'] -= pecas
        corrente = round(rng.uniform(8, 12), 1)
    else:
        pecas, corrente = 0, round(rng.uniform(0.2, 0.8), 1)
    return est['estado'], pecas, round(est['temp'], 1), corrente


def gerar_historico(con, horas=HORAS_HISTORICO):
    agora = datetime.now().replace(microsecond=0)
    operadores = [r[0] for r in con.execute("SELECT id FROM usuario WHERE perfil = 'operador'")]
    for m in con.execute('SELECT * FROM maquina').fetchall():
        rng = random.Random(m['id'] * 101)
        est = {'estado': 'rodando', 'temp': PERFIL.get(m['nome'], PADRAO)['temp'], 'acumulado': 0.0}
        t = agora - timedelta(hours=horas)
        while t <= agora:
            leitura = passo(rng, est, m, 60)
            if m['nome'] == PARADA_AGORA and t >= agora - timedelta(minutes=7):
                est['estado'] = 'parada'  # a demo começa com esta máquina parada há 7 min
                leitura = ('parada', 0, leitura[2], 0.4)
            retrofit.processar_leitura(con, m, *leitura, t.strftime(retrofit.FMT))
            t += timedelta(minutes=1)
        # O operador informa o motivo das paradas (menos a última em algumas máquinas)
        paradas = [r[0] for r in con.execute('SELECT id FROM parada WHERE maquina_id = ? ORDER BY inicio',
                                             (m['id'],))]
        if m['nome'] in FICAM_SEM_MOTIVO:
            paradas = paradas[:-1]
        for pid in paradas:
            con.execute('UPDATE parada SET motivo_id = ?, usuario_id = ? WHERE id = ?',
                        (rng.choices(MOTIVOS, PESOS)[0], rng.choice(operadores), pid))
        if m['nome'] not in FICAM_SEM_MOTIVO:
            con.execute("UPDATE alerta SET resolvido_em = ? WHERE maquina_id = ? AND tipo = 'parada_sem_motivo' "
                        "AND resolvido_em IS NULL", (agora.strftime(retrofit.FMT), m['id']))
        else:  # o alerta aberto passa a ter a hora da parada que ficou sem motivo
            con.execute("UPDATE alerta SET criado_em = (SELECT MAX(inicio) FROM parada WHERE maquina_id = ? "
                        "AND motivo_id IS NULL) WHERE maquina_id = ? AND tipo = 'parada_sem_motivo' "
                        "AND resolvido_em IS NULL", (m['id'], m['id']))
        if m['nome'] != 'Forno 07':  # deixa só o alerta de temperatura do forno aberto
            con.execute("UPDATE alerta SET resolvido_em = ? WHERE maquina_id = ? AND tipo = 'temperatura' "
                        "AND resolvido_em IS NULL", (agora.strftime(retrofit.FMT), m['id']))
        # Refugo: 3 apontamentos de 1% a 3% da produção
        total = con.execute('SELECT SUM(pecas) FROM leitura WHERE maquina_id = ?', (m['id'],)).fetchone()[0] or 0
        for h in (horas * 0.8, horas * 0.45, horas * 0.15):
            qtd = max(1, round(total * rng.uniform(0.01, 0.03) / 3))
            quando = (agora - timedelta(hours=h)).strftime(retrofit.FMT)
            con.execute('INSERT INTO refugo (maquina_id, usuario_id, data_hora, quantidade) VALUES (?, ?, ?, ?)',
                        (m['id'], rng.choice(operadores), quando, qtd))
    con.commit()


def ao_vivo():
    """Continua enviando leituras enquanto o sistema roda."""
    con = sqlite3.connect(retrofit.app.config['DATABASE'], check_same_thread=False)
    con.row_factory = sqlite3.Row
    rng, estados = random.Random(), {}
    while True:
        time.sleep(INTERVALO_AO_VIVO)
        for m in con.execute('SELECT * FROM maquina WHERE ativa = 1').fetchall():
            if m['id'] not in estados:
                ult = con.execute('SELECT estado, temperatura FROM leitura WHERE maquina_id = ? '
                                  'ORDER BY data_hora DESC LIMIT 1', (m['id'],)).fetchone()
                estados[m['id']] = {'estado': ult['estado'] if ult else 'rodando',
                                    'temp': (ult['temperatura'] if ult and ult['temperatura'] else
                                             PERFIL.get(m['nome'], PADRAO)['temp']),
                                    'acumulado': 0.0}
            leitura = passo(rng, estados[m['id']], m, INTERVALO_AO_VIVO)
            retrofit.processar_leitura(con, m, *leitura, retrofit.agora())
        con.commit()


if __name__ == '__main__':
    retrofit.app.config['DEMO'] = True
    retrofit.init_db(demo=True)
    con = sqlite3.connect(retrofit.app.config['DATABASE'])
    con.row_factory = sqlite3.Row
    print(f'Gerando {HORAS_HISTORICO} h de dados fictícios para 7 máquinas...')
    gerar_historico(con)
    con.close()
    threading.Thread(target=ao_vivo, daemon=True).start()
    porta = int(os.environ.get('PORT', 5000))
    print(f'Pronto! Abra http://localhost:{porta}  (Ctrl + C para parar)')
    retrofit.app.run(host='0.0.0.0', port=porta, debug=False)
