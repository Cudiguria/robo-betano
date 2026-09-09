import os
import requests
from datetime import datetime, timezone
from google import genai
from google.genai import types

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# Sistema de Rotação de Múltiplas Chaves do Gemini (Proteção contra Erro 429)
GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY") # Chave principal, deixada por último como backup caso já tenha estourado
]
# Limpa chaves vazias ou nulas da lista
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

# Credenciais do Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Ligas monitoradas
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

            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
                
                # Pega jogos APENAS de hoje e de amanhã (0 a 1 dia de diferença)
                diferenca_dias = (data_jogo - hoje_utc).days
                if 0 <= diferenca_dias <= 1:
                    bookmakers = jogo.get('bookmakers', [])
                    if bookmakers:
                        bm_betano = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds = bm_betano['markets'][0]['outcomes']
                        info_jogo = f"LIGA: {liga} | DATA: {data_jogo} | {jogo['home_team']} vs {jogo['away_team']} | ODDS (Casa: {bm_betano['title']}): {odds}"
                        jogos_disponiveis.append(info_jogo)

        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    print(f"Total de jogos encontrados: {len(jogos_disponiveis)}")
    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR COM O GEMINI + WEB SEARCH + ROTAÇÃO DE CHAVES
# ==========================================
def analisar_com_ia(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo encontrado para hoje ou amanhã nas ligas selecionadas."

    prompt_master = f"""
    Atue como um Analista Estatístico Sênior e Especialista em Quantitative Sports Trading na Betano.
    
    SUA MISSÃO:
    Analisar os jogos disponíveis hoje/amanhã e, em uma ÚNICA resposta, montar TRÊS apostas múltiplas distintas cruzando microfatores táticos via pesquisa web (xG, cartões, desfalques, árbitros). As três múltiplas devem obrigatoriamente ser formadas por jogos da MESMA DATA.

    ESTRUTURA DAS MÚLTIPLAS EXIGIDAS:
    1. 🛡️ MÚLTIPLA CONSERVADORA: Odd total máxima de 10. Foco extremo em segurança, favoritos absolutos ou under gols em jogos travados. Stake sugerida: 0,50u.
    2. 🎯 MÚLTIPLA PREMIUM (PADRÃO): Odd total mínima de 20. Foco em EV+ equilibrado, mercados de cartões, cantos e duplas chances. Stake sugerida: 0,20u.
    3. 🚀 MÚLTIPLA MOONSHOT (OUSADA): Odd total mínima de 100. Foco em variância, empates em clássicos, viradas ou combinação longa de mercados. Stake sugerida: 0,05u.

    DIRETRIZES DE PESQUISA E FILTROS (Aplique a todas as múltiplas):
    1. Desempenho Casa x Fora: Avalie a Força do Calendário e a métrica de "Clean Sheets".
    2. Trava de Escanteios: Se o favorito tem alta probabilidade de abrir o placar cedo, PROÍBA cantos a favor dele (o mercado morre). Evite cantos contra defesas em blocos baixos.
    3. Perfil do Árbitro: Exija histórico do árbitro (acima de 5.5) + descontrole das equipes para linhas de cartões altas.
    4. Fadiga/Game State: Times que viajaram muito ou têm menos de 72h de descanso devem tender a Under Gols.

    ======================================================================
    FORMATO DA RESPOSTA FINAL (PARA O TELEGRAM):
    ======================================================================
    (Formate de forma limpa, usando as divisões abaixo)

    📅 *DATA ESCOLHIDA PARA TODOS OS BILHETES:* [DD/MM/AAAA]

    🛡️ *BILHETE 1: CONSERVADOR (Odd Máx: 10)*
    *Stake:* 0,50u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX
    🔍 *Por quê?* [Justificativa em 1 frase resumida para o bilhete]

    ---
    🎯 *BILHETE 2: PREMIUM (Odd Mín: 20)*
    *Stake:* 0,20u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX
    🔍 *Por quê?* [Justificativa em 1 frase resumida para o bilhete]

    ---
    🚀 *BILHETE 3: MOONSHOT (Odd Mín: 100)*
    *Stake:* 0,05u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    3. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX
    🔍 *Por quê?* [Justificativa em 1 frase resumida para o bilhete]

    JOGOS DISPONÍVEIS:
    {lista_de_jogos}
    """

    for i, key in enumerate(GEMINI_KEYS):
        try:
            print(f"Tentando conexão com o Gemini usando a Chave #{i+1}...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}]
                )
            )
            return response.text
        except Exception as e:
            print(f"Erro com a Chave #{i+1}: {e}")
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print("Limite de cota atingido nesta chave. Tentando a próxima...")
                continue
            else:
                return f"Erro na análise da IA: {e}"

    return "Erro crítico: Todas as chaves da API do Gemini atingiram o limite de cota."

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
        "text": mensagem_formatada,
        "parse_mode": "Markdown"
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

    print("Analisando dados com o Gemini Flash + Web Search e montando as 3 Múltiplas...")
    bilhete_final = analisar_com_ia(grade_hoje)

    print("Enviando bilhete para o Telegram...")
    enviar_telegram(bilhete_final)
    print("Processo concluído com sucesso!")
