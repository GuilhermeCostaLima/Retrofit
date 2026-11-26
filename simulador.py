"""Simulador da peça Retrofit: envia leituras para a API como a peça real enviaria.

Tempo real (uma leitura a cada 10 s):
    python simulador.py --token TOKEN

Gerar histórico das últimas 8 h de uma vez (para demonstração):
    python simulador.py --token TOKEN --historico 8

Os dados são aleatórios: servem só para testar e demonstrar o sistema.
"""
import argparse
import json
import random
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta


def enviar(url, token, leitura):
    req = urllib.request.Request(url, data=json.dumps(leitura).encode(), method='POST',
                                 headers={'Content-Type': 'application/json', 'X-Token': token})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def proxima(estado, temp, intervalo, ciclo):
    """Sorteia o próximo estado: ~3% de chance de parar a cada leitura, ~15% de voltar."""
    if estado == 'rodando' and random.random() < 0.03:
        estado = 'parada'
    elif estado == 'parada' and random.random() < 0.15:
        estado = 'rodando'
    if estado == 'rodando':
        pecas = max(0, round(intervalo / ciclo * random.uniform(0.75, 1.0)))
        temp = min(temp + random.uniform(-0.5, 0.8), 90)
        corrente = round(random.uniform(8, 12), 1)
    else:
        pecas = 0
        temp = max(temp - random.uniform(0.2, 1.0), 25)
        corrente = round(random.uniform(0.2, 0.8), 1)
    return estado, temp, {'estado': estado, 'pecas': pecas, 'temperatura': round(temp, 1), 'corrente': corrente}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='http://localhost:5000/api/leituras')
    ap.add_argument('--token', required=True)
    ap.add_argument('--ciclo', type=float, default=30, help='segundos por peça')
    ap.add_argument('--intervalo', type=int, default=10, help='segundos entre leituras')
    ap.add_argument('--historico', type=float, default=0, help='gera N horas para trás e sai')
    ap.add_argument('--semente', type=int, default=None)
    a = ap.parse_args()
    random.seed(a.semente)

    estado, temp = 'rodando', 40.0
    if a.historico:
        passo = 60  # uma leitura por minuto no histórico
        t = datetime.now() - timedelta(hours=a.historico)
        n = 0
        while t <= datetime.now():
            estado, temp, leitura = proxima(estado, temp, passo, a.ciclo)
            leitura['data_hora'] = t.strftime('%Y-%m-%d %H:%M:%S')
            enviar(a.url, a.token, leitura)
            t += timedelta(seconds=passo)
            n += 1
        print(f'{n} leituras enviadas')
        return
    while True:
        estado, temp, leitura = proxima(estado, temp, a.intervalo, a.ciclo)
        print(datetime.now().strftime('%H:%M:%S'), enviar(a.url, a.token, leitura), leitura)
        time.sleep(a.intervalo)


if __name__ == '__main__':
    main()
