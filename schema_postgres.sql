-- Retrofit - script do banco (PostgreSQL)
-- Mesmas tabelas do schema.sql; muda só o tipo das chaves (SERIAL).

DROP TABLE IF EXISTS alerta, refugo, parada, leitura, motivo_parada, maquina, usuario, fabrica;

CREATE TABLE fabrica (
    id      SERIAL PRIMARY KEY,
    nome    VARCHAR(100) NOT NULL,
    cnpj    VARCHAR(18)  NOT NULL UNIQUE,
    cidade  VARCHAR(80)  NOT NULL
);

CREATE TABLE usuario (
    id          SERIAL PRIMARY KEY,
    fabrica_id  INTEGER      NOT NULL REFERENCES fabrica(id),
    nome        VARCHAR(100) NOT NULL,
    email       VARCHAR(120) NOT NULL UNIQUE,
    senha_hash  VARCHAR(255) NOT NULL,
    perfil      VARCHAR(10)  NOT NULL CHECK (perfil IN ('admin', 'gestor', 'operador')),
    ativo       INTEGER      NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1))
);

CREATE TABLE maquina (
    id                SERIAL PRIMARY KEY,
    fabrica_id        INTEGER      NOT NULL REFERENCES fabrica(id),
    nome              VARCHAR(80)  NOT NULL,
    tipo              VARCHAR(40)  NOT NULL,
    ciclo_padrao_seg  REAL         NOT NULL CHECK (ciclo_padrao_seg > 0),
    temp_max          REAL,
    token             VARCHAR(64)  NOT NULL UNIQUE,
    ativa             INTEGER      NOT NULL DEFAULT 1 CHECK (ativa IN (0, 1))
);

CREATE TABLE motivo_parada (
    id         SERIAL PRIMARY KEY,
    descricao  VARCHAR(60) NOT NULL UNIQUE,
    planejada  INTEGER     NOT NULL CHECK (planejada IN (0, 1))
);

CREATE TABLE leitura (
    id           SERIAL PRIMARY KEY,
    maquina_id   INTEGER     NOT NULL REFERENCES maquina(id),
    data_hora    TIMESTAMP   NOT NULL,
    estado       VARCHAR(8)  NOT NULL CHECK (estado IN ('rodando', 'parada')),
    pecas        INTEGER     NOT NULL DEFAULT 0 CHECK (pecas >= 0),
    temperatura  REAL,
    corrente     REAL
);
CREATE INDEX ix_leitura_maquina_data ON leitura (maquina_id, data_hora);

CREATE TABLE parada (
    id          SERIAL PRIMARY KEY,
    maquina_id  INTEGER   NOT NULL REFERENCES maquina(id),
    inicio      TIMESTAMP NOT NULL,
    fim         TIMESTAMP,
    motivo_id   INTEGER   REFERENCES motivo_parada(id),
    usuario_id  INTEGER   REFERENCES usuario(id),
    observacao  VARCHAR(200)
);
CREATE UNIQUE INDEX ux_parada_aberta ON parada (maquina_id) WHERE fim IS NULL;

CREATE TABLE refugo (
    id          SERIAL PRIMARY KEY,
    maquina_id  INTEGER   NOT NULL REFERENCES maquina(id),
    usuario_id  INTEGER   NOT NULL REFERENCES usuario(id),
    data_hora   TIMESTAMP NOT NULL,
    quantidade  INTEGER   NOT NULL CHECK (quantidade > 0)
);

CREATE TABLE alerta (
    id            SERIAL PRIMARY KEY,
    maquina_id    INTEGER      NOT NULL REFERENCES maquina(id),
    tipo          VARCHAR(20)  NOT NULL CHECK (tipo IN ('parada_sem_motivo', 'temperatura')),
    mensagem      VARCHAR(200) NOT NULL,
    criado_em     TIMESTAMP    NOT NULL,
    resolvido_em  TIMESTAMP
);
CREATE UNIQUE INDEX ux_alerta_aberto ON alerta (maquina_id, tipo) WHERE resolvido_em IS NULL;

INSERT INTO motivo_parada (descricao, planejada) VALUES
    ('Setup / troca de ferramenta', 1),
    ('Manutenção preventiva', 1),
    ('Intervalo / refeição', 1),
    ('Falta de material', 0),
    ('Quebra / manutenção corretiva', 0),
    ('Falta de operador', 0),
    ('Problema de qualidade', 0),
    ('Outro', 0);
