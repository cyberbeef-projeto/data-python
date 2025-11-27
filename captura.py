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
    "DISCO": 70
}

TIPOS_VALIDOS = {"CPU", "RAM", "DISCO", "REDE"} 

MAPA_PARAMETROS_FALLBACK = {
    "CPU": 1,
    "RAM": 2,
    "DISCO": 3
}

def enviar_slack(mensagem: str):
    """Envia mensagem para Slack e checa resposta HTTP para debug."""
    try:
        resposta = requests.post(SLACK_WEBHOOK_URL, json={"text": mensagem}, timeout=10)
        # Slack Incoming Webhooks normalmente responde 200 OK
        if resposta.status_code != 200:
            print(f"Slack retornou HTTP {resposta.status_code}: {resposta.text}")
        else:
            print("Mensagem enviada ao Slack.")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar Slack (network/timeout): {e}")
    except Exception as e:
        print(f"Erro inesperado ao enviar Slack: {e}")


def conectar():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        print(f"Erro na conexão com o banco: {e}")
        return None


def registrar_log(id_maquina, tipo_log_db, mensagem):
    """
    Insere na tabela log.
    tipo_log_db deve ser um dos valores permitidos no enum do banco (por ex: 'INFO', 'WARNING', 'ERROR').
    """
    db = conectar()
    if db is None:
        print("Impossível registrar log: sem conexão com DB.")
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
    """
    Tenta obter idParametro a partir da tabela parametro (nivel = tipo e idMaquina = id_maquina).
    Se falhar, retorna valor do MAPA_PARAMETROS_FALLBACK se existir.
    """
    tipo = tipo.strip().upper()
    db = conectar()
    if db is None:
        print("Sem conexão ao DB para obter idParametro -> usando fallback se existir.")
        return MAPA_PARAMETROS_FALLBACK.get(tipo)

    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT idParametro FROM parametro
            WHERE UPPER(nivel) = %s AND idMaquina = %s
            LIMIT 1
        """, (tipo, id_maquina))
        row = cursor.fetchone()
        if row:
            return row[0]
        else:
            # fallback
            return MAPA_PARAMETROS_FALLBACK.get(tipo)
    except Error as e:
        print(f"Erro ao obter idParametro: {e} -> usando fallback se existir.")
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
        print(f"ERRO: Tipo de componente inválido enviado: '{tipo}'")
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
    """
    Insere leitura e retorna idLeitura recém-criado (ou None em caso de erro).
    """
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
    """
    Insere linha na tabela alerta.
    """
    db = conectar()
    if db is None:
        print("Não foi possível registrar alerta: sem conexão DB.")
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
    """
    Retorna tupla (classificacao_texto, nivel_log_db)
    classificacao_texto -> 'Crítico' / 'Anormal' / 'Normal'
    nivel_log_db -> 'ERROR' / 'WARNING' / 'INFO' (valores aceitos pelo enum do log)
    Regras solicitadas:
      - Crítico: > 90%
      - Anormal: 85% <= x <= 90%
      - Normal: < 85%
    """
    if valor > 80:
        return "Crítico", "CRITICO"
    if 85 <= valor <= 90:
        return "Anormal", "ANORMAL"
    return "Normal", "NORMAL"


def verificar_e_tratar_alerta(tipo, valor, id_leitura, id_componente):
    """
    Classifica leitura, registra log (usando enum válido), insere alerta na tabela alerta (se Anormal/Crítico),
    e envia Slack.
    """
    tipo = tipo.strip().upper()

    id_parametro = obter_id_parametro(tipo, ID_MAQUINA)

    classificacao_texto, nivel_log_db = classificar_valor(tipo, valor)

    mensagem_curta = f"{tipo} = {valor:.2f}% -> {classificacao_texto}"

    registrar_log(ID_MAQUINA, nivel_log_db, mensagem_curta)

    if classificacao_texto in ("Anormal", "Crítico"):
        descricao = f"{classificacao_texto} — {tipo} atingiu {valor:.2f}%"
        sucesso_alerta = registrar_alerta(id_leitura, id_componente, ID_MAQUINA, id_parametro, descricao)

        if sucesso_alerta:
            if classificacao_texto == "Crítico":
                enviar_slack(f":rotating_light: CRÍTICO — {descricao}")
            else:
                enviar_slack(f":warning: AVISO — {descricao}")
        else:
            print("Alerta não registrado no BD; Slack não será notificado para evitar mensagens inconsistentes.")
    else:
        pass

def iniciar_monitoramento():
    print("Iniciando monitoramento em tempo real... (Ctrl + C para parar)\n")
    while True:
        metricas = capturar_metricas()

        for (tipo, unidade), valor in metricas.items():
            tipo = tipo.strip().upper()

            id_comp = obter_ou_criar_componente(tipo, unidade, ID_MAQUINA)

            if id_comp:
                id_leitura = inserir_leitura(id_comp, ID_MAQUINA, valor, tipo, unidade)

                if id_leitura:
                    verificar_e_tratar_alerta(tipo, valor, id_leitura, id_comp)

        time.sleep(INTERVALO)

if __name__ == "__main__":
    iniciar_monitoramento()
