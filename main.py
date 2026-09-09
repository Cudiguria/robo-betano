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

# Ampliando ligas para garantir que encontre jogos disponíveis
LIGAS = [
    "soccer_epl",                # Premier League
    "soccer_uefa_champs_league", # Champions League
    "soccer_brazil_campeonato",  # Brasileirão Série A
    "soccer_spain_la_liga",      # La Liga
    "soccer_italy_serie_a",      # Itália Serie A
    "soccer_germany_bundesliga", # Alemanha Bundesliga
    "soccer_france_ligue_one",   # França Ligue 1
    "soccer_efl_champ",          # Inglaterra Championship
    "soccer_usa_mls"             # EUA MLS
]

# ==========================================
# 2. FUNÇÃO: BUSCAR JOGOS E ODDS
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    hoje_utc = datetime.now(timezone.utc).date()

    for liga in LIGAS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h"
        }

        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

            print(f"Liga {liga}: {len(dados)} jogos retornados pela API.")

            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
                
                # Pega jogos de hoje e dos próximos 3 dias
                diferenca_dias = (data_jogo - hoje_utc).days
                if 0 <= diferenca_dias <= 3:
                    bookmakers = jogo.get('bookmakers', [])
                    if bookmakers:
                        # Tenta pegar a Betano, se não achar, pega a primeira disponível
                        bm_betano = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds = bm_betano['markets'][0]['outcomes']
                        info_jogo = f"LIGA: {liga} | DATA: {data_jogo} | {jogo['home_team']} vs {jogo['away_team']} | ODDS (Casa: {bm_betano['title']}): {odds}"
                        jogos_disponiveis.append(info_jogo)

        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    print(f"Total de jogos válidos encontrados no filtro: {len(jogos_disponiveis)}")
    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR COM O GEMINI
# ==========================================
def analisar_com_ia(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo encontrado para os próximos dias nas ligas selecionadas."

    url_gemini = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    prompt_master = f"""
    Atue como meu especialista e analista estatístico de apostas esportivas.

    INSTRUÇÃO DE EXECUÇÃO:
    Abaixo está a lista real de jogos de hoje/próximos dias com cotações (odds). Selecione os melhores confrontos e monte uma aposta múltipla com odd mínima de 20.

    DIRETRIZES TÉCNICAS:
    1. Amostragem Recente: Fundamente nas médias e frequências dos últimos jogos.
    2. Retrospecto e Game State: Avalie a necessidade de vitória.
    3. Filtro de Desfalques e Elenco: Evite times com rotação massiva.
    4. Exploração Ampla de Mercados: Busque a menor variância.
    5. Trava de Valor: Odd mínima de 1,45 por perna.
    6. Gestão: Stake padrão de 0,20u.

    Entregue APENAS a tabela final com os jogos, mercados, odds combinadas e justificativa enxuta.

    JOGOS DISPONÍVEIS:
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

# ==========================================
# 5. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos...")
    grade_hoje = buscar_jogos_do_dia()

    print("Analisando dados com a IA e montando múltipla odd 20+...")
    bilhete_final = analisar_com_ia(grade_hoje)

    print("Enviando bilhete para o Telegram...")
    enviar_telegram(bilhete_final)
    print("Processo concluído com sucesso!")
    enviar_telegram(bilhete_final)
    print("Processo concluído com sucesso!")
