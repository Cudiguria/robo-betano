import os
import requests
from datetime import datetime, timezone
from twilio.rest import Client

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
# Contas necessárias: the-odds-api.com, aistudio.google.com e twilio.com
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Credenciais da Twilio para o WhatsApp
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_REMETENTE = os.getenv("TWILIO_WHATSAPP_REMETENTE", "whatsapp:+17372508034")  # Número do Sandbox

# Destinatários (todos vêm dos secrets do GitHub — nenhum número fica exposto no código)
MEU_WHATSAPP = os.getenv("MEU_WHATSAPP")
# RAYAN_WHATSAPP DESATIVADO TEMPORARIAMENTE PARA TESTE ISOLADO
# RAYAN_WHATSAPP = os.getenv("RAYAN_WHATSAPP")
RAYAN_WHATSAPP = None

# Ligas de Elite + Ligas de Valor (Nomes Oficiais The Odds API)
LIGAS = [
    "soccer_epl",                        # Premier League
    "soccer_uefa_champs_league",         # Champions League
    "soccer_brazil_campeonato",          # Brasileirão Série A
    "soccer_spain_la_liga",              # La Liga
    "soccer_netherlands_eerste_divisie", # Holanda 2ª Divisão
    "soccer_efl_champ",                  # Inglaterra Championship
    "soccer_japan_j_league",             # Japão J-League
    "soccer_usa_mls"                     # EUA MLS
]

# ==========================================
# 2. FUNÇÃO: BUSCAR JOGOS E ODDS DA BETANO
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []

    for liga in LIGAS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "bookmakers": "betano"
        }

        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if data_jogo.date() == datetime.now(timezone.utc).date():
                    if jogo.get('bookmakers'):
                        odds = jogo['bookmakers'][0]['markets'][0]['outcomes']
                        info_jogo = f"LIGA: {liga} | {jogo['home_team']} vs {jogo['away_team']} | ODDS 1X2: {odds}"
                        jogos_disponiveis.append(info_jogo)

        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR COM O GEMINI
# ==========================================
def analisar_com_ia(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo com odds da Betano encontrado para hoje nas ligas selecionadas."

    url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt_master = f"""
    Atue como meu especialista e analista estatístico de apostas esportivas na Betano.

    INSTRUÇÃO DE EXECUÇÃO:
    Abaixo está a lista real de jogos de hoje com cotações (odds) da Betano. Selecione os melhores confrontos e monte uma aposta múltipla com odd mínima de 20.

    DIRETRIZES TÉCNICAS:
    1. Amostragem Recente (Últimos 10 Jogos): Fundamente nas médias e frequências.
    2. Retrospecto e Game State: Avalie necessidade de vitória.
    3. Filtro de Desfalques e Elenco: Evite times com rotação massiva.
    4. Exploração Ampla de Mercados: Busque a menor variância (Gols, Ambas Marcam, Escanteios, Cartões, Faltas).
    5. Micro-mercados e Coerência: Lógica combinada no mesmo jogo deve fazer sentido tático.
    6. Trava de Valor: Odd mínima de 1,45 por perna.
    7. Gestão: Stake padrão de 0,20u.

    Entregue APENAS a tabela final com os jogos, mercados, odds combinadas e justificativa enxuta.

    JOGOS DISPONÍVEIS HOJE:
    {lista_de_jogos}
    """

    headers = {"Content-Type": "application/json"}
    payload = {"contents": [{"parts": [{"text": prompt_master}]}]}

    try:
        resposta = requests.post(url_gemini, headers=headers, json=payload)
        resposta.raise_for_status()
        return resposta.json()['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        return f"Erro na análise da IA: {e}"

# ==========================================
# 4. FUNÇÃO: ENVIAR PARA O WHATSAPP (TWILIO)
# ==========================================
def enviar_whatsapp(mensagem):
    # Monta a lista de destinatários a partir dos secrets configurados,
    # ignorando qualquer um que não tenha sido definido
    destinatarios = [numero for numero in [MEU_WHATSAPP, RAYAN_WHATSAPP] if numero]

    if not destinatarios:
        print("Nenhum número de destino configurado (defina MEU_WHATSAPP e/ou RAYAN_WHATSAPP nos secrets).")
        return

    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        print("TWILIO_ACCOUNT_SID ou TWILIO_AUTH_TOKEN não configurados nos secrets.")
        return

    cliente = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    # A API da Twilio tem um limite de 1600 caracteres por mensagem.
    mensagem_formatada = mensagem[:1590] if len(mensagem) > 1600 else mensagem

    for numero in destinatarios:
        try:
            message = cliente.messages.create(
                from_=TWILIO_WHATSAPP_REMETENTE,
                body=mensagem_formatada,
                to=numero
            )
            print(f"Mensagem enviada com sucesso para {numero}. SID: {message.sid}")
        except Exception as e:
            print(f"Erro ao enviar para {numero}: {e}")

# ==========================================
# 5. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos da Betano...")
    grade_hoje = buscar_jogos_do_dia()

    print("Analisando dados com a IA e montando múltipla odd 20+...")
    bilhete_final = analisar_com_ia(grade_hoje)

    print("Enviando bilhete para o WhatsApp...")
    enviar_whatsapp(bilhete_final)
    print("Processo concluído com sucesso!")


