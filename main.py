import os
import re
import json
import time
import requests
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, timezone
from google import genai
from google.genai import types

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "").strip()
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
APIFOOTBALL_KEY = os.getenv("APIFOOTBALL_KEY", "").strip()
APIOPENWEATHER_KEY = os.getenv("APIOPENWEATHER_KEY", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

GEMINI_KEYS = [
    os.getenv("GEMINI_API_KEY", "").strip(),
    os.getenv("GEMINI_API_KEY_1", "").strip(),
    os.getenv("GEMINI_API_KEY_2", "").strip(),
    os.getenv("GEMINI_API_KEY_3", "").strip(),
    os.getenv("GEMINI_API_KEY_4", "").strip(),
    os.getenv("GEMINI_API_KEY_5", "").strip()
]
GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

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

MAPA_LIGAS_API_FOOTBALL = {
    "soccer_epl": 39, "soccer_uefa_champs_league": 2, "soccer_brazil_campeonato": 71,
    "soccer_spain_la_liga": 140, "soccer_italy_serie_a": 135, "soccer_germany_bundesliga": 78,
    "soccer_france_ligue_one": 61, "soccer_efl_champ": 40, "soccer_usa_mls": 253,
}

def temporada_atual():
    hoje = datetime.now(timezone.utc)
    return hoje.year if hoje.month >= 7 else hoje.year - 1

# ==========================================
# 2. NORMALIZAÇÃO DE NOMES DE TIMES
# ==========================================
SUFIXOS_SOCIETARIOS = [
    ' fc', ' cf', ' cfb', ' ca', ' cd', ' afc', ' se', ' ac', ' sv',
    ' bvb', ' sc', ' fk', ' as', ' ud', ' rc', ' ec', ' fsv', ' vfb',
    ' tsg', ' ssc', ' us', ' cfc', ' sd'
]

APELIDOS_MANUAIS = {
    "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
    "man utd": "manchester united", "man united": "manchester united",
    "manchester utd": "manchester united", "man city": "manchester city",
    "wolves": "wolverhampton wanderers", "wolverhampton": "wolverhampton wanderers",
    "nottm forest": "nottingham forest", "nott ham forest": "nottingham forest",
    "leicester": "leicester city", "newcastle": "newcastle united",
    "west ham": "west ham united", "brighton": "brighton hove albion",
    "bayern munich": "bayern munchen", "bayern": "bayern munchen",
    "dortmund": "borussia dortmund", "inter": "internazionale",
    "inter milan": "internazionale", "ac milan": "milan",
    "atletico madrid": "atletico de madrid", "atleti": "atletico de madrid",
    "psg": "paris saint germain", "paris sg": "paris saint germain",
    "athletic bilbao": "athletic club", "celta vigo": "rc celta de vigo",
    "rc lens": "racing club de lens",
    "atletico mineiro": "clube atletico mineiro", "atletico mg": "clube atletico mineiro",
    "atletico paranaense": "ca paranaense", "athletico pr": "ca paranaense",
    "bragantinosp": "red bull bragantino", "bragantino": "red bull bragantino",
    "rb bragantino": "red bull bragantino", "vasco": "cr vasco da gama",
    "vasco da gama": "cr vasco da gama"
}

def normalizar_nome(nome):
    if not nome: return ""
    nome = nome.lower().strip()
    nome = ''.join(c for c in unicodedata.normalize('NFD', nome) if unicodedata.category(c) != 'Mn')
    for sufixo in SUFIXOS_SOCIETARIOS:
        if nome.endswith(sufixo):
            nome = nome[:-len(sufixo)]
            break
    nome = re.sub(r'[^\w\s]', '', nome).strip()
    nome = re.sub(r'\s+', ' ', nome)
    return nome

def chave_canonica(nome):
    n = normalizar_nome(nome)
    return APELIDOS_MANUAIS.get(n, n)

def times_equivalentes(nome_a, nome_b, limiar=0.82):
    ca, cb = chave_canonica(nome_a), chave_canonica(nome_b)
    if not ca or not cb: return False
    if ca == cb: return True
    if ca in cb or cb in ca: return True
    return SequenceMatcher(None, ca, cb).ratio() >= limiar

def buscar_em_dicionario(dicionario, nome_time, contexto=""):
    if not dicionario: return None
    chave_busca = chave_canonica(nome_time)
    for chave_dict, valor in dicionario.items():
        if times_equivalentes(chave_busca, chave_dict):
            return valor
    print(f"Aviso [{contexto}]: não achei correspondência pra '{nome_time}' (chave: '{chave_busca}').")
    return None

# ==========================================
# 3. TABELA/FORMA (football-data.org) — ETAPA 1
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
                tabela[chave_canonica(nome)] = resumo
        return tabela
    except Exception as e:
        print(f"Aviso: falha ao buscar tabela football-data ({codigo_competicao}): {e}")
        return {}

# ==========================================
# 4. FIXTURES: ÁRBITRO, CIDADE, IDs DE TIME — ETAPA 1
# ==========================================
def buscar_fixtures_api_football(id_liga_api_football, data_str):
    if not APIFOOTBALL_KEY or not id_liga_api_football: return {}
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    params = {"league": id_liga_api_football, "season": temporada_atual(), "date": data_str}
    try:
        time.sleep(1)
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get("errors"):
            print(f"Aviso API-Football (liga {id_liga_api_football}, {data_str}): {dados['errors']}")
            return {}
        mapa_jogos = {}
        for item in dados.get("response", []):
            time_casa = item["teams"]["home"]["name"]
            time_fora = item["teams"]["away"]["name"]
            arbitro = item["fixture"].get("referee") or "não informado"
            cidade = item["fixture"]["venue"].get("city") or None
            chave = f"{chave_canonica(time_casa)}_vs_{chave_canonica(time_fora)}"
            mapa_jogos[chave] = {
                "arbitro": arbitro, "cidade": cidade,
                "id_casa": item["teams"]["home"]["id"],
                "id_fora": item["teams"]["away"]["id"],
            }
        if not mapa_jogos:
            print(f"Aviso API-Football (liga {id_liga_api_football}, {data_str}): 0 jogos retornados.")
        return mapa_jogos
    except requests.exceptions.HTTPError as e:
        print(f"Erro HTTP na API-Football (fixtures, liga {id_liga_api_football}, {data_str}): {e}")
        return {}
    except Exception as e:
        print(f"Aviso: falha ao buscar fixtures API-Football (liga {id_liga_api_football}, {data_str}): {e}")
        return {}

def encontrar_extras_jogo(mapa_fixtures, home_team, away_team):
    if not mapa_fixtures: return {"arbitro": "não disponível", "cidade": None, "id_casa": None, "id_fora": None}
    home_c, away_c = chave_canonica(home_team), chave_canonica(away_team)
    for chave, valor in mapa_fixtures.items():
        if home_c in chave and away_c in chave:
            return valor
    return {"arbitro": "não localizado", "cidade": None, "id_casa": None, "id_fora": None}

# ==========================================
# 5. CLIMA (OpenWeatherMap) — ETAPA 1
# ==========================================
def buscar_clima(cidade, cache_clima):
    if not APIOPENWEATHER_KEY or not cidade: return "Clima: não disponível"
    if cidade in cache_clima: return cache_clima[cidade]
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
        resultado = f"Clima de {cidade}: não disponível"
    cache_clima[cidade] = resultado
    return resultado

# ==========================================
# 6. CARTÕES E ESCANTEIOS REAIS — SÓ NA ETAPA 2
# ==========================================
def buscar_cartoes_time(id_time, id_liga_api_football, cache_cartoes):
    if not APIFOOTBALL_KEY or not id_time or not id_liga_api_football:
        return "Cartões: não disponível"
    if id_time in cache_cartoes:
        return cache_cartoes[id_time]
    url = "https://v3.football.api-sports.io/teams/statistics"
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    params = {"team": id_time, "league": id_liga_api_football, "season": temporada_atual()}
    try:
        time.sleep(1) # Proteção contra rate limit da API
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json().get("response", {})
        jogos = dados.get("fixtures", {}).get("played", {}).get("total") or 0
        if jogos == 0:
            resultado = "Cartões: sem jogos suficientes na temporada"
        else:
            amarelos = sum((v.get("total") or 0) for v in dados.get("cards", {}).get("yellow", {}).values())
            vermelhos = sum((v.get("total") or 0) for v in dados.get("cards", {}).get("red", {}).values())
            resultado = f"Cartões: média {round(amarelos/jogos,2)} amarelos e {round(vermelhos/jogos,2)} vermelhos/jogo ({jogos} jogos)"
    except Exception as e:
        print(f"Aviso: falha ao buscar cartões do time {id_time}: {e}")
        resultado = "Cartões: não disponível"
    cache_cartoes[id_time] = resultado
    return resultado

def buscar_ultimos_jogos_time(id_time, id_liga_api_football, quantidade=3):
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    params = {"team": id_time, "league": id_liga_api_football, "season": temporada_atual(), "last": quantidade}
    try:
        time.sleep(1)
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        return [item["fixture"]["id"] for item in resposta.json().get("response", [])]
    except Exception as e:
        print(f"Aviso: falha ao buscar últimos jogos do time {id_time}: {e}")
        return []

def buscar_escanteios_fixture(id_fixture, id_time):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    params = {"fixture": id_fixture, "team": id_time}
    try:
        time.sleep(1)
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json().get("response", [])
        if not dados: return None
        for stat in dados[0].get("statistics", []):
            if stat.get("type") == "Corner Kicks":
                valor = stat.get("value")
                return valor if isinstance(valor, (int, float)) else None
        return None
    except Exception as e:
        print(f"Aviso: falha ao buscar escanteios do fixture {id_fixture}: {e}")
        return None

def buscar_media_escanteios_time(id_time, id_liga_api_football, cache_escanteios):
    if not APIFOOTBALL_KEY or not id_time or not id_liga_api_football:
        return "Escanteios: não disponível"
    if id_time in cache_escanteios:
        return cache_escanteios[id_time]
    fixtures_ids = buscar_ultimos_jogos_time(id_time, id_liga_api_football, quantidade=3)
    valores = []
    for fid in fixtures_ids:
        v = buscar_escanteios_fixture(fid, id_time)
        if v is not None:
            valores.append(v)
    if valores:
        resultado = f"Escanteios: média {round(sum(valores)/len(valores), 1)}/jogo (últimos {len(valores)} jogos)"
    else:
        resultado = "Escanteios: não disponível"
    cache_escanteios[id_time] = resultado
    return resultado

def montar_dados_aprofundados(jogos_escolhidos, mapa_ids_jogos):
    cache_cartoes, cache_escanteios = {}, {}
    linhas = []
    for jogo in jogos_escolhidos:
        home = jogo.get("home_team", "")
        away = jogo.get("away_team", "")
        chave = f"{chave_canonica(home)}_vs_{chave_canonica(away)}"
        info = mapa_ids_jogos.get(chave)
        if not info or not info.get("id_casa") or not info.get("id_fora"):
            linhas.append(f"{home} vs {away}: dados aprofundados não disponíveis (time não localizado)")
            continue
        id_liga_af = info["id_liga_af"]
        cart_casa = buscar_cartoes_time(info["id_casa"], id_liga_af, cache_cartoes)
        cart_fora = buscar_cartoes_time(info["id_fora"], id_liga_af, cache_cartoes)
        esc_casa = buscar_media_escanteios_time(info["id_casa"], id_liga_af, cache_escanteios)
        esc_fora = buscar_media_escanteios_time(info["id_fora"], id_liga_af, cache_escanteios)
        linhas.append(
            f"{home} vs {away}:\n"
            f"  {home} — {cart_casa} | {esc_casa}\n"
            f"  {away} — {cart_fora} | {esc_fora}"
        )
    return "\n".join(linhas)

# ==========================================
# 7. ETAPA 1: BUSCAR JOGOS E ODDS 
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    mapa_ids_jogos = {}
    hoje_utc = datetime.now(timezone.utc).date()
    tabelas_cache, fixtures_cache, clima_cache = {}, {}, {}

    for liga in LIGAS:
        codigo_fd = MAPA_COMPETICOES_FOOTBALL_DATA.get(liga)
        if codigo_fd and codigo_fd not in tabelas_cache:
            tabelas_cache[codigo_fd] = buscar_tabela_competicao(codigo_fd)
        tabela_liga = tabelas_cache.get(codigo_fd, {})

        id_liga_af = MAPA_LIGAS_API_FOOTBALL.get(liga)

        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals,spreads"}
        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            dados = resposta.json()

            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
                diferenca_dias = (data_jogo - hoje_utc).days

                if 0 <= diferenca_dias <= 1:
                    bookmakers = jogo.get('bookmakers', [])
                    if bookmakers:
                        bm = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds_str_list = []
                        for market in bm['markets']:
                            m_key = market['key'].upper()
                            outcomes_list = []
                            for o in market['outcomes'][:6]:
                                name = o.get('name', '')
                                point = f" {o.get('point')}" if o.get('point') is not None else ""
                                price = o.get('price', '')
                                outcomes_list.append(f"{name}{point}: {price}")
                            odds_str_list.append(f"[{m_key}] {' / '.join(outcomes_list)}")
                        odds_finais = " | ".join(odds_str_list)

                        resumo_casa = buscar_em_dicionario(tabela_liga, jogo['home_team'], "tabela-casa") or "Sem dados de tabela"
                        resumo_fora = buscar_em_dicionario(tabela_liga, jogo['away_team'], "tabela-fora") or "Sem dados de tabela"

                        data_str = data_jogo.isoformat()
                        chave_cache_fixture = (id_liga_af, data_str)
                        if id_liga_af and chave_cache_fixture not in fixtures_cache:
                            fixtures_cache[chave_cache_fixture] = buscar_fixtures_api_football(id_liga_af, data_str)
                        mapa_fixtures_dia = fixtures_cache.get(chave_cache_fixture, {})

                        extras = encontrar_extras_jogo(mapa_fixtures_dia, jogo['home_team'], jogo['away_team'])
                        info_arbitro = f"Árbitro: {extras['arbitro']}"
                        info_clima = buscar_clima(extras['cidade'], clima_cache) if extras['cidade'] else "Clima: cidade não disponível"

                        # Guarda os IDs pra usar na Etapa 2, SE esse jogo for escolhido
                        chave_id = f"{chave_canonica(jogo['home_team'])}_vs_{chave_canonica(jogo['away_team'])}"
                        mapa_ids_jogos[chave_id] = {
                            "id_casa": extras.get("id_casa"), "id_fora": extras.get("id_fora"),
                            "id_liga_af": id_liga_af
                        }

                        info_jogo = (
                            f"LIGA: {liga} | DATA: {data_jogo} | \n"
                            f"CASA: {jogo['home_team']} (Tabela: {resumo_casa}) \n"
                            f"FORA: {jogo['away_team']} (Tabela: {resumo_fora}) \n"
                            f"ODDS: {odds_finais} \n"
                            f"EXTRAS: {info_arbitro} | {info_clima}\n"
                            f"-" * 40
                        )
                        jogos_disponiveis.append(info_jogo)
        except Exception as e:
            continue

    print(f"Total de jogos encontrados: {len(jogos_disponiveis)}")

    LIMITE_MAXIMO_JOGOS = 30
    if len(jogos_disponiveis) > LIMITE_MAXIMO_JOGOS:
        jogos_disponiveis = jogos_disponiveis[:LIMITE_MAXIMO_JOGOS]

    return "\n".join(jogos_disponiveis), mapa_ids_jogos

# ==========================================
# 8. ETAPA 1: MONTAR MÚLTIPLA CANDIDATA
# ==========================================
def analisar_com_ia_unificada(lista_de_jogos):
    if not lista_de_jogos: return "Nenhum jogo encontrado."

    prompt_master = f"""
    Você é Analista Sênior de Sports Trading na Betano, postura de "Advogado do Diabo" (cético, rigoroso).
    MISSÃO: montar 1 múltipla candidata (odd ~20.00), só com jogos da MESMA DATA.

    REGRAS DE OURO:
    1. Análise de Médias: use posição, pontos, saldo e médias de gols da tabela.
    2. Cartões e Estilo Físico: Como não temos os dados do árbitro, flexibilize a análise de cartões. Baseie-se no estilo tático/físico do confronto (ex: ataque contra defesa baixa, necessidade de vitória, clássicos ou times com histórico agressivo).
    3. EXPLORAÇÃO DE MERCADOS: liberdade para Dupla Chance, DNB, Over/Under Gols, Cartões ou Escanteios. Você PODE incluir mais de uma perna (mercado) para o MESMO jogo se os cenários táticos forem muito fortes (ex: escolher Vencedor e também adicionar uma perna de Escanteios pro mesmo jogo).
    4. Valor: descarte trap odds (≤1.25).
    5. ANTI-ALUCINAÇÃO: como os números reais de cartões/escanteios chegarão na próxima etapa de refinamento, se você escolher esses mercados agora, justifique apenas com o contexto tático e a necessidade do jogo. NUNCA invente números estatísticos.

    FORMATO DE SAÍDA (Telegram):
    ### 🎯 BILHETE MÚLTIPLO DE VALOR | DATA: [DD/MM/AAAA]
    [⚠️ AVISO DE RISCO: só se grade fraca]
    Odd Combinada Total: [XX.XX] | Gestão de Banca: 0.20u

    | Jogo | Liga | Mercado | Odd | Justificativa Enxuta |
    |:---|:---|:---|:---|:---|
    | [Time A vs Time B] | [Liga] | [Mercado] | [Odd] | [resumo] |

    ---
    ### 🔍 FUNDAMENTAÇÃO TÁTICA
    ⚽ **[Time A] vs [Time B]**
    - **Tabela:** [pontos, posição, médias reais]
    - **Contexto Extra:** [dinâmica tática, clima, estilo físico do confronto]
    - **Leitura do Mercado:** [por que este mercado]

    DEPOIS DE TUDO ACIMA, adicione uma última linha exatamente:
    ###JOGOS_ESCOLHIDOS###
    E logo abaixo, APENAS um JSON válido (sem markdown, sem texto extra) listando os jogos escolhidos
    na múltipla, usando os nomes EXATAMENTE como aparecem no texto de jogos abaixo:
    [{{"home_team": "Time A", "away_team": "Time B"}}, ...]

    JOGOS E DADOS REAIS:
    {lista_de_jogos}
    """

    ultimo_erro = None
    for i, key in enumerate(GEMINI_KEYS):
        try:
            print(f"[Etapa 1] Tentando conexão com Gemini na Chave #{i+1}...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            print(f"[Etapa 1] Sucesso com a Chave #{i+1}.")
            return response.text
        except Exception as e:
            print(f"[Etapa 1] Erro com a Chave #{i+1}: {e}")
            ultimo_erro = e
            continue

    return f"Erro crítico: Todas as chaves falharam. Último erro: {ultimo_erro}"

def separar_bilhete_e_jogos_escolhidos(resposta_completa):
    if "###JOGOS_ESCOLHIDOS###" not in resposta_completa:
        print("Aviso: a IA não retornou o bloco de jogos escolhidos — pulando Etapa 2.")
        return resposta_completa.strip(), []
    texto_bilhete, bloco_json = resposta_completa.split("###JOGOS_ESCOLHIDOS###", 1)
    
    bloco_json = bloco_json.replace("```json", "").replace("```", "").strip()
    
    try:
        jogos = json.loads(bloco_json)
    except Exception as e:
        print(f"Aviso: falha ao interpretar JSON de jogos escolhidos: {e}")
        jogos = []
    return texto_bilhete.strip(), jogos

# ==========================================
# 9. ETAPA 3: REFINAR COM DADOS REAIS DE CARTÕES/ESCANTEIOS
# ==========================================
def refinar_com_dados_aprofundados(bilhete_candidato, dados_aprofundados):
    if not dados_aprofundados.strip():
        return bilhete_candidato

    prompt_refinamento = f"""
    Você montou esta múltipla candidata:

    {bilhete_candidato}

    Agora chegaram dados REAIS de cartões e escanteios (médias dos últimos jogos) dos times envolvidos:

    {dados_aprofundados}

    TAREFA: revise a múltipla com esses dados novos e aprimore o bilhete.
    - Análise de Cartões: Cruze as médias reais de cartões fornecidas agora com o estilo de jogo e a agressividade física projetada para o confronto. Se a média sustentar a tese, mantenha e cite os números reais recebidos.
    - Adição de Escanteios: Se a média real de escanteios de um jogo for alta e fizer sentido com o volume ofensivo da partida, você TEM PERMISSÃO para adicionar uma perna extra de escanteios para um jogo que JÁ POSSUI outra seleção na múltipla.
    - Correção de Rota: Se os dados reais contradisserem a sua escolha original (ex: mercado de cartões numa dupla com médias baixas confirmadas), troque esse mercado por outro mais coerente, mantendo a odd total próxima de 20.
    - NUNCA invente escanteios/cartões além dos números fornecidos acima.

    Mantenha EXATAMENTE o mesmo formato de saída (tabela + fundamentação tática) usado na múltipla candidata.
    Responda só com a versão final revisada, pronta pra enviar no Telegram. Não inclua o bloco JSON dessa vez.
    """

    ultimo_erro = None
    for i, key in enumerate(GEMINI_KEYS):
        try:
            print(f"[Etapa 3] Tentando conexão com Gemini na Chave #{i+1}...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_refinamento,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            print(f"[Etapa 3] Sucesso com a Chave #{i+1}.")
            return response.text
        except Exception as e:
            print(f"[Etapa 3] Erro com a Chave #{i+1}: {e}")
            ultimo_erro = e
            continue

    print(f"Aviso: falha ao refinar com dados aprofundados, mantendo bilhete candidato original.")
    return bilhete_candidato

# ==========================================
# 10. ENVIAR PARA O TELEGRAM (ANTI-CORTE)
# ==========================================
def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    pedacos = [mensagem[i:i+4000] for i in range(0, len(mensagem), 4000)]
    for pedaco in pedacos:
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": pedaco, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload).raise_for_status()
            time.sleep(1)
        except requests.exceptions.RequestException:
            payload_sem_formato = {"chat_id": TELEGRAM_CHAT_ID, "text": pedaco}
            try:
                requests.post(url, json=payload_sem_formato).raise_for_status()
                time.sleep(1)
            except Exception as e:
                print(f"Erro ao enviar pedaço para o Telegram: {e}")

# ==========================================
# 11. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Etapa 1: varredura ampla e montagem da múltipla candidata...")
    grade, mapa_ids_jogos = buscar_jogos_do_dia()

    if not grade:
        print("Nenhum jogo encontrado.")
        exit()

    resposta_bruta = analisar_com_ia_unificada(grade)

    if "Erro crítico" in resposta_bruta:
        enviar_telegram(f"❌ {resposta_bruta}")
        exit()

    bilhete_candidato, jogos_escolhidos = separar_bilhete_e_jogos_escolhidos(resposta_bruta)

    if jogos_escolhidos:
        print(f"Etapa 2: buscando cartões/escanteios reais pra {len(jogos_escolhidos)} jogos escolhidos...")
        dados_aprofundados = montar_dados_aprofundados(jogos_escolhidos, mapa_ids_jogos)
        print("Etapa 3: refinando bilhete final com dados reais...")
        bilhete_final = refinar_com_dados_aprofundados(bilhete_candidato, dados_aprofundados)
    else:
        bilhete_final = bilhete_candidato

    enviar_telegram(bilhete_final.strip())
    print("\nProcesso concluído!")
