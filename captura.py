import mysql.connector
from mysql.connector import Error
import datetime
import psutil
import time
import requests

DB_CONFIG = {
    'host': '44.214.19.72',
    'user': 'root',
    'password': 'urubu100',
    'database': 'cyberbeef',
    'port': 3306
}

ID_MAQUINA = 1
INTERVALO = 5
TOLERANCIA = 3 

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"

LIMITE_ALERTA = {
    "CPU": 80,
    "RAM": 85,
    "DISCO": 70
}

TIPOS_VALIDOS = {"CPU", "RAM", "DISCO", "REDE"}

MAPA_PARAMETROS_FALLBACK = {
    "CPU": 1,
    "RAM": 2,
    "DISCO": 3
}

CONTADORES = {
    "CPU": 0,
    "RAM": 0,
    "DISCO": 0
}


def enviar_slack(mensagem: str):
    try:
        resposta = requests.post(SLACK_WEBHOOK_URL, json={"text": mensagem}, timeout=10)
        if resposta.status_code != 200:
            print(f"Slack retornou HTTP {resposta.status_code}: {resposta.text}")
        else:
            print("Mensagem enviada ao Slack.")
    except Exception as e:
        print(f"Erro ao enviar Slack: {e}")


def conectar():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Erro na conexão com o banco: {e}")
        return None


def registrar_log(id_maquina, tipo_log_db, mensagem):
    db = conectar()
    if db is None:
        return

    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO log (id_maquina, tipo, mensagem)
            VALUES (%s, %s, %s)
        """, (id_maquina, tipo_log_db, mensagem))
        db.commit()
    except Error as e:
        print(f"Erro ao inserir log: {e}")
    finally:
        try:
            cursor.close()
            db.close()
        except:
            pass


def obter_id_parametro(tipo, id_maquina):
    tipo = tipo.strip().upper()
    db = conectar()
    if db is None:
        return MAPA_PARAMETROS_FALLBACK.get(tipo)

    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT idParametro FROM parametro
            WHERE UPPER(nivel) = %s AND idMaquina = %s
            LIMIT 1
        """, (tipo, id_maquina))
        row = cursor.fetchone()
        return row[0] if row else MAPA_PARAMETROS_FALLBACK.get(tipo)

    except Error:
        return MAPA_PARAMETROS_FALLBACK.get(tipo)

    finally:
        try:
            cursor.close()
            db.close()
        except:
            pass


def obter_ou_criar_componente(tipo, unidade, id_maquina):
    tipo = tipo.strip().upper()

    if tipo not in TIPOS_VALIDOS:
        return None

    db = conectar()
    if db is None:
        return None

    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT idComponente FROM componente
            WHERE UPPER(tipoComponente) = %s AND idMaquina = %s
            LIMIT 1
        """, (tipo, id_maquina))
        resultado = cursor.fetchone()
        if resultado:
            return resultado[0]

        cursor.execute("""
            INSERT INTO componente (tipoComponente, unidadeMedida, idMaquina)
            VALUES (%s, %s, %s)
        """, (tipo, unidade, id_maquina))
        db.commit()
        return cursor.lastrowid

    except Error as e:
        print(f"Erro ao obter ou criar componente '{tipo}': {e}")
        return None

    finally:
        try:
            cursor.close()
            db.close()
        except:
            pass


def inserir_leitura(id_componente, id_maquina, valor, tipo, unidade):
    db = conectar()
    if db is None:
        return None
    try:
        cursor = db.cursor()
        agora = datetime.datetime.now()

        cursor.execute("""
            INSERT INTO leitura (idComponente, idMaquina, dado, dthCaptura)
            VALUES (%s, %s, %s, %s)
        """, (id_componente, id_maquina, valor, agora))
        db.commit()

        id_leitura = cursor.lastrowid

        print(f"[{agora.strftime('%Y-%m-%d %H:%M:%S')}] {tipo:<7} | {valor:.2f}%")

        return id_leitura

    except Error as e:
        print(f"Erro ao inserir leitura: {e}")
        return None

    finally:
        try:
            cursor.close()
            db.close()
        except:
            pass


def registrar_alerta(id_leitura, id_componente, id_maquina, id_parametro, descricao):
    db = conectar()
    if db is None:
        return False

    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO alerta (idLeitura, idComponente, idMaquina, idParametro, descricao)
            VALUES (%s, %s, %s, %s, %s)
        """, (id_leitura, id_componente, id_maquina, id_parametro, descricao))
        db.commit()
        print(f"Alerta registrado no BD: {descricao} (idLeitura={id_leitura})")
        return True

    except Error as e:
        print(f"Erro ao registrar alerta: {e}")
        return False

    finally:
        try:
            cursor.close()
            db.close()
        except:
            pass


def capturar_metricas():
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_percent = psutil.virtual_memory().percent
    disco_percent = psutil.disk_usage('/').percent

    return {
        ("CPU", "%"): cpu_percent,
        ("RAM", "%"): ram_percent,
        ("DISCO", "%"): disco_percent
    }


def classificar_valor(tipo, valor):
    if valor >= LIMITE_ALERTA[tipo]:
        return "Critico", "CRITICO"
    else:
        return "Anormal", "ANORMAL"


def verificar_e_tratar_alerta(tipo, valor, id_leitura, id_componente):
    tipo = tipo.strip().upper()

    id_parametro = obter_id_parametro(tipo, ID_MAQUINA)
    classificacao_texto, nivel_log_db = classificar_valor(tipo, valor)

    mensagem_log = f"{tipo} = {valor:.2f}% -> {classificacao_texto}"
    registrar_log(ID_MAQUINA, nivel_log_db, mensagem_log)

    global CONTADORES

    if valor < LIMITE_ALERTA[tipo]:
        CONTADORES[tipo] = 0
        return

    CONTADORES[tipo] += 1

    print(f"{tipo}: {CONTADORES[tipo]}/{TOLERANCIA} leituras acima do limite")

    if CONTADORES[tipo] < TOLERANCIA:
        return

    descricao_alerta_bd = classificacao_texto

    sucesso_alerta = registrar_alerta(
        id_leitura,
        id_componente,
        ID_MAQUINA,
        id_parametro,
        descricao_alerta_bd
    )

    if sucesso_alerta:
        msg_slack = f"{classificacao_texto} — {tipo} atingiu {valor:.2f}%"

        if classificacao_texto == "Critico":
            enviar_slack(f":rotating_light: CRÍTICO — {msg_slack}")
        else:
            enviar_slack(f":warning: AVISO — {msg_slack}")

    CONTADORES[tipo] = 0


def iniciar_monitoramento():
    print("Iniciando monitoramento em tempo real... (Ctrl + C para parar)\n")
    while True:
        metricas = capturar_metricas()

        for (tipo, unidade), valor in metricas.items():
            id_comp = obter_ou_criar_componente(tipo, unidade, ID_MAQUINA)

            if id_comp:
                id_leitura = inserir_leitura(id_comp, ID_MAQUINA, valor, tipo, unidade)

                if id_leitura:
                    verificar_e_tratar_alerta(tipo, valor, id_leitura, id_comp)

        time.sleep(INTERVALO)


if __name__ == "__main__":
    iniciar_monitoramento()

