import mysql.connector
from mysql.connector import Error
import datetime
import psutil
import time
import requests

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'stevejobs',
    'database': 'cyberbeef',
    'port': 3306
}

ID_MAQUINA = 1
INTERVALO = 5  # segundos

SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"

LIMITE_ALERTA = {
    "CPU": 80,
    "RAM": 85,
    "DISCO": 80
}

TIPOS_VALIDOS = {"CPU", "RAM", "DISCO", "REDE"}  # Do ENUM do banco


def enviar_slack(mensagem: str):
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": mensagem})
    except Exception as e:
        print(f"Erro ao enviar Slack: {e}")


def conectar():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Erro na conexão com o banco: {e}")
        return None


def registrar_log(id_maquina, tipo, mensagem):
    db = conectar()
    if db is None:
        return

    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO log (id_maquina, tipo, mensagem)
            VALUES (%s, %s, %s)
        """, (id_maquina, tipo, mensagem))
        db.commit()

    except Error as e:
        print(f"Erro ao inserir log: {e}")
    finally:
        cursor.close()
        db.close()

def obter_ou_criar_componente(tipo, unidade, id_maquina):
    tipo = tipo.strip().upper()

    if tipo not in TIPOS_VALIDOS:
        print(f"⚠ ERRO: Tipo de componente inválido enviado: '{tipo}'")
        return None

    db = conectar()
    if db is None:
        return None

    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT idComponente FROM componente
            WHERE tipoComponente = %s AND idMaquina = %s
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
        cursor.close()
        db.close()


def inserir_leitura(id_componente, id_maquina, valor, tipo, unidade):
    db = conectar()
    if db is None:
        return
    try:
        cursor = db.cursor()
        agora = datetime.datetime.now()

        cursor.execute("""
            INSERT INTO leitura (idComponente, idMaquina, dado, dthCaptura)
            VALUES (%s, %s, %s, %s)
        """, (id_componente, id_maquina, valor, agora))
        db.commit()

        print(f"[{agora.strftime('%Y-%m-%d %H:%M:%S')}] {tipo:<7} | {valor:.2f}%")

        registrar_log(
            id_maquina,
            "INFO",
            f"Leitura registrada: {tipo} = {valor:.2f}%"
        )

    except Error as e:
        print(f"Erro ao inserir leitura: {e}")

    finally:
        cursor.close()
        db.close()

def capturar_metricas():
    cpu_percent = psutil.cpu_percent(interval=1)
    ram_percent = psutil.virtual_memory().percent
    disco_percent = psutil.disk_usage('/').percent

    return {
        ("CPU", "%"): cpu_percent,
        ("RAM", "%"): ram_percent,
        ("DISCO", "%"): disco_percent
    }


def verificar_alertas(tipo, valor):
    limite = LIMITE_ALERTA[tipo]
    limite_critico = limite + 10

    if valor >= limite_critico:
        tipo_log = "ERROR"
        mensagem = f":rotating_light: ERRO CRÍTICO — {tipo} atingiu {valor:.2f}% (limite: {limite_critico}%)"
        registrar_log(ID_MAQUINA, tipo_log, mensagem)
        enviar_slack(mensagem)

    elif valor >= limite:
        tipo_log = "WARNING"
        mensagem = f":warning: AVISO — {tipo} está em {valor:.2f}% (limite: {limite}%)"
        registrar_log(ID_MAQUINA, tipo_log, mensagem)
        enviar_slack(mensagem)

def iniciar_monitoramento():
    print("Iniciando monitoramento em tempo real... (Ctrl + C para parar)\n")
    while True:
        metricas = capturar_metricas()

        for (tipo, unidade), valor in metricas.items():
            tipo = tipo.strip().upper()  # 🔥 evita erros de ENUM

            id_comp = obter_ou_criar_componente(tipo, unidade, ID_MAQUINA)

            if id_comp:
                inserir_leitura(id_comp, ID_MAQUINA, valor, tipo, unidade)
                verificar_alertas(tipo, valor)

        time.sleep(INTERVALO)

if __name__ == "__main__":
    iniciar_monitoramento()
