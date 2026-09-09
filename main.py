import os
import requests
from datetime import datetime, timezone
from google import genai
from google.genai import types

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Credenciais do Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Ampliando ligas para garantir jogos disponíveis em qualquer dia
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
                
                # Pega jogos APENAS de hoje e de amanhã
                diferenca_dias = (data_jogo - hoje_utc).days
                if 0 <= diferenca_dias <= 1:
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

    print(f"Total de jogos encontrados: {len(jogos_disponiveis)}")
    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR COM O GEMINI + WEB SEARCH
# ==========================================
def analisar_com_ia(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo encontrado para hoje ou amanhã nas ligas selecionadas."

    prompt_master = f"""
    Atue como um Analista Estatístico Sênior e Especialista em Quantitative Sports Trading na Betano.
    
    SUA MISSÃO:
    Analisar os jogos disponíveis hoje, realizar uma avaliação de probabilidade extremamente aprofundada (cruzando microfatores táticos e estatísticos) e montar uma aposta múltipla de alto valor esperado (EV+) com Odd Total de no mínimo 20, utilizando gestão de 0,20u.

    ======================================================================
    PROTOCOLO DE PESQUISA PROFUNDA E FILTROS DE ALTA PRECISÃO
    ======================================================================
    Antes de selecionar qualquer mercado, submeta cada jogo aos seguintes crivos de pesquisa:

    1. ANÁLISE DE EXPECTATIVA DE GOLS (xG) E DESEMPENHO CASA x FORA (Splits)
       - Não olhe apenas a forma geral. Isole o desempenho do Mandante jogando EM CASA e do Visitante jogando FORA.
       - Avalie o "Strength of Schedule" (Força do Calendário): as vitórias recentes foram contra times do topo ou da base da tabela?
       - Defesa Sólida vs Ataque Ineficiente: Avalie a métrica de "Clean Sheets" (jogos sem sofrer gol) do mandante contra a taxa de conversão do visitante.

    2. TRAVA DE ESCANTEIOS E "GAME SCRIPT" (Armadilha de Favoritos)
       - O volume de escanteios despenca assim que um time faz gol. Se o favorito é amplamente superior e tem alta probabilidade de abrir o placar no 1º tempo, PROÍBA apostas em "Mais de X Escanteios" a favor dele. Ele vai administrar a posse e o mercado vai morrer.
       - Proibição contra Blocos Baixos: Contra retrancas puras, zere a exposição em cantos. Defesas fechadas cedem tiro de meta e lateral, não escanteio. Só valide cantos em jogos de transição rápida e espaço aberto.

    3. PERFIL DO ÁRBITRO E TRAVA DE CLÁSSICOS TENSOS (Mercado de Cartões)
       - O juiz é o fator número 1. Não assuma que clássicos pesados garantem "Mais de 4.5 Cartões" apenas pelo peso da camisa. Jogos truncados muitas vezes geram apenas faltas táticas no meio-campo.
       - Para validar uma linha alta de cartões, exija cruzamento duplo obrigatório: Árbitro com média historicamente rígida (acima de 5.5) E histórico recente de descontrole disciplinar de ambas as equipes. Se a partida tender a ser de estudo e cautela, fuja dos cartões.

    4. MOTIVAÇÃO, FADIGA E FATORES EXTERNOS (Game State)
       - Avalie o desgaste: O time viajou muito? Teve menos de 72 horas de descanso por causa de copas? Se sim, a probabilidade de um jogo de baixa intensidade (Under Gols) aumenta.
       - Descarte times favoritos que já cumpriram seu objetivo na temporada e entrarão com rotação de elenco.

    5. VALOR REAL EM ODDS BAIXAS E FUGA DE "TRAP ODDS"
       - Nem toda odd baixa é armadilha. Avalie se cotações "esmagadas" refletem um abismo técnico inegável (ex: elite titular em casa x time de segunda divisão). 
       - Se a probabilidade real beirar a certeza tática e física, odds mais baixas (abaixo de 1.45) PODEM e DEVEM ser incluídas como pilares de segurança do bilhete. Só evite odds baixas sustentadas apenas pelo nome do time (Trap Odds).

    6. MONTAGEM DA MÚLTIPLA E FLEXIBILIDADE DE PERNAS
       - Odd total mínima: 20.00.
       - Não há um limite engessado de pernas. Evite bilhetes excessivamente longos apenas para não acumular variância gratuita, mas tenha total liberdade para estender o número de seleções caso encontre várias oportunidades altamente pertinentes e de forte convicção.

    ======================================================================
    FORMATO DA RESPOSTA (RELATÓRIO FINAL PARA WHATSAPP)
    ======================================================================
    
    🎯 *MÚLTIPLA PREMIUM ODD 20+ | DADOS AVANÇADOS*
    📊 *Stake:* 0,20u

    📋 *SELEÇÕES DO BILHETE:*
    1. [Liga] Nome do Jogo | Mercado Escolhido | Odd: X.XX
    2. [Liga] Nome do Jogo | Mercado Escolhido | Odd: X.XX
    3. [Liga] Nome do Jogo | Mercado Escolhido | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX

    🔍 *RELATÓRIO TÉCNICO (O "PORQUÊ" DE CADA ESCOLHA):*
    • *Jogo 1:* [Justifique com dados de Casa/Fora, Fadiga, ou Tática]
    • *Jogo 2:* [Justifique com base no Game Script esperado]
    • *Jogo 3:* [Justifique pelo encaixe, Árbitro ou Desnível Técnico irrecusável]
    ...

    JOGOS DISPONÍVEIS HOJE:
    {lista_de_jogos}
    """

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # O modelo retorna ao Flash, mas mantém a ferramenta de busca ativada
        response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt_master,
            config=types.GenerateContentConfig(
                tools=[{"google_search": {}}]
            )
        )
        return response.text
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

    print("Analisando dados com o Gemini Flash + Search e montando múltipla odd 20+...")
    bilhete_final = analisar_com_ia(grade_hoje)

    print("Enviando bilhete para o Telegram...")
    enviar_telegram(bilhete_final)
    print("Processo concluído com sucesso!")
