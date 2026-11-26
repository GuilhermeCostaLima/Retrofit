"""Retrofit - plataforma web (Flask + SQLite).

Rodar:
    pip install -r requirements.txt
    python demo.py                 # demonstração: 7 máquinas com dados fictícios, ao vivo
    python app.py init --demo      # ou: banco só com usuários e máquinas de demonstração
    python app.py                  # sobe em http://localhost:5000
"""
import io
import os
import secrets
import sqlite3
import sys
from datetime import datetime, timedelta
from functools import wraps

import qrcode
import qrcode.image.svg
from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
FMT = '%Y-%m-%d %H:%M:%S'
PERFIS = ('admin', 'gestor', 'operador')
SEM_SINAL_MIN = 5  # sem leitura há mais de 5 min = "sem sinal"
# As 7 máquinas do protótipo 3D: nome, tipo, ciclo padrão (s), temperatura máxima (°C)
MAQUINAS_DEMO = [('Torno 01', 'Torno', 45, 70), ('Injetora 02', 'Injetora', 30, 85),
                 ('Prensa 03', 'Prensa', 12, 65), ('Compressor 04', 'Compressor', 60, 95),
                 ('Serra 05', 'Serra', 25, 60), ('Tear 06', 'Tear', 20, 55),
                 ('Forno 07', 'Forno', 90, 180)]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get('SECRET_KEY', 'troque-esta-chave-em-producao'),
    DATABASE=os.environ.get('RETROFIT_DB', os.path.join(BASE, 'retrofit.db')),
    DEMO=False,  # True no modo demonstração (demo.py): mostra o login de um clique
)


# ---------------------------------------------------------------- banco
def db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db


@app.teardown_appcontext
def fechar_db(_erro):
    con = g.pop('db', None)
    if con is not None:
        con.close()


def init_db(demo=False):
    con = sqlite3.connect(app.config['DATABASE'])
    with open(os.path.join(BASE, 'schema.sql'), encoding='utf-8') as f:
        con.executescript(f.read())
    tokens = []
    if demo:
        # Dados fictícios de demonstração (nenhuma pessoa ou empresa real)
        con.execute("INSERT INTO fabrica (nome, cnpj, cidade) VALUES "
                    "('Metalúrgica Demonstração Ltda', '00.000.000/0001-00', 'Joinville')")
        for nome, email, perfil in [('Ana Ribeiro', 'admin@demo.com', 'admin'),
                                    ('Rafael Mendes', 'gestor@demo.com', 'gestor'),
                                    ('João Pereira', 'operador@demo.com', 'operador'),
                                    ('Bruna Costa', 'bruna@demo.com', 'operador'),
                                    ('Diego Alves', 'diego@demo.com', 'operador')]:
            con.execute('INSERT INTO usuario (fabrica_id, nome, email, senha_hash, perfil) '
                        'VALUES (1, ?, ?, ?, ?)',
                        (nome, email, generate_password_hash('retrofit123'), perfil))
        for nome, tipo, ciclo, tmax in MAQUINAS_DEMO:
            tok = secrets.token_hex(16)
            con.execute('INSERT INTO maquina (fabrica_id, nome, tipo, ciclo_padrao_seg, temp_max, token) '
                        'VALUES (1, ?, ?, ?, ?, ?)', (nome, tipo, ciclo, tmax, tok))
            tokens.append((nome, tok))
    con.commit()
    con.close()
    return tokens


def agora():
    return datetime.now().strftime(FMT)


def para_dt(texto):
    return datetime.strptime(texto, FMT)


# ---------------------------------------------------------------- acesso
def login_obrigatorio(*perfis):
    """RF02: libera a rota só para os perfis informados (vazio = qualquer perfil)."""
    def decorador(func):
        @wraps(func)
        def envolvida(*args, **kwargs):
            uid = session.get('uid')
            if uid is None:
                return redirect(url_for('login', proximo=request.path))
            g.user = db().execute('SELECT * FROM usuario WHERE id = ? AND ativo = 1', (uid,)).fetchone()
            if g.user is None:
                session.clear()
                return redirect(url_for('login'))
            if perfis and g.user['perfil'] not in perfis:
                abort(403)
            return func(*args, **kwargs)
        return envolvida
    return decorador


def maquina_da_fabrica(mid):
    """RN03: só devolve máquinas da fábrica do usuário logado."""
    m = db().execute('SELECT * FROM maquina WHERE id = ? AND fabrica_id = ?',
                     (mid, g.user['fabrica_id'])).fetchone()
    if m is None:
        abort(404)
    return m


@app.context_processor
def usuario_no_template():
    return {'usuario': g.get('user'), 'demo': app.config['DEMO']}


# ---------------------------------------------------------------- RF01 login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        u = db().execute('SELECT * FROM usuario WHERE email = ? AND ativo = 1', (email,)).fetchone()
        if u and check_password_hash(u['senha_hash'], senha):
            session.clear()
            session['uid'] = u['id']
            proximo = request.args.get('proximo', '')
            return redirect(proximo if proximo.startswith('/') else url_for('inicio'))
        flash('E-mail ou senha inválidos.')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ---------------------------------------------------------------- RF10 visão geral
@app.route('/')
@login_obrigatorio()
def inicio():
    con = db()
    maquinas = con.execute('SELECT * FROM maquina WHERE fabrica_id = ? AND ativa = 1 ORDER BY nome',
                           (g.user['fabrica_id'],)).fetchall()
    fim = datetime.now().replace(microsecond=0)
    inicio_turno = fim - timedelta(hours=8)
    limite = (fim - timedelta(minutes=SEM_SINAL_MIN)).strftime(FMT)
    linhas = []
    for m in maquinas:
        ult = con.execute('SELECT * FROM leitura WHERE maquina_id = ? ORDER BY data_hora DESC LIMIT 1',
                          (m['id'],)).fetchone()
        if ult is None or ult['data_hora'] < limite:
            estado = 'sem sinal'
        else:
            estado = ult['estado']
        alertas = con.execute('SELECT COUNT(*) FROM alerta WHERE maquina_id = ? AND resolvido_em IS NULL',
                              (m['id'],)).fetchone()[0]
        linhas.append({'m': m, 'estado': estado, 'ultima': ult, 'alertas': alertas,
                       'ind': indicadores(con, m, inicio_turno, fim),
                       'faixa': linha_do_tempo(con, m['id'], inicio_turno, fim)})
    oees = [l['ind']['oee'] for l in linhas if l['ind']['oee'] is not None]
    resumo = {'total': len(linhas),
              'rodando': sum(l['estado'] == 'rodando' for l in linhas),
              'paradas': sum(l['estado'] == 'parada' for l in linhas),
              'alertas': sum(l['alertas'] for l in linhas),
              'oee': sum(oees) / len(oees) if oees else None,
              'pecas': sum(l['ind']['pecas'] for l in linhas)}
    return render_template('inicio.html', linhas=linhas, resumo=resumo)


# ---------------------------------------------------------------- RF07 / RF08 tela do operador (QR)
@app.route('/operador/<int:mid>')
@login_obrigatorio('operador', 'gestor', 'admin')
def operador(mid):
    m = maquina_da_fabrica(mid)
    con = db()
    pendentes = con.execute('SELECT * FROM parada WHERE maquina_id = ? AND motivo_id IS NULL '
                            'ORDER BY inicio DESC LIMIT 10', (mid,)).fetchall()
    motivos = con.execute('SELECT * FROM motivo_parada ORDER BY planejada DESC, id').fetchall()
    ult = con.execute('SELECT * FROM leitura WHERE maquina_id = ? ORDER BY data_hora DESC LIMIT 1',
                      (mid,)).fetchone()
    return render_template('operador.html', m=m, pendentes=pendentes, motivos=motivos, ultima=ult)


@app.route('/operador/<int:mid>/motivo', methods=['POST'])
@login_obrigatorio('operador', 'gestor', 'admin')
def informar_motivo(mid):
    maquina_da_fabrica(mid)
    con = db()
    parada = con.execute('SELECT * FROM parada WHERE id = ? AND maquina_id = ?',
                         (request.form.get('parada_id', type=int), mid)).fetchone()
    motivo = con.execute('SELECT * FROM motivo_parada WHERE id = ?',
                         (request.form.get('motivo_id', type=int),)).fetchone()
    if parada is None or motivo is None:
        flash('Parada ou motivo inválido.')
        return redirect(url_for('operador', mid=mid))
    con.execute('UPDATE parada SET motivo_id = ?, usuario_id = ?, observacao = ? WHERE id = ?',
                (motivo['id'], g.user['id'], request.form.get('observacao', '').strip()[:200] or None,
                 parada['id']))
    # RN07: alerta resolvido quando não restam paradas sem motivo
    restantes = con.execute('SELECT COUNT(*) FROM parada WHERE maquina_id = ? AND motivo_id IS NULL',
                            (mid,)).fetchone()[0]
    if restantes == 0:
        con.execute("UPDATE alerta SET resolvido_em = ? WHERE maquina_id = ? "
                    "AND tipo = 'parada_sem_motivo' AND resolvido_em IS NULL", (agora(), mid))
    con.commit()
    flash(f'Motivo registrado: {motivo["descricao"]}.')
    return redirect(url_for('operador', mid=mid))


@app.route('/operador/<int:mid>/refugo', methods=['POST'])
@login_obrigatorio('operador', 'gestor', 'admin')
def apontar_refugo(mid):
    maquina_da_fabrica(mid)
    con = db()
    qtd = request.form.get('quantidade', type=int)
    desde = (datetime.now() - timedelta(hours=8)).strftime(FMT)
    produzidas = con.execute('SELECT COALESCE(SUM(pecas), 0) FROM leitura WHERE maquina_id = ? AND data_hora > ?',
                             (mid, desde)).fetchone()[0]
    ja_refugadas = con.execute('SELECT COALESCE(SUM(quantidade), 0) FROM refugo WHERE maquina_id = ? AND data_hora > ?',
                               (mid, desde)).fetchone()[0]
    # RN09
    if qtd is None or qtd <= 0:
        flash('Informe uma quantidade inteira maior que zero.')
    elif qtd + ja_refugadas > produzidas:
        flash(f'Refugo maior que o produzido nas últimas 8 h ({produzidas} peças, {ja_refugadas} já refugadas).')
    else:
        con.execute('INSERT INTO refugo (maquina_id, usuario_id, data_hora, quantidade) VALUES (?, ?, ?, ?)',
                    (mid, g.user['id'], agora(), qtd))
        con.commit()
        flash(f'Refugo de {qtd} peça(s) registrado.')
    return redirect(url_for('operador', mid=mid))


# ---------------------------------------------------------------- RF11 painel e indicadores
def indicadores(con, maquina, inicio, fim):
    """RN08 / RN11: disponibilidade, performance, qualidade e OEE no período [inicio, fim]."""
    total = (fim - inicio).total_seconds()
    paradas = con.execute(
        'SELECT p.inicio, p.fim, COALESCE(mp.planejada, 0) AS planejada FROM parada p '
        'LEFT JOIN motivo_parada mp ON mp.id = p.motivo_id '
        'WHERE p.maquina_id = ? AND p.inicio < ? AND (p.fim IS NULL OR p.fim > ?)',
        (maquina['id'], fim.strftime(FMT), inicio.strftime(FMT))).fetchall()
    planejada = nao_planejada = 0.0
    for p in paradas:
        ini = max(para_dt(p['inicio']), inicio)
        fin = min(para_dt(p['fim']) if p['fim'] else fim, fim)
        dur = max((fin - ini).total_seconds(), 0)
        if p['planejada']:
            planejada += dur
        else:
            nao_planejada += dur
    tempo_planejado = total - planejada
    operando = tempo_planejado - nao_planejada
    periodo = (maquina['id'], inicio.strftime(FMT), fim.strftime(FMT))
    pecas = con.execute('SELECT COALESCE(SUM(pecas), 0) FROM leitura '
                        'WHERE maquina_id = ? AND data_hora > ? AND data_hora <= ?', periodo).fetchone()[0]
    refugo = con.execute('SELECT COALESCE(SUM(quantidade), 0) FROM refugo '
                         'WHERE maquina_id = ? AND data_hora > ? AND data_hora <= ?', periodo).fetchone()[0]
    disp = operando / tempo_planejado if tempo_planejado > 0 else 0.0
    perf = min(1.0, pecas * maquina['ciclo_padrao_seg'] / operando) if operando > 0 else 0.0
    qual = (pecas - refugo) / pecas if pecas > 0 else None
    oee = disp * perf * qual if qual is not None else None
    return {'disponibilidade': disp, 'performance': perf, 'qualidade': qual, 'oee': oee,
            'pecas': pecas, 'refugo': refugo, 'parado_min': nao_planejada / 60,
            'planejada_min': planejada / 60}


def _paradas_no_periodo(con, mid, inicio, fim):
    rows = con.execute(
        'SELECT p.inicio, p.fim, p.motivo_id, mp.descricao, COALESCE(mp.planejada, 0) AS planejada FROM parada p '
        'LEFT JOIN motivo_parada mp ON mp.id = p.motivo_id '
        'WHERE p.maquina_id = ? AND p.inicio < ? AND (p.fim IS NULL OR p.fim > ?) ORDER BY p.inicio',
        (mid, fim.strftime(FMT), inicio.strftime(FMT))).fetchall()
    for p in rows:
        ini = max(para_dt(p['inicio']), inicio)
        fin = min(para_dt(p['fim']) if p['fim'] else fim, fim)
        tipo = 'semmotivo' if p['motivo_id'] is None else ('planejada' if p['planejada'] else 'naoplanejada')
        yield p, ini, max((fin - ini).total_seconds(), 0), tipo


def linha_do_tempo(con, mid, inicio, fim):
    """Faixas de parada no período, em % da largura, para a barra de estados."""
    total = (fim - inicio).total_seconds()
    return [{'x': round((ini - inicio).total_seconds() / total * 100, 2),
             'w': round(max(dur / total * 100, 0.4), 2), 'tipo': tipo}
            for _p, ini, dur, tipo in _paradas_no_periodo(con, mid, inicio, fim)]


def paradas_por_motivo(con, mid, inicio, fim):
    """Minutos parados por motivo, do maior para o menor (Pareto)."""
    soma = {}
    for p, _ini, dur, tipo in _paradas_no_periodo(con, mid, inicio, fim):
        chave = (p['descricao'] or 'Sem motivo', tipo)
        soma[chave] = soma.get(chave, 0) + dur / 60
    lista = sorted(({'motivo': k[0], 'tipo': k[1], 'min': v} for k, v in soma.items()),
                   key=lambda x: -x['min'])
    maior = max([x['min'] for x in lista] + [1])
    for x in lista:
        x['largura'] = round(x['min'] / maior * 100, 1)
    return lista


def producao_por_hora(con, mid, inicio, fim):
    """Peças por hora no período, para o gráfico de barras."""
    por_hora = dict(con.execute(
        'SELECT substr(data_hora, 1, 13), SUM(pecas) FROM leitura '
        'WHERE maquina_id = ? AND data_hora > ? AND data_hora <= ? GROUP BY 1',
        (mid, inicio.strftime(FMT), fim.strftime(FMT))).fetchall())
    horas, h = [], inicio.replace(minute=0, second=0)
    while h <= fim:
        horas.append({'rotulo': h.strftime('%Hh'), 'valor': por_hora.get(h.strftime('%Y-%m-%d %H'), 0)})
        h += timedelta(hours=1)
    maior = max([x['valor'] for x in horas] + [1])
    passo = max(1, len(horas) // 12)  # no máximo ~12 rótulos no eixo
    for i, x in enumerate(horas):
        x['altura'] = round(x['valor'] / maior * 100, 1)
        x['mostrar'] = i % passo == 0
    return horas


def serie_temperatura(con, m, inicio, fim, largura=600, altura=110):
    """Média de temperatura a cada 10 min, como pontos de uma linha SVG."""
    vals = [r[1] for r in con.execute(
        'SELECT substr(data_hora, 1, 15) AS bloco, AVG(temperatura) FROM leitura '
        'WHERE maquina_id = ? AND data_hora > ? AND data_hora <= ? AND temperatura IS NOT NULL '
        'GROUP BY bloco ORDER BY bloco', (m['id'], inicio.strftime(FMT), fim.strftime(FMT)))]
    if len(vals) < 2:
        return None
    limites = vals + ([m['temp_max']] if m['temp_max'] is not None else [])
    lo, hi = min(limites) - 2, max(limites) + 2
    y = lambda v: round(altura - (v - lo) / (hi - lo) * altura, 1)
    pontos = ' '.join(f'{round(i / (len(vals) - 1) * largura, 1)},{y(v)}' for i, v in enumerate(vals))
    return {'pontos': pontos, 'largura': largura, 'altura': altura,
            'y_max': y(m['temp_max']) if m['temp_max'] is not None else None,
            'atual': vals[-1], 'menor': min(vals), 'maior': max(vals)}


@app.route('/maquina/<int:mid>')
@login_obrigatorio('gestor', 'admin')
def painel(mid):
    m = maquina_da_fabrica(mid)
    horas = min(max(request.args.get('horas', 8, type=int), 1), 168)
    fim = datetime.now().replace(microsecond=0)
    inicio = fim - timedelta(hours=horas)
    con = db()
    ind = indicadores(con, m, inicio, fim)
    paradas = con.execute(
        'SELECT p.*, mp.descricao AS motivo, mp.planejada, u.nome AS quem FROM parada p '
        'LEFT JOIN motivo_parada mp ON mp.id = p.motivo_id LEFT JOIN usuario u ON u.id = p.usuario_id '
        'WHERE p.maquina_id = ? AND (p.fim IS NULL OR p.fim > ?) ORDER BY p.inicio DESC',
        (mid, inicio.strftime(FMT))).fetchall()
    alertas = con.execute('SELECT * FROM alerta WHERE maquina_id = ? AND resolvido_em IS NULL '
                          'ORDER BY criado_em DESC', (mid,)).fetchall()
    ult = con.execute('SELECT * FROM leitura WHERE maquina_id = ? ORDER BY data_hora DESC LIMIT 1',
                      (mid,)).fetchone()
    return render_template('painel.html', m=m, ind=ind, paradas=paradas, alertas=alertas,
                           ultima=ult, horas=horas,
                           faixa=linha_do_tempo(con, mid, inicio, fim),
                           motivos=paradas_por_motivo(con, mid, inicio, fim),
                           producao=producao_por_hora(con, mid, inicio, fim),
                           temp=serie_temperatura(con, m, inicio, fim),
                           inicio=inicio, fim=fim)


@app.route('/alerta/<int:aid>/resolver', methods=['POST'])
@login_obrigatorio('gestor', 'admin')
def resolver_alerta(aid):
    a = db().execute('SELECT a.* FROM alerta a JOIN maquina m ON m.id = a.maquina_id '
                     'WHERE a.id = ? AND m.fabrica_id = ?', (aid, g.user['fabrica_id'])).fetchone()
    if a is None:
        abort(404)
    db().execute('UPDATE alerta SET resolvido_em = ? WHERE id = ?', (agora(), aid))
    db().commit()
    return redirect(url_for('painel', mid=a['maquina_id']))


# ---------------------------------------------------------------- RF03 usuários
@app.route('/admin/usuarios', methods=['GET', 'POST'])
@login_obrigatorio('admin')
def admin_usuarios():
    con = db()
    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        perfil = request.form.get('perfil', '')
        if not nome or '@' not in email or perfil not in PERFIS:
            flash('Preencha nome, e-mail válido e perfil.')
        elif len(senha) < 8:  # RN02
            flash('A senha deve ter no mínimo 8 caracteres.')
        elif con.execute('SELECT 1 FROM usuario WHERE email = ?', (email,)).fetchone():  # RN01
            flash('Este e-mail já está cadastrado.')
        else:
            con.execute('INSERT INTO usuario (fabrica_id, nome, email, senha_hash, perfil) VALUES (?, ?, ?, ?, ?)',
                        (g.user['fabrica_id'], nome, email, generate_password_hash(senha), perfil))
            con.commit()
            flash(f'Usuário {nome} cadastrado.')
            return redirect(url_for('admin_usuarios'))
    usuarios = con.execute('SELECT * FROM usuario WHERE fabrica_id = ? ORDER BY nome',
                           (g.user['fabrica_id'],)).fetchall()
    return render_template('admin_usuarios.html', usuarios=usuarios, perfis=PERFIS)


@app.route('/admin/usuarios/<int:uid>/ativo', methods=['POST'])
@login_obrigatorio('admin')
def alternar_usuario(uid):
    if uid == g.user['id']:
        flash('Você não pode desativar o próprio usuário.')
    else:
        db().execute('UPDATE usuario SET ativo = 1 - ativo WHERE id = ? AND fabrica_id = ?',
                     (uid, g.user['fabrica_id']))
        db().commit()
    return redirect(url_for('admin_usuarios'))


# ---------------------------------------------------------------- RF04 máquinas
def ler_form_maquina():
    nome = request.form.get('nome', '').strip()
    tipo = request.form.get('tipo', '').strip()
    ciclo = request.form.get('ciclo_padrao_seg', type=float)
    tmax = request.form.get('temp_max', type=float)
    if not nome or not tipo:
        return None, 'Preencha nome e tipo.'
    if ciclo is None or ciclo <= 0:  # RN05
        return None, 'O tempo de ciclo padrão deve ser maior que zero.'
    return (nome, tipo, ciclo, tmax), None


@app.route('/admin/maquinas', methods=['GET', 'POST'])
@login_obrigatorio('admin')
def admin_maquinas():
    con = db()
    if request.method == 'POST':
        dados, erro = ler_form_maquina()
        if erro:
            flash(erro)
        else:
            cur = con.execute('INSERT INTO maquina (fabrica_id, nome, tipo, ciclo_padrao_seg, temp_max, token) '
                              'VALUES (?, ?, ?, ?, ?, ?)', (g.user['fabrica_id'], *dados, secrets.token_hex(16)))
            con.commit()
            flash(f'Máquina {dados[0]} cadastrada. Configure o token na peça.')
            return redirect(url_for('admin_maquina', mid=cur.lastrowid))
    maquinas = con.execute('SELECT * FROM maquina WHERE fabrica_id = ? ORDER BY nome',
                           (g.user['fabrica_id'],)).fetchall()
    return render_template('admin_maquinas.html', maquinas=maquinas)


@app.route('/admin/maquinas/<int:mid>', methods=['GET', 'POST'])
@login_obrigatorio('admin')
def admin_maquina(mid):
    m = maquina_da_fabrica(mid)
    if request.method == 'POST':
        if request.form.get('acao') == 'ativa':
            db().execute('UPDATE maquina SET ativa = 1 - ativa WHERE id = ?', (mid,))
            db().commit()
        else:
            dados, erro = ler_form_maquina()
            if erro:
                flash(erro)
            else:
                db().execute('UPDATE maquina SET nome = ?, tipo = ?, ciclo_padrao_seg = ?, temp_max = ? WHERE id = ?',
                             (*dados, mid))
                db().commit()
                flash('Máquina atualizada.')
        return redirect(url_for('admin_maquina', mid=mid))
    return render_template('admin_maquina.html', m=m,
                           link_qr=url_for('operador', mid=mid, _external=True))


@app.route('/maquina/<int:mid>/qr.svg')
@login_obrigatorio('admin', 'gestor')
def qr_maquina(mid):
    maquina_da_fabrica(mid)
    # O QR leva para a tela do operador; o token da peça nunca vai no QR.
    img = qrcode.make(url_for('operador', mid=mid, _external=True),
                      image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), mimetype='image/svg+xml')


# ---------------------------------------------------------------- RF05 / RF06 / RF09 API da peça
def abrir_alerta(con, mid, tipo, mensagem, quando):
    """RN10: só um alerta aberto por tipo em cada máquina."""
    existe = con.execute('SELECT 1 FROM alerta WHERE maquina_id = ? AND tipo = ? AND resolvido_em IS NULL',
                         (mid, tipo)).fetchone()
    if not existe:
        con.execute('INSERT INTO alerta (maquina_id, tipo, mensagem, criado_em) VALUES (?, ?, ?, ?)',
                    (mid, tipo, mensagem, quando))


@app.route('/api/leituras', methods=['POST'])
def receber_leitura():
    con = db()
    m = con.execute('SELECT * FROM maquina WHERE token = ? AND ativa = 1',
                    (request.headers.get('X-Token', ''),)).fetchone()
    if m is None:  # RN04
        return jsonify(erro='token inválido ou máquina inativa'), 401
    d = request.get_json(silent=True) or {}
    estado = d.get('estado')
    if estado not in ('rodando', 'parada'):
        return jsonify(erro="estado deve ser 'rodando' ou 'parada'"), 400
    try:
        pecas = int(d.get('pecas', 0))
        temperatura = None if d.get('temperatura') is None else float(d['temperatura'])
        corrente = None if d.get('corrente') is None else float(d['corrente'])
        quando = d.get('data_hora') or agora()  # a peça manda a própria hora (guarda leituras se cair a rede)
        para_dt(quando)
    except (TypeError, ValueError):
        return jsonify(erro='campos com formato inválido'), 400
    if pecas < 0:
        return jsonify(erro='pecas não pode ser negativo'), 400
    processar_leitura(con, m, estado, pecas, temperatura, corrente, quando)
    con.commit()
    return jsonify(ok=True, parada_aberta=(estado == 'parada')), 201


def processar_leitura(con, m, estado, pecas, temperatura, corrente, quando):
    """Grava a leitura e atualiza paradas e alertas. Usada pela API e pelo modo demo."""
    con.execute('INSERT INTO leitura (maquina_id, data_hora, estado, pecas, temperatura, corrente) '
                'VALUES (?, ?, ?, ?, ?, ?)', (m['id'], quando, estado, pecas, temperatura, corrente))
    aberta = con.execute('SELECT id FROM parada WHERE maquina_id = ? AND fim IS NULL', (m['id'],)).fetchone()
    # RN06
    if estado == 'parada' and aberta is None:
        con.execute('INSERT INTO parada (maquina_id, inicio) VALUES (?, ?)', (m['id'], quando))
        abrir_alerta(con, m['id'], 'parada_sem_motivo', f'{m["nome"]} parou: informe o motivo.', quando)  # RN07
    elif estado == 'rodando' and aberta is not None:
        con.execute('UPDATE parada SET fim = ? WHERE id = ?', (quando, aberta['id']))
    # RN10
    if temperatura is not None and m['temp_max'] is not None and temperatura > m['temp_max']:
        abrir_alerta(con, m['id'], 'temperatura',
                     f'Temperatura {temperatura:.1f} °C acima do limite de {m["temp_max"]:.0f} °C.', quando)


# ---------------------------------------------------------------- filtros de template
@app.template_filter('pct')
def pct(v):
    return '—' if v is None else f'{v * 100:.1f}%'


@app.template_filter('hora')
def hora(texto):
    return '—' if not texto else para_dt(texto).strftime('%d/%m %H:%M')


@app.template_filter('duracao')
def duracao(minutos):
    minutos = int(round(minutos))
    return f'{minutos // 60} h {minutos % 60:02d} min' if minutos >= 60 else f'{minutos} min'


@app.template_filter('minutos_desde')
def minutos_desde(texto):
    return max((datetime.now() - para_dt(texto)).total_seconds() / 60, 0)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'init':
        for nome, tok in init_db(demo='--demo' in sys.argv):
            print(f'{nome}: token da peça = {tok}')
        print('Banco criado em', app.config['DATABASE'])
    else:
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
