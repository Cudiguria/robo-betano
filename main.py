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

# ==========================================
# 2. NORMALIZAÇÃO DE NOMES
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
    "atletico mineiro": "atletico mineiro", "clube atletico mineiro": "atletico mineiro", 
    "atletico mg": "atletico mineiro", "atletico paranaense": "ca paranaense", 
    "athletico pr": "ca paranaense", "bragantinosp": "red bull bragantino", 
    "bragantino": "red bull bragantino", "rb bragantino": "red bull bragantino", 
    "vasco": "cr vasco da gama", "vasco da gama": "cr vasco da gama"
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

def buscar_em_dicionario(dicionario, nome_time):
    if not dicionario: return None
    chave_busca = chave_canonica(nome_time)
    for chave_dict, valor in dicionario.items():
        if times_equivalentes(chave_busca, chave_dict):
            return valor
    return None

# ==========================================
# 3. FONTES DE DADOS (Tabela e Clima)
# ==========================================
def buscar_tabela_competicao(codigo_competicao):
    if not FOOTBALL_DATA_API_KEY or not codigo_competicao: return {}
    url = f"https://api.football-data.org/v4/competitions/{codigo_competicao}/standings"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        resposta = requests.get(url, headers=headers, timeout=10)
        resposta.raise_for_status()
        tabela = {}
        for grupo in resposta.json().get("standings", []):
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
                    f"Média Gols Contra: {media_contra} | Forma: {forma}"
                )
                tabela[chave_canonica(nome)] = resumo
        return tabela
    except Exception:
        return {}

def buscar_clima_da_liga(liga):
    mapa_clima = {
        "soccer_epl": "London", "soccer_brazil_campeonato": "São Paulo",
        "soccer_spain_la_liga": "Madrid", "soccer_italy_serie_a": "Rome",
        "soccer_germany_bundesliga": "Berlin", "soccer_france_ligue_one": "Paris"
    }
    cidade = mapa_clima.get(liga)
    if not APIOPENWEATHER_KEY or not cidade: return "Clima não disponível"
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": cidade, "appid": APIOPENWEATHER_KEY, "units": "metric", "lang": "pt_br"}
    try:
        resposta = requests.get(url, params=params, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()
        return f"{cidade}: {dados['main']['temp']}°C, {dados['weather'][0]['description']}"
    except Exception:
        return "Clima não disponível"

# ==========================================
# 4. ETAPA 1: BUSCAR ODDS E MONTAR BASE
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    hoje_utc = datetime.now(timezone.utc).date()
    tabelas_cache = {}

    for liga in LIGAS:
        codigo_fd = MAPA_COMPETICOES_FOOTBALL_DATA.get(liga)
        if codigo_fd and codigo_fd not in tabelas_cache:
            tabelas_cache[codigo_fd] = buscar_tabela_competicao(codigo_fd)
        tabela_liga = tabelas_cache.get(codigo_fd, {})
        clima_liga = buscar_clima_da_liga(liga)

        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h,totals,spreads"}
        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            for jogo in resposta.json():
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).date()
                if 0 <= (data_jogo - hoje_utc).days <= 1:
                    bookmakers = jogo.get('bookmakers', [])
                    if bookmakers:
                        bm = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds_str_list = []
                        for market in bm['markets']:
                            m_key = market['key'].upper()
                            outcomes_list = []
                            for o in market['outcomes'][:6]:
                                point = f" {o.get('point')}" if o.get('point') is not None else ""
                                outcomes_list.append(f"{o.get('name')}{point}: {o.get('price')}")
                            odds_str_list.append(f"[{m_key}] {' / '.join(outcomes_list)}")
                        
                        resumo_casa = buscar_em_dicionario(tabela_liga, jogo['home_team']) or "Sem dados de tabela"
                        resumo_fora = buscar_em_dicionario(tabela_liga, jogo['away_team']) or "Sem dados de tabela"

                        info_jogo = (
                            f"LIGA: {liga} | DATA: {data_jogo} | {clima_liga} \n"
                            f"CASA: {jogo['home_team']} (Tabela: {resumo_casa}) \n"
                            f"FORA: {jogo['away_team']} (Tabela: {resumo_fora}) \n"
                            f"ODDS: {' | '.join(odds_str_list)} \n"
                            f"-" * 40
                        )
                        jogos_disponiveis.append(info_jogo)
        except Exception:
            continue

    LIMITE_MAXIMO_JOGOS = 30
    if len(jogos_disponiveis) > LIMITE_MAXIMO_JOGOS:
        jogos_disponiveis = jogos_disponiveis[:LIMITE_MAXIMO_JOGOS]

    return "\n".join(jogos_disponiveis)

# ==========================================
# 5. ETAPA 1: IA MONTA MÚLTIPLA CANDIDATA
# ==========================================
def analisar_com_ia_candidata(lista_de_jogos):
    prompt_master = f"""
    Você é Analista Sênior de Sports Trading na Betano.
    MISSÃO: montar 1 múltipla candidata (odd ~20.00), com jogos do texto abaixo.

    REGRAS DE OURO:
    1. Baseie-se apenas em posição, saldo, forma recente e odds apresentadas.
    2. Como você ainda não tem os dados de Escanteios e Cartões exatos, se quiser explorar esses mercados agora, faça-o baseado puramente em Inferência Tática.
    3. Você PODE incluir duas seleções para o mesmo jogo (ex: Vencedor + Escanteios).

    FORMATO OBRIGATÓRIO:
    Responda apenas com o texto da múltipla e as justificativas breves. 
    NO FINAL DA MENSAGEM, adicione exatamente a tag ###JOGOS_ESCOLHIDOS### e abaixo dela um JSON com os nomes dos times que você escolheu:
    [{{"home": "Time A", "away": "Time B"}}, ...]

    JOGOS DISPONÍVEIS:
    {lista_de_jogos}
    """
    for key in GEMINI_KEYS:
        try:
            print(f"[Etapa 1] Conectando Gemini (Chave {key[-4:]})...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(temperature=0.2)
            )
            return response.text
        except Exception:
            continue
    return "Erro Crítico: Todas as chaves falharam na Etapa 1."

def extrair_candidata(resposta):
    if "###JOGOS_ESCOLHIDOS###" not in resposta:
        return resposta, []
    texto, json_str = resposta.split("###JOGOS_ESCOLHIDOS###", 1)
    json_str = json_str.replace("```json", "").replace("```", "").strip()
    try:
        jogos = json.loads(json_str)
    except Exception:
        jogos = []
    return texto.strip(), jogos

# ==========================================
# 6. ETAPA 2: IA "GOOGLA" OS JOGOS ESCOLHIDOS (10 ÚLTIMOS JOGOS + CONFRONTOS DIRETOS)
# ==========================================
def refinar_com_google_search(bilhete_candidato, jogos_escolhidos):
    if not jogos_escolhidos:
        return bilhete_candidato

    lista_jogos_str = ", ".join([f"{j.get('home')} vs {j.get('away')}" for j in jogos_escolhidos])

    prompt_refinamento = f"""
    Você montou a seguinte múltipla candidata:
    {bilhete_candidato}

    Você agora DEVE usar a sua ferramenta de Busca do Google (Google Search) para fazer uma PESQUISA PROFUNDA E DETALHADA sobre os seguintes confrontos:
    {lista_jogos_str}

    PESQUISE ESPECIFICAMENTE ESTES PONTOS PARA CADA JOGO:
    1. Desempenho e médias detalhadas nos ÚLTIMOS 10 JOGOS de cada equipe (gols marcados/sofridos, consistência).
    2. Média de escanteios (cantos) com base nos jogos recentes da temporada.
    3. Média de cartões (disciplina, amarelos e vermelhos) nos últimos confrontos e na temporada.
    4. Histórico recente de CONFRONTOS DIRETOS entre as duas equipes (resultados dos últimos duelos diretos entre eles, sem focar em H2H abstrato, apenas o placar e dinâmica dos encontros passados).

    🚨 REGRA ANTI-ALUCINAÇÃO:
    Trabalhe APENAS com os dados reais retornados pela busca. Se faltar algum dado exato, escreva "Dado não localizado na busca". NUNCA invente estatísticas.

    TAREFA DE REFINAMENTO:
    - Cruze o resultado da sua pesquisa profunda com o bilhete que você montou.
    - Se os dados dos últimos 10 jogos e dos confrontos diretos confirmarem a tese, mantenha e enriqueça a justificativa técnica.
    - Se os dados mostrarem riscos ocultos, TROQUE o mercado escolhido para algo mais seguro.

    FORMATO DE SAÍDA EXIGIDO:
    Crie o bilhete final no padrão profissional do Telegram.
    Na seção de 🔍 FUNDAMENTAÇÃO TÁTICA, ao final da explicação de CADA JOGO, adicione OBRIGATORIAMENTE esta linha exata preenchida com os dados da sua pesquisa:

    **📊 Resumo Estatístico:** Média de escanteios: [X] | Média de Cartões: [X] | Histórico de confrontos diretos recentes: [Breve resumo dos últimos duelos] | Postura de jogo esperada: [Ex: Ataque contra Defesa]

    Responda diretamente com o bilhete formatado.
    """

    for key in GEMINI_KEYS:
        try:
            print(f"[Etapa 2] Ativando Agente com Google Search para pesquisa profunda (10 jogos + diretos) (Chave {key[-4:]})...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_refinamento,
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    tools=[{"google_search": {}}]
                )
            )
            return response.text
        except Exception as e:
            print(f"Erro na Busca: {e}")
            continue

    return bilhete_candidato

# ==========================================
# 7. TELEGRAM E EXECUÇÃO
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
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": pedaco})

if __name__ == "__main__":
    print("Iniciando Robô Trader (Versão Definitiva - Agente Web Profundo)...")
    grade = buscar_jogos_do_dia()
    if not grade:
        print("Sem jogos.")
        exit()

    print("Etapa 1: Analisando e gerando candidata...")
    resposta_bruta = analisar_com_ia_candidata(grade)
    
    if "Erro Crítico" in resposta_bruta:
        enviar_telegram(f"❌ {resposta_bruta}")
        exit()

    candidata, escolhidos = extrair_candidata(resposta_bruta)

    if escolhidos:
        print(f"Etapa 2: IA pesquisando {len(escolhidos)} jogos no Google (10 últimos jogos + confrontos diretos)...")
        bilhete_final = refinar_com_google_search(candidata, escolhidos)
    else:
        bilhete_final = candidata

    enviar_telegram(bilhete_final.strip())
    print("\nConcluído!")
