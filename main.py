import os
import requests
from datetime import datetime, timezone

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Credenciais do Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Ligas de Elite + Ligas de Valor (Nomes Oficiais The Odds API)
LIGAS = [
    "soccer_epl",                # Premier League
    "soccer_uefa_champs_league", # Champions League
    "soccer_brazil_campeonato",  # Brasileirão Série A
    "soccer_spain_la_liga",      # La Liga
    "soccer_efl_champ",          # Inglaterra Championship
    "soccer_japan_j_league",     # Japão J-League
    "soccer_usa_mls"             # EUA MLS
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
# 4. FUNÇÃO: ENVIAR PARA O TELEGRAM
# ==========================================
def enviar_telegram(mensagem):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados nos secrets.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    mensagem_formatada = mensagem[:4090] if len(mensagem) > 4096 else mensagem

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem_formatada
    }

    try:
        resposta = requests.post(url, json=payload)
        resposta.raise_for_status()
        print("Mensagem enviada com sucesso para o Telegram.")
    except Exception as e:
        print(f"Erro ao enviar para o Telegram: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Detalhe do erro: {e.response.text}")

# ==========================================
# 5. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos da Betano...")
    grade_hoje = buscar_jogos_do_dia()

    print("Analisando dados com a IA e montando múltipla odd 20+...")
    bilhete_final = analisar_com_ia(grade_hoje)

    print("Enviando bilhete para o Telegram...")
    enviar_telegram(bilhete_final)
    print("Processo concluído com sucesso!")
