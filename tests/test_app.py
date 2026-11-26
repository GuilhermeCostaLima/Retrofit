"""Casos de teste CT01-CT15 (ver documento de entrega, seção 7)."""
from datetime import datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

import app as retrofit

FMT = retrofit.FMT


@pytest.fixture
def cliente(tmp_path):
    retrofit.app.config.update(TESTING=True, DATABASE=str(tmp_path / 'teste.db'))
    retrofit.init_db(demo=True)
    with retrofit.app.test_client() as c:
        yield c


def con():
    import sqlite3
    c = sqlite3.connect(retrofit.app.config['DATABASE'])
    c.row_factory = sqlite3.Row
    return c


def entrar(c, email, senha='retrofit123'):
    return c.post('/login', data={'email': email, 'senha': senha})


def token(mid=1):
    return con().execute('SELECT token FROM maquina WHERE id = ?', (mid,)).fetchone()[0]


def leitura(c, estado, quando=None, tok=None, **extra):
    corpo = {'estado': estado, 'pecas': extra.pop('pecas', 0), **extra}
    if quando:
        corpo['data_hora'] = quando
    return c.post('/api/leituras', json=corpo, headers={'X-Token': tok or token()})


# UC01 ---------------------------------------------------------------------------
def test_ct01_login_valido(cliente):
    r = entrar(cliente, 'gestor@demo.com')
    assert r.status_code == 302 and r.headers['Location'] == '/'


def test_ct02_login_senha_errada(cliente):
    r = entrar(cliente, 'gestor@demo.com', 'errada123')
    assert r.status_code == 200 and 'E-mail ou senha inválidos' in r.get_data(as_text=True)


# UC01 / RF02 --------------------------------------------------------------------
def test_ct03_operador_nao_acessa_admin(cliente):
    entrar(cliente, 'operador@demo.com')
    assert cliente.get('/admin/usuarios').status_code == 403
    assert cliente.get('/maquina/1').status_code == 403


# UC02 ---------------------------------------------------------------------------
def test_ct04_email_duplicado_recusado(cliente):
    entrar(cliente, 'admin@demo.com')
    r = cliente.post('/admin/usuarios', data={'nome': 'Outro', 'email': 'gestor@demo.com',
                                              'senha': '12345678', 'perfil': 'operador'})
    assert 'já está cadastrado' in r.get_data(as_text=True)


def test_ct05_senha_curta_recusada(cliente):
    entrar(cliente, 'admin@demo.com')
    r = cliente.post('/admin/usuarios', data={'nome': 'Novo', 'email': 'novo@demo.com',
                                              'senha': '1234567', 'perfil': 'operador'})
    assert 'mínimo 8 caracteres' in r.get_data(as_text=True)
    assert con().execute("SELECT COUNT(*) FROM usuario WHERE email = 'novo@demo.com'").fetchone()[0] == 0


# UC03 ---------------------------------------------------------------------------
def test_ct06_maquina_ciclo_zero_recusada(cliente):
    entrar(cliente, 'admin@demo.com')
    r = cliente.post('/admin/maquinas', data={'nome': 'Serra', 'tipo': 'Serra', 'ciclo_padrao_seg': '0'})
    assert 'maior que zero' in r.get_data(as_text=True)


# UC04 ---------------------------------------------------------------------------
def test_ct07_leitura_token_invalido(cliente):
    assert leitura(cliente, 'rodando', tok='token-falso').status_code == 401


def test_ct08_parada_abre_parada_e_alerta(cliente):
    assert leitura(cliente, 'parada').status_code == 201
    c = con()
    assert c.execute('SELECT COUNT(*) FROM parada WHERE maquina_id = 1 AND fim IS NULL').fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM alerta WHERE maquina_id = 1 AND tipo = 'parada_sem_motivo' "
                     "AND resolvido_em IS NULL").fetchone()[0] == 1


def test_ct09_segunda_leitura_parada_nao_duplica(cliente):
    leitura(cliente, 'parada')
    leitura(cliente, 'parada')
    assert con().execute('SELECT COUNT(*) FROM parada WHERE maquina_id = 1').fetchone()[0] == 1


def test_ct10_rodando_fecha_parada(cliente):
    leitura(cliente, 'parada', '2026-11-20 10:00:00')
    leitura(cliente, 'rodando', '2026-11-20 10:12:00')
    p = con().execute('SELECT inicio, fim FROM parada WHERE maquina_id = 1').fetchone()
    assert (p['inicio'], p['fim']) == ('2026-11-20 10:00:00', '2026-11-20 10:12:00')


# UC05 ---------------------------------------------------------------------------
def test_ct11_motivo_resolve_alerta(cliente):
    leitura(cliente, 'parada')
    pid = con().execute('SELECT id FROM parada WHERE maquina_id = 1').fetchone()[0]
    entrar(cliente, 'operador@demo.com')
    cliente.post('/operador/1/motivo', data={'parada_id': pid, 'motivo_id': 4})
    c = con()
    assert c.execute('SELECT motivo_id FROM parada WHERE id = ?', (pid,)).fetchone()[0] == 4
    assert c.execute("SELECT COUNT(*) FROM alerta WHERE maquina_id = 1 AND resolvido_em IS NULL").fetchone()[0] == 0


# UC06 ---------------------------------------------------------------------------
def test_ct12_refugo_maior_que_produzido(cliente):
    leitura(cliente, 'rodando', pecas=10)
    entrar(cliente, 'operador@demo.com')
    r = cliente.post('/operador/1/refugo', data={'quantidade': 11}, follow_redirects=True)
    assert 'Refugo maior que o produzido' in r.get_data(as_text=True)
    r = cliente.post('/operador/1/refugo', data={'quantidade': 3}, follow_redirects=True)
    assert 'Refugo de 3 peça(s) registrado' in r.get_data(as_text=True)


# UC04 / RN10 --------------------------------------------------------------------
def test_ct13_temperatura_gera_um_alerta(cliente):
    leitura(cliente, 'rodando', temperatura=75)   # Torno 01: máximo 70 °C
    leitura(cliente, 'rodando', temperatura=78)
    assert con().execute("SELECT COUNT(*) FROM alerta WHERE maquina_id = 1 AND tipo = 'temperatura'").fetchone()[0] == 1


# RN03 ---------------------------------------------------------------------------
def test_ct14_usuario_de_outra_fabrica(cliente):
    c = con()
    c.execute("INSERT INTO fabrica (nome, cnpj, cidade) VALUES ('Outra', '11.111.111/0001-11', 'Blumenau')")
    c.execute("INSERT INTO usuario (fabrica_id, nome, email, senha_hash, perfil) VALUES (2, 'Gestor B', 'b@outra.com', ?, 'gestor')",
              (generate_password_hash('retrofit123'),))
    c.commit()
    entrar(cliente, 'b@outra.com')
    assert cliente.get('/maquina/1').status_code == 404


# UC07 / RN08 / RN11 -------------------------------------------------------------
def test_ct15_calculo_oee(cliente):
    """8 h de período, ciclo de 30 s (Injetora 02, id 2).
    Parada não planejada de 60 min e parada planejada de 30 min; 702 peças, 27 refugos.
    Esperado: D = 23400/27000 = 86,7%; P = 702*30/23400 = 90%; Q = 675/702 = 96,2%; OEE = 75%."""
    tok = token(2)
    leitura(cliente, 'rodando', '2026-11-20 08:00:00', tok, pecas=702)
    leitura(cliente, 'parada', '2026-11-20 09:00:00', tok)
    leitura(cliente, 'rodando', '2026-11-20 10:00:00', tok)
    leitura(cliente, 'parada', '2026-11-20 12:00:00', tok)
    leitura(cliente, 'rodando', '2026-11-20 12:30:00', tok)
    c = con()
    c.execute('UPDATE parada SET motivo_id = 5 WHERE inicio = ?', ('2026-11-20 09:00:00',))  # corretiva
    c.execute('UPDATE parada SET motivo_id = 3 WHERE inicio = ?', ('2026-11-20 12:00:00',))  # intervalo
    c.execute("INSERT INTO refugo (maquina_id, usuario_id, data_hora, quantidade) VALUES (2, 3, '2026-11-20 13:00:00', 27)")
    c.commit()
    m = c.execute('SELECT * FROM maquina WHERE id = 2').fetchone()
    ind = retrofit.indicadores(c, m, datetime(2026, 11, 20, 7, 59, 0), datetime(2026, 11, 20, 15, 59, 0))
    assert ind['disponibilidade'] == pytest.approx(23400 / 27000)
    assert ind['performance'] == pytest.approx(0.9)
    assert ind['qualidade'] == pytest.approx(675 / 702)
    assert ind['oee'] == pytest.approx(0.75)
