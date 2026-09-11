import os
import re
import time
import requests
import pandas as pd
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

# Novos Links do FBref para Scraping de Dados Avançados
MAPA_LIGAS_FBREF = {
    "soccer_epl": "https://fbref.com/en/comps/9/Premier-League-Stats",
    "soccer_brazil_campeonato": "https://fbref.com/en/comps/24/Serie-A-Stats",
    "soccer_spain_la_liga": "https://fbref.com/en/comps/12/La-Liga-Stats",
    "soccer_italy_serie_a": "https://fbref.com/en/comps/11/Serie-A-Stats",
    "soccer_germany_bundesliga": "https://fbref.com/en/comps/20/Bundesliga-Stats"
}

def temporada_atual():
    hoje = datetime.now(timezone.utc)
    return hoje.year if hoje.month >= 7 else hoje.year - 1

def limpar_nome_time(nome):
    if not nome: return ""
    nome = nome.lower()
    sufixos = [" fc", " cfb", " cf", " ca", " cd", " afc", " 04", " sv", " bvb", " sc"]
    for sufixo in sufixos:
        nome = nome.replace(sufixo, "")
    nome = re.sub(r'[^\w\s]', '', nome).strip()
    return nome

# ==========================================
# 2. FBREF WEB SCRAPING (O MOTOR NOVO)
# ==========================================
def raspar_dados_fbref(liga):
    link = MAPA_LIGAS_FBREF.get(liga)
    if not link: return {}
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        time.sleep(3) # Pausa obrigatória para o FBref não bloquear
        resposta = requests.get(link, headers=headers, timeout=15)
        # O pandas varre o HTML e acha todas as tabelas
        tabelas = pd.read_html(resposta.text)
        
        # A tabela 0 do FBref costuma ser a Standard Stats (xG, Cartões, etc)
        df = tabelas[0]
        # Limpando o cabeçalho duplo que o FBref usa
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(0)
            
        dados_avancados = {}
        for _, linha in df.iterrows():
            if 'Squad' not in linha: continue
            nome_time = limpar_nome_time(str(linha['Squad']))
            xg = linha.get('xG', 'N/A')
            xg_contra = linha.get('xGA', 'N/A')
            amarelos = linha.get('CrdY', 'N/A')
            vermelhos = linha.get('CrdR', 'N/A')
            
            dados_avancados[nome_time] = f"xG Pró: {xg} | xG Contra: {xg_contra} | Cartões(Amarelos/Vermelhos): {amarelos}/{vermelhos}"
            
        return dados_avancados
    except Exception as e:
        print(f"Erro ao raspar FBref para {liga}: {e}")
        return {}

def encontrar_fbref_time(dados_fbref, nome_time):
    if not dados_fbref: return "Sem dados táticos avançados"
    nome_limpo = limpar_nome_time(nome_time)
    for nome_tabela, resumo in dados_fbref.items():
        if nome_limpo in nome_tabela or nome_tabela in nome_limpo:
            return resumo
    return "Dados avançados não localizados"

# ==========================================
# 3. FUNÇÕES DE DADOS EXTERNOS (APIs CLÁSSICAS)
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
                tabela[limpar_nome_time(nome)] = resumo
        return tabela
    except Exception as e:
        return {}

def encontrar_resumo_time(tabela, nome_time):
    if not tabela: return "Sem dados de tabela"
    nome_limpo = limpar_nome_time(nome_time)
    for nome_tabela, resumo in tabela.items():
        if nome_limpo in nome_tabela or nome_tabela in nome_limpo: return resumo
    return "Time não localizado na tabela"

def buscar_fixtures_api_football(id_liga_api_football, data_str):
    if not APIFOOTBALL_KEY or not id_liga_api_football: return {}
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": APIFOOTBALL_KEY}
    params = {"league": id_liga_api_football, "season": temporada_atual(), "date": data_str}

    try:
        time.sleep(2) 
        resposta = requests.get(url, headers=headers, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
        mapa_jogos = {}
        for item in dados.get("response", []):
            time_casa = limpar_nome_time(item["teams"]["home"]["name"])
            time_fora = limpar_nome_time(item["teams"]["away"]["name"])
            arbitro = item["fixture"].get("referee") or "não informado"
            cidade = item["fixture"]["venue"].get("city") or None
            chave = f"{time_casa}_vs_{time_fora}"
            mapa_jogos[chave] = {"arbitro": arbitro, "cidade": cidade}
        return mapa_jogos
    except Exception as e:
        return {}

def encontrar_extras_jogo(mapa_fixtures, home_team, away_team):
    if not mapa_fixtures: return {"arbitro": "não disponível", "cidade": None}
    home_clean = limpar_nome_time(home_team)
    away_clean = limpar_nome_time(away_team)
    
    chave_limpa = f"{home_clean}_vs_{away_clean}"
    if chave_limpa in mapa_fixtures: return mapa_fixtures[chave_limpa]
        
    for chave, valor in mapa_fixtures.items():
        if home_clean in chave and away_clean in chave: return valor
    return {"arbitro": "não localizado", "cidade": None}

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
# 4. FUNÇÃO: BUSCAR JOGOS E ODDS
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    hoje_utc = datetime.now(timezone.utc).date()
    tabelas_cache, fixtures_cache, clima_cache, fbref_cache = {}, {}, {}, {}

    for liga in LIGAS:
        # Cache Football Data
        codigo_fd = MAPA_COMPETICOES_FOOTBALL_DATA.get(liga)
        if codigo_fd and codigo_fd not in tabelas_cache:
            tabelas_cache[codigo_fd] = buscar_tabela_competicao(codigo_fd)
        tabela_liga = tabelas_cache.get(codigo_fd, {})
        
        # Cache FBref
        if liga not in fbref_cache:
            fbref_cache[liga] = raspar_dados_fbref(liga)
        fbref_liga = fbref_cache.get(liga, {})

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
                            for o in market['outcomes']:
                                name = o.get('name', '')
                                point = f" {o.get('point')}" if o.get('point') is not None else ""
                                price = o.get('price', '')
                                outcomes_list.append(f"{name}{point}: {price}")
                            odds_str_list.append(f"[{m_key}] {' / '.join(outcomes_list)}")
                        odds_finais = " | ".join(odds_str_list)
                        
                        resumo_casa = encontrar_resumo_time(tabela_liga, jogo['home_team'])
                        resumo_fora = encontrar_resumo_time(tabela_liga, jogo['away_team'])
                        
                        fbref_casa = encontrar_fbref_time(fbref_liga, jogo['home_team'])
                        fbref_fora = encontrar_fbref_time(fbref_liga, jogo['away_team'])

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
                            f"CASA: {jogo['home_team']} (Tabela: {resumo_casa} | Tático: {fbref_casa}) \n"
                            f"FORA: {jogo['away_team']} (Tabela: {resumo_fora} | Tático: {fbref_fora}) \n"
                            f"ODDS: {odds_finais} \n"
                            f"EXTRAS: {info_arbitro} | {info_clima}\n"
                            f"-" * 40
                        )
                        jogos_disponiveis.append(info_jogo)
        except Exception as e:
            continue

    LIMITE_MAXIMO_JOGOS = 60
    if len(jogos_disponiveis) > LIMITE_MAXIMO_JOGOS:
        jogos_disponiveis = jogos_disponiveis[:LIMITE_MAXIMO_JOGOS]

    return "\n".join(jogos_disponiveis)

# ==========================================
# 5. FUNÇÃO: ANALISAR COM IA 
# ==========================================
def analisar_com_ia_unificada(lista_de_jogos):
    if not lista_de_jogos: return "Nenhum jogo encontrado."

    prompt_master = f"""
    Você é Analista Sênior de Sports Trading na Betano, postura de "Advogado do Diabo" (cético, rigoroso).
    MISSÃO: montar 1 múltipla (odd ~20.00), só com jogos da MESMA DATA (escolha 1 dia e monte tudo nele).

    REGRAS DE OURO:
    1. Análise de Médias: use posição, pontos, e as novas métricas táticas de xG (Gols Esperados) e Cartões fornecidos no texto.
    2. Condições de Clima e Árbitro: Clima adverso favorece Under Gols; Árbitros rigorosos somados a times com alta contagem de cartões justificam apostas disciplinares.
    3. EXPLORAÇÃO DE MERCADOS: Você tem TOTAL LIBERDADE para adotar mercados alternativos como Dupla Chance (1X/X2), Empate Anula Aposta (DNB), Over/Under Gols, Cartões ou Handicaps. Use-os como "blindagem" se o Vencedor 1X2 for arriscado. O xG aponta a força real do ataque para inferir escanteios ou gols.
    4. Valor: Descarte trap odds (≤1.25) que não compensam o risco de variância na múltipla.
    5. ANTI-ALUCINAÇÃO E LIMPEZA: Só cite dados que existam. SE a informação do árbitro, clima ou xG constar como "não disponível/não informado", NÃO MENCIONE ISSO NA RESPOSTA. Simplesmente omita.

    FORMATO DE SAÍDA EXIGIDO (Telegram):
    ### 🎯 BILHETE MÚLTIPLO DE VALOR | DATA: [DD/MM/AAAA]
    [⚠️ AVISO DE RISCO: só se grade fraca]
    Odd Combinada Total: [XX.XX] | Gestão de Banca: 0.20u

    | Jogo | Liga | Mercado | Odd | Justificativa Enxuta |
    |:---|:---|:---|:---|:---|
    | [Time A vs Time B] | [Liga] | [Mercado Escolhido] | [Odd] | [resumo] |
    (linhas suficientes até ~odd 20)

    ---
    ### 🔍 FUNDAMENTAÇÃO TÁTICA E PROTEÇÃO DE MERCADO
    ⚽ **[Time A] vs [Time B]**
    - **Tabela e xG:** [pontos, saldo e leitura dos gols esperados e cartões]
    - **Contexto Extra:** [Impacto do clima/árbitro, apenas se relevantes]
    - **Leitura do Mercado:** [Justifique a escolha técnica da proteção escolhida]

    JOGOS E DADOS REAIS:
    {lista_de_jogos}
    """

    ultimo_erro = None
    for i, key in enumerate(GEMINI_KEYS):
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            return response.text
        except Exception as e:
            ultimo_erro = e
            continue

    return f"Erro crítico: Todas as chaves falharam. Último erro: {ultimo_erro}"

# ==========================================
# 6. FUNÇÃO: ENVIAR PARA O TELEGRAM (ANTI-CORTE)
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
# 7. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Iniciando varredura tática...")
    grade = buscar_jogos_do_dia()

    if not grade:
        print("Nenhum jogo encontrado.")
        exit()

    print("Enviando matriz para a IA...")
    resposta_ia = analisar_com_ia_unificada(grade)

    if "Erro crítico" in resposta_ia:
        enviar_telegram(f"❌ {resposta_ia}")
    else:
        enviar_telegram(resposta_ia.strip())

    print("\nProcesso concluído!")
