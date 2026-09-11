import os
import re
import time
import requests
from datetime import datetime, timezone
from google import genai
from google.genai import types

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY")
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
APIFOOTBALL_KEY = os.getenv("APIFOOTBALL_KEY")
APIOPENWEATHER_KEY = os.getenv("APIOPENWEATHER_KEY")

# Rotação das 6 chaves do GitHub
GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_1"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
    os.getenv("GEMINI_API_KEY_4"),
    os.getenv("GEMINI_API_KEY_5")
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIGAS = [
    "soccer_epl", "soccer_uefa_champs_league", "soccer_brazil_campeonato",
    "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga",
    "soccer_france_ligue_one", "soccer_efl_champ", "soccer_usa_mls"
]

MAPA_COMPETICOES_FOOTBALL_DATA = {
    "soccer_brazil_campeonato": "BSA", "soccer_spain_la_liga": "PD",
    "soccer_italy_serie_a": "SA", "soccer_epl": "PL",
    "soccer_uefa_champs_league": "CL", "soccer_germany_bundesliga": "BL1",
    "soccer_france_ligue_one": "FL1", "soccer_efl_champ": "ELC"
}

# Mapa das ligas pro ID numérico usado pela API-Football (v3.football.api-sports.io)
# IDs padrão e estáveis da própria documentação da API-Football.
MAPA_LIGAS_API_FOOTBALL = {
    "soccer_epl": 39,
    "soccer_uefa_champs_league": 2,
    "soccer_brazil_campeonato": 71,
    "soccer_spain_la_liga": 140,
    "soccer_italy_serie_a": 135,
    "soccer_germany_bundesliga": 78,
    "soccer_france_ligue_one": 61,
    "soccer_efl_champ": 40,
    "soccer_usa_mls": 253,
}

def temporada_atual():
    # Convenção padrão: temporada europeia começa em julho/agosto.
    # De jan a jun, ainda estamos na temporada que começou no ano anterior.
    hoje = datetime.now(timezone.utc)
    return hoje.year if hoje.month >= 7 else hoje.year - 1

# ==========================================
# 2. FUNÇÕES DE DADOS EXTERNOS (APIs)
# ==========================================
def buscar_tabela_competicao(codigo_competicao):
    if not FOOTBALL_DATA_API_KEY or not codigo_competicao: return {}
    url = f"https://api.football-data.org/v4/competitions/{codigo_competicao}/standings"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        resposta = requests.get(url, headers=headers, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
        tabela = {}
        for grupo in dados.get("standings", []):
            if grupo.get("type") != "TOTAL": continue
            for time_dados in grupo.get("table", []):
                nome = time_dados["team"]["name"]
                forma = time_dados.get("form") or "N/A"
                jogos = time_dados['playedGames']
                media_pro = round(time_dados['goalsFor'] / jogos, 2) if jogos > 0 else 0
                media_contra = round(time_dados['goalsAgainst'] / jogos, 2) if jogos > 0 else 0

                resumo = (
                    f"{time_dados['position']}º lugar | {time_dados['points']}pts "
                    f"({time_dados['won']}V-{time_dados['draw']}E-{time_dados['lost']}D) | "
                    f"Saldo: {time_dados['goalDifference']} | Média Gols Pró: {media_pro} | "
                    f"Média Gols Contra: {media_contra} | Forma Recente: {forma}"
                )
                tabela[nome.lower()] = resumo
        return tabela
    except Exception as e:
        print(f"Aviso: falha ao buscar tabela football-data ({codigo_competicao}): {e}")
        return {}

def encontrar_resumo_time(tabela, nome_time):
    if not tabela: return "Sem dados de tabela"
    nome_time_lower = nome_time.lower()
    for nome_tabela, resumo in tabela.items():
        if nome_time_lower in nome_tabela or nome_tabela in nome_time_lower:
            return resumo
    return "Time não localizado na tabela"

def buscar_fixtures_api_football(id_liga_api_football, data_str):
    """
    Busca, de uma vez, TODOS os jogos de uma liga numa data específica na
    API-Football — inclui árbitro e cidade do estádio de cada jogo.
    1 chamada por liga por dia (cache feito em buscar_jogos_do_dia).
    """
    if not APIFOOTBALL_KEY or not id_liga_api_football:
        return {}

    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": APIFOOTBALL_KEY,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    params = {
        "league": id_liga_api_football,
        "season": temporada_atual(),
        "date": data_str
    }

    try:
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()

        mapa_jogos = {}
        for item in dados.get("response", []):
            time_casa = item["teams"]["home"]["name"]
            time_fora = item["teams"]["away"]["name"]
            arbitro = item["fixture"].get("referee") or "não informado"
            cidade = item["fixture"]["venue"].get("city") or None
            chave = f"{time_casa.lower()}_vs_{time_fora.lower()}"
            mapa_jogos[chave] = {"arbitro": arbitro, "cidade": cidade}
        return mapa_jogos
    except Exception as e:
        print(f"Aviso: falha ao buscar fixtures API-Football (liga {id_liga_api_football}, {data_str}): {e}")
        return {}

def encontrar_extras_jogo(mapa_fixtures, home_team, away_team):
    if not mapa_fixtures:
        return {"arbitro": "não disponível", "cidade": None}
    chave_exata = f"{home_team.lower()}_vs_{away_team.lower()}"
    if chave_exata in mapa_fixtures:
        return mapa_fixtures[chave_exata]
    # fallback: procura por correspondência parcial de nomes (nomes podem divergir entre APIs)
    for chave, valor in mapa_fixtures.items():
        if home_team.lower() in chave and away_team.lower() in chave:
            return valor
    return {"arbitro": "não localizado", "cidade": None}

def buscar_clima(cidade, cache_clima):
    if not APIOPENWEATHER_KEY or not cidade:
        return "Clima: não disponível"
    if cidade in cache_clima:
        return cache_clima[cidade]

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": cidade, "appid": APIOPENWEATHER_KEY, "units": "metric", "lang": "pt_br"}
    try:
        resposta = requests.get(url, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
        temp = dados["main"]["temp"]
        descricao = dados["weather"][0]["description"]
        vento = dados["wind"]["speed"]
        resultado = f"{cidade}: {temp}°C, {descricao}, vento {vento}m/s"
    except Exception as e:
        resultado = f"Clima de {cidade}: não disponível ({e})"

    cache_clima[cidade] = resultado
    return resultado

# ==========================================
# 3. FUNÇÃO: BUSCAR JOGOS E ODDS (Janela de 3 Dias)
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    hoje_utc = datetime.now(timezone.utc).date()
    tabelas_cache = {}
    fixtures_cache = {}  # chave: (id_liga_api_football, data_str)
    clima_cache = {}     # chave: nome da cidade

    for liga in LIGAS:
        codigo_fd = MAPA_COMPETICOES_FOOTBALL_DATA.get(liga)
        if codigo_fd and codigo_fd not in tabelas_cache:
            tabelas_cache[codigo_fd] = buscar_tabela_competicao(codigo_fd)
        tabela_liga = tabelas_cache.get(codigo_fd, {})

        id_liga_af = MAPA_LIGAS_API_FOOTBALL.get(liga)

        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h"}

        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
                diferenca_dias = (data_jogo - hoje_utc).days

                if 0 <= diferenca_dias <= 3:
                    bookmakers = jogo.get('bookmakers', [])
                    if bookmakers:
                        bm = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds = bm['markets'][0]['outcomes']
                        resumo_casa = encontrar_resumo_time(tabela_liga, jogo['home_team'])
                        resumo_fora = encontrar_resumo_time(tabela_liga, jogo['away_team'])

                        data_str = data_jogo.isoformat()
                        chave_cache_fixture = (id_liga_af, data_str)
                        if id_liga_af and chave_cache_fixture not in fixtures_cache:
                            fixtures_cache[chave_cache_fixture] = buscar_fixtures_api_football(id_liga_af, data_str)
                        mapa_fixtures_dia = fixtures_cache.get(chave_cache_fixture, {})

                        extras = encontrar_extras_jogo(mapa_fixtures_dia, jogo['home_team'], jogo['away_team'])
                        info_arbitro = f"Árbitro: {extras['arbitro']}"
                        info_clima = buscar_clima(extras['cidade'], clima_cache) if extras['cidade'] else "Clima: cidade não disponível"

                        info_jogo = (
                            f"LIGA: {liga} | DATA: {data_jogo} | \n"
                            f"CASA: {jogo['home_team']} (Tabela: {resumo_casa}) \n"
                            f"FORA: {jogo['away_team']} (Tabela: {resumo_fora}) \n"
                            f"ODDS: {odds} \n"
                            f"EXTRAS: {info_arbitro} | {info_clima}\n"
                            f"-" * 40
                        )
                        jogos_disponiveis.append(info_jogo)
        except Exception as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    print(f"Total de jogos encontrados: {len(jogos_disponiveis)}")
    return "\n".join(jogos_disponiveis)

# ==========================================
# 4. FUNÇÃO: ANALISAR COM IA (DIRETRIZES COMPLETAS RESTAURADAS)
# ==========================================
def analisar_com_ia_unificada(lista_de_jogos):
    if not lista_de_jogos: return "Nenhum jogo encontrado."

    prompt_master = f"""
    Atue como um Analista Estatístico Sênior e Especialista em Quantitative Sports Trading na Betano, com a postura de um 'Advogado do Diabo' (estritamente cético e rigoroso).

    SUA MISSÃO:
    Analisar os jogos fornecidos abaixo com base nas estatísticas matemáticas reais de tabela, médias de gols e cotações. Monte APENAS UMA aposta múltipla (Bilhete de Valor) com odd combinada em torno de 20.00.

    REGRA DE DATA (OBRIGATÓRIO): A aposta múltipla DEVE conter APENAS jogos que acontecem EXATAMENTE na MESMA DATA. Escolha um dia específico e monte o bilhete inteiro nele.

    DIRETRIZES TÉCNICAS E FILTROS RIGOROSOS (Aplique rigorosamente):
    1. ANÁLISE DE MÉDIAS E DESEMPENHO:
       - Avalie a posição, pontos, saldo e as médias de gols Pró e Contra fornecidas no texto de cada equipe.
       - Defesa Sólida vs Ataque Ineficiente: Identifique confrontos onde o mandante ou visitante possui alta taxa de solidez com base nos gols sofridos.

    2. TRAVA DE ESCANTEIOS E "GAME SCRIPT":
       - Se o favorito tem alta probabilidade estatística de abrir o placar cedo (visto pela tabela e odds baixas), evite recomendar mercados excessivos de cantos a favor dele (o mercado costuma morrer). Evite cantos contra defesas em blocos baixos.

    3. MOTIVAÇÃO E FATORES EXTERNOS (Game State):
       - Analise a necessidade real de pontos de cada time com base na tabela (brigando pelo título, G4, rebaixamento ou meio de tabela sem ambições).
       - Se houver clima adverso informado (chuva forte, vento intenso), considere impacto em jogos de posse/técnica — favorecendo Under Gols ou jogo mais físico.
       - Se o árbitro estiver identificado, use isso como contexto adicional pra mercados de cartões (árbitros mais rigorosos historicamente tendem a linhas mais altas — mas só entre nesse mercado com embasamento real, não suposição).

    4. VALOR REAL E FUGA DE "TRAP ODDS":
       - Odds baixas só são válidas quando refletem um abismo técnico nítido na tabela. Descarte sumariamente odds esmagadas (como 1.05 a 1.25) que não compensam o risco de variância em múltiplas. Odd mínima recomendada por perna: 1.45.

    5. POSTURA ANTI-ALUCINAÇÃO E RIGOR MATEMÁTICO:
       - PROIBIDO INVENTAR DADOS: Trabalhe estritamente com os números (gols, pontos, saldo, forma V/E/D, árbitro, clima) passados na lista abaixo. Se um dado não estiver disponível (ex: "não disponível" ou "não localizado"), NÃO invente um substituto — apenas não use aquele fator específico na justificativa.

    6. VÁLVULA DE ESCAPE (GRADE RUIM):
       - Se a grade do dia for fraca ou os dados não sustentarem com segurança matemática a meta de Odd 20, inclua obrigatoriamente um [⚠️ AVISO DE RISCO DESTACADO] no início da análise, alertando que a múltipla foi forçada pela ausência de opções melhores.

    ======================================================================
    FORMATO DA RESPOSTA FINAL (PARA O TELEGRAM):
    ======================================================================
    Siga estritamente este formato com a tabela e a fundamentação detalhada logo abaixo:

    ### 🎯 BILHETE MÚLTIPLO DE VALOR | DATA: [DD/MM/AAAA]
    [⚠️ AVISO DE RISCO: Insira aqui apenas se a grade estiver fraca, ou omita esta linha se o dia for tecnicamente seguro]
    Odd Combinada Total: [ODD TOTAL] | Gestão de Banca: 0.20u (Stake Padrão)

    | Jogo | Liga | Mercado Escolhido | Odd | Justificativa Enxuta |
    |:---|:---|:---|:---|:---|
    | [Time A vs Time B] | [Liga] | [Mercado] | [Odd] | [Resumo direto] |
    *(Adicione as linhas necessárias até bater a Odd ~20.00)*

    ---
    ### 🔍 FUNDAMENTAÇÃO TÁTICA E MÉDIAS APLICADAS
    (Para cada jogo da tabela acima, apresente a leitura estatística detalhada):

    ⚽ **[Time A] vs [Time B]**
    - **Leitura de Tabela e Médias:** [Cite os pontos, posição, saldo e as médias de gols Pró/Contra exatas extraídas dos dados]
    - **Contexto Extra:** [Cite árbitro e/ou clima se estiverem disponíveis e forem relevantes pra escolha do mercado]
    - **Análise de Risco / Game Script:** [Explique o cenário tático esperado, a necessidade de vitória e o porquê de o mercado escolhido resistir ao rigor analítico]

    ⚽ **[Time C] vs [Time D]**
    - **Leitura de Tabela e Médias:** [Estatísticas...]
    - **Contexto Extra:** [árbitro/clima...]
    - **Análise de Risco / Game Script:** [Racional...]

    JOGOS DISPONÍVEIS E DADOS REAIS (Tabela, Árbitro, Clima):
    {lista_de_jogos}
    """

    ultimo_erro = None
    for i, key in enumerate(GEMINI_KEYS):
        try:
            print(f"Tentando conexão com Gemini na Chave #{i+1}...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            print(f"Sucesso com a Chave #{i+1}.")
            return response.text
        except Exception as e:
            print(f"Erro com a Chave #{i+1}: {e}")
            ultimo_erro = e
            continue

    return f"Erro crítico: Todas as {len(GEMINI_KEYS)} chaves falharam. Último erro: {ultimo_erro}"

# ==========================================
# 5. FUNÇÃO: ENVIAR PARA O TELEGRAM
# ==========================================
def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    mensagem_formatada = mensagem[:4090]
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem_formatada, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload).raise_for_status()
        print("Mensagem enviada com sucesso (Markdown).")
    except requests.exceptions.RequestException:
        payload_sem_formato = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem_formatada}
        try:
            requests.post(url, json=payload_sem_formato).raise_for_status()
            print("Mensagem enviada com sucesso (texto puro).")
        except Exception as e:
            print(f"Erro ao enviar para o Telegram: {e}")

# ==========================================
# 6. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos e processando tabelas...")
    grade = buscar_jogos_do_dia()

    if not grade:
        print("Nenhum jogo encontrado.")
        exit()

    print("Iniciando análise com Gemini...")
    resposta_ia = analisar_com_ia_unificada(grade)

    if "Erro crítico" in resposta_ia:
        enviar_telegram(f"❌ {resposta_ia}")
    else:
        enviar_telegram(resposta_ia.strip())

    print("\nProcesso concluído!")
