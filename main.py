import os
import re
import json
import math
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

# Arquivo de histórico de bilhetes enviados (usado pra graduar green/red depois).
# IMPORTANTE: em GitHub Actions o runner é efêmero — sem um passo de
# "git commit/push" desse arquivo de volta pro repo (ou um storage externo),
# ele é perdido a cada execução e o histórico nunca acumula. Ver nota no chat.
HISTORICO_PATH = "historico_apostas.json"

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
# 3. FONTE DE DADOS: TABELA (football-data.org)
# ==========================================
def buscar_tabela_competicao(codigo_competicao):
    """Retorna dict: chave_canonica(time) -> {texto, media_pro, media_contra}"""
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
                tabela[chave_canonica(nome)] = {
                    "texto": resumo,
                    "media_pro": media_pro,
                    "media_contra": media_contra
                }
        return tabela
    except Exception:
        return {}

# ==========================================
# 4. MODELO ESTATÍSTICO (Poisson) — NOVO
# ==========================================
def _poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)

def calcular_probabilidades_poisson(exp_casa, exp_fora, max_gols=6):
    """Modelo simples de Poisson independente (sem ajuste de liga/mando de campo
    além da própria média de gols pró/contra). É uma aproximação, não uma
    predição precisa — serve pra dar um número de referência ao invés de
    decisão puramente narrativa."""
    p_casa = p_empate = p_fora = p_over25 = 0.0
    for i in range(max_gols + 1):
        for j in range(max_gols + 1):
            p = _poisson_pmf(i, exp_casa) * _poisson_pmf(j, exp_fora)
            if i > j: p_casa += p
            elif i == j: p_empate += p
            else: p_fora += p
            if i + j >= 3: p_over25 += p
    return {
        "casa": p_casa, "empate": p_empate, "fora": p_fora,
        "over25": p_over25, "under25": 1 - p_over25
    }

def probabilidades_implicitas_sem_vig(odds_dict):
    """Remove a margem da casa (overround) normalizando as probabilidades
    implícitas (1/odd) pra somarem 100%. Sem isso, a comparação com o modelo
    fica injustamente pessimista pro lado do modelo."""
    implicitas = {k: (1 / v) for k, v in odds_dict.items() if v}
    soma = sum(implicitas.values())
    if soma == 0: return {}
    return {k: v / soma for k, v in implicitas.items()}

def montar_texto_modelo(home_team, away_team, resumo_casa, resumo_fora, odds_h2h, odds_totals_25):
    if not (isinstance(resumo_casa, dict) and isinstance(resumo_fora, dict)):
        return "MODELO: indisponível (faltam médias de gols na tabela pra um dos dois times)"

    exp_casa = (resumo_casa["media_pro"] + resumo_fora["media_contra"]) / 2
    exp_fora = (resumo_fora["media_pro"] + resumo_casa["media_contra"]) / 2
    probs = calcular_probabilidades_poisson(exp_casa, exp_fora)

    partes = [f"Casa {probs['casa']*100:.0f}% / Empate {probs['empate']*100:.0f}% / Fora {probs['fora']*100:.0f}%"]

    if odds_h2h:
        fair = probabilidades_implicitas_sem_vig(odds_h2h)
        for nome, prob_modelo in [(home_team, probs['casa']), ("Draw", probs['empate']), (away_team, probs['fora'])]:
            prob_odd = fair.get(nome)
            if prob_odd is not None and prob_modelo - prob_odd >= 0.03:
                partes.append(f"[VALOR em {nome}: modelo {prob_modelo*100:.0f}% vs mercado {prob_odd*100:.0f}%]")

    if odds_totals_25:
        fair_t = probabilidades_implicitas_sem_vig(odds_totals_25)
        for nome, prob_modelo in [("Over", probs['over25']), ("Under", probs['under25'])]:
            prob_odd = fair_t.get(nome)
            if prob_odd is not None and prob_modelo - prob_odd >= 0.03:
                partes.append(f"[VALOR em {nome} 2.5: modelo {prob_modelo*100:.0f}% vs mercado {prob_odd*100:.0f}%]")

    return "MODELO (Poisson, baseado em médias reais de gols): " + " | ".join(partes)

# ==========================================
# 5. ETAPA 1: BUSCAR ODDS E MONTAR BASE
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

                        odds_h2h = {}
                        odds_totals_25 = {}
                        odds_str_list = []
                        for market in bm['markets']:
                            m_key = market['key'].upper()
                            outcomes_list = []
                            for o in market['outcomes'][:6]:
                                point = f" {o.get('point')}" if o.get('point') is not None else ""
                                outcomes_list.append(f"{o.get('name')}{point}: {o.get('price')}")
                                if market['key'] == 'h2h' and o.get('price'):
                                    odds_h2h[o.get('name')] = o.get('price')
                                if market['key'] == 'totals' and o.get('point') == 2.5 and o.get('price'):
                                    odds_totals_25[o.get('name')] = o.get('price')
                            odds_str_list.append(f"[{m_key}] {' / '.join(outcomes_list)}")

                        resumo_casa = buscar_em_dicionario(tabela_liga, jogo['home_team'])
                        resumo_fora = buscar_em_dicionario(tabela_liga, jogo['away_team'])
                        texto_casa = resumo_casa["texto"] if isinstance(resumo_casa, dict) else "Sem dados de tabela"
                        texto_fora = resumo_fora["texto"] if isinstance(resumo_fora, dict) else "Sem dados de tabela"
                        modelo_texto = montar_texto_modelo(
                            jogo['home_team'], jogo['away_team'],
                            resumo_casa, resumo_fora, odds_h2h, odds_totals_25
                        )

                        info_jogo = (
                            f"LIGA: {liga} | DATA: {data_jogo} \n"
                            f"CASA: {jogo['home_team']} (Tabela: {texto_casa}) \n"
                            f"FORA: {jogo['away_team']} (Tabela: {texto_fora}) \n"
                            f"ODDS: {' | '.join(odds_str_list)} \n"
                            f"{modelo_texto} \n"
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
# 6. ETAPA 1: IA MONTA MÚLTIPLA CANDIDATA
# ==========================================
def analisar_com_ia_candidata(lista_de_jogos):
    prompt_master = f"""
    Você é Analista Sênior de Sports Trading na Betano.
    MISSÃO: montar 1 múltipla candidata (odd ~20.00), com jogos do texto abaixo.

    REGRAS DE OURO:
    1. Baseie-se em posição, saldo, forma recente, odds e, principalmente, na linha MODELO
       (probabilidade calculada via Poisson a partir de médias reais de gols). Quando o MODELO
       marcar [VALOR] em um mercado, isso é um sinal estatístico real — priorize esses mercados.
       Quando o MODELO estiver indisponível para um jogo, trate a escolha ali como mais especulativa.
    2. Só use mercados com dado real por trás: vencedor (H2H) e Over/Under de gols (TOTALS).
       Não invente ou infira estatísticas de escanteios/cartões — não há dado confiável pra isso
       nesta versão do robô, então NÃO inclua esses mercados.
    3. NÃO combine duas seleções do mesmo jogo (ex: vencedor + over gols do mesmo confronto),
       mesmo que pareça aumentar a odd — mercados do mesmo jogo costumam ser correlacionados
       (ex: time favorito vencer e o jogo ter mais gols andam juntos), e isso infla a odd
       combinada sem valor estatístico real correspondente. Uma seleção por jogo.

    FORMATO OBRIGATÓRIO:
    Responda apenas com o texto da múltipla e as justificativas breves (cite o MODELO quando usar).
    NO FINAL DA MENSAGEM, adicione exatamente a tag ###JOGOS_ESCOLHIDOS### e abaixo dela um JSON
    com os jogos escolhidos, incluindo o mercado e a seleção exatos:
    [{{"home": "Time A", "away": "Time B", "mercado": "H2H", "selecao": "Time A", "odd": 1.85}},
     {{"home": "Time C", "away": "Time D", "mercado": "TOTALS", "selecao": "Over", "ponto": 2.5, "odd": 1.72}}]

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
# 7. ETAPA 2: IA "GOOGLA" OS JOGOS ESCOLHIDOS
#    (agora focada só no que os dados estruturados NÃO cobrem:
#    desfalques de última hora e confrontos diretos recentes)
# ==========================================
def refinar_com_google_search(bilhete_candidato, jogos_escolhidos):
    if not jogos_escolhidos:
        return bilhete_candidato

    lista_jogos_str = ", ".join([f"{j.get('home')} vs {j.get('away')}" for j in jogos_escolhidos])

    prompt_refinamento = f"""
    Você montou a seguinte múltipla candidata, já baseada em modelo estatístico (Poisson) e odds:
    {bilhete_candidato}

    Use a ferramenta de Busca do Google (Google Search) para checar, para cada confronto abaixo,
    apenas o que os dados estruturados do robô NÃO cobrem:
    {lista_jogos_str}

    PESQUISE ESPECIFICAMENTE:
    1. Desfalques/lesões/suspensões de última hora que possam mudar o time titular esperado.
    2. Histórico recente de CONFRONTOS DIRETOS entre as duas equipes (placar e dinâmica dos últimos encontros).

    🚨 REGRA ANTI-ALUCINAÇÃO:
    Trabalhe APENAS com os dados reais retornados pela busca. Se faltar algum dado exato, escreva
    "Dado não localizado na busca". NUNCA invente estatísticas.

    TAREFA DE REFINAMENTO:
    - Cruze o resultado da sua pesquisa com o bilhete que você montou.
    - Se um desfalque relevante contradiz a tese estatística (ex: artilheiro suspenso), TROQUE o
      mercado escolhido para algo mais seguro, ou remova essa perna se não houver alternativa segura.
    - Caso contrário, mantenha e enriqueça a justificativa.

    FORMATO DE SAÍDA EXIGIDO:
    Crie o bilhete final no padrão profissional do Telegram. Na seção de 🔍 FUNDAMENTAÇÃO TÁTICA,
    ao final da explicação de CADA JOGO, adicione OBRIGATORIAMENTE esta linha exata:

    **📊 Checagem:** Desfalques: [X] | Confrontos diretos recentes: [Breve resumo]

    Responda diretamente com o bilhete formatado.
    """

    ultimo_erro_foi_quota = False
    for key in GEMINI_KEYS:
        try:
            print(f"[Etapa 2] Ativando Agente com Google Search (Chave {key[-4:]})...")
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
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                ultimo_erro_foi_quota = True
                print(f"[Etapa 2] Cota de grounding esgotada na chave {key[-4:]}.")
            else:
                print(f"[Etapa 2] Erro na chave {key[-4:]}: {e}")
            continue

    print("[Etapa 2] Todas as chaves falharam. Formatando fallback sem busca...")
    return formatar_fallback_sem_busca(bilhete_candidato, ultimo_erro_foi_quota)


def formatar_fallback_sem_busca(bilhete_candidato, foi_erro_de_quota):
    aviso = (
        "⚠️ Checagem de desfalques/confrontos diretos indisponível hoje "
        "(cota de grounding esgotada no projeto)." if foi_erro_de_quota else
        "⚠️ Checagem de desfalques/confrontos diretos indisponível hoje."
    )

    prompt_fallback = f"""
    Reformate o texto abaixo no padrão profissional de bilhete para Telegram
    (título, lista numerada de seleções com odd e justificativa breve, sem inventar
    nenhuma estatística nova).

    Para cada jogo, ao final da justificativa, adicione exatamente esta linha:
    **📊 Checagem:** Dado não localizado na busca (checagem indisponível nesta execução).

    No topo da mensagem, inclua esta linha de aviso, sem alterá-la:
    {aviso}

    TEXTO ORIGINAL:
    {bilhete_candidato}
    """
    for key in GEMINI_KEYS:
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_fallback,
                config=types.GenerateContentConfig(temperature=0.1)
            )
            return response.text
        except Exception:
            continue

    return f"{aviso}\n\n{bilhete_candidato}"

# ==========================================
# 8. HISTÓRICO E VERIFICAÇÃO DE RESULTADOS — NOVO
# ==========================================
def carregar_historico():
    if os.path.exists(HISTORICO_PATH):
        try:
            with open(HISTORICO_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def salvar_historico(historico):
    try:
        with open(HISTORICO_PATH, "w", encoding="utf-8") as f:
            json.dump(historico, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Histórico] Falha ao salvar: {e}")

def registrar_bilhete(escolhidos):
    if not escolhidos:
        return
    historico = carregar_historico()
    historico.append({
        "data_envio": datetime.now(timezone.utc).isoformat(),
        "jogos": escolhidos,
        "status": "pendente"
    })
    salvar_historico(historico)

def _avaliar_selecao(jogo_registrado, placar_casa, placar_fora):
    mercado = (jogo_registrado.get("mercado") or "").upper()
    selecao = (jogo_registrado.get("selecao") or "").strip()

    if mercado == "H2H":
        if placar_casa > placar_fora:
            vencedor = jogo_registrado["home"]
        elif placar_fora > placar_casa:
            vencedor = jogo_registrado["away"]
        else:
            vencedor = "Draw"
        if selecao.lower() == "draw":
            return "green" if vencedor == "Draw" else "red"
        return "green" if times_equivalentes(vencedor, selecao) else "red"

    if mercado == "TOTALS":
        total = placar_casa + placar_fora
        ponto = jogo_registrado.get("ponto", 2.5)
        if "over" in selecao.lower():
            return "green" if total > ponto else "red"
        if "under" in selecao.lower():
            return "green" if total < ponto else "red"

    return "manual"  # spreads e outros mercados não são graduados automaticamente

def verificar_resultados_pendentes():
    """Confere, via endpoint de scores da própria Odds API, o resultado real
    dos bilhetes ainda pendentes e grada green/red. Retorna um resumo em texto
    (ou None se não houver nada novo pra reportar)."""
    historico = carregar_historico()
    pendentes = [h for h in historico if h["status"] == "pendente"]
    if not pendentes:
        return None

    placares_por_liga = {}
    for liga in LIGAS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga}/scores/"
        params = {"apiKey": ODDS_API_KEY, "daysFrom": 3}
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            placares_por_liga[liga] = resp.json()
        except Exception:
            placares_por_liga[liga] = []

    recem_verificados = []
    for entrada in pendentes:
        todos_resolvidos = True
        for jogo in entrada["jogos"]:
            if jogo.get("resultado") in ("green", "red", "manual"):
                continue
            encontrado = False
            for resultados_liga in placares_por_liga.values():
                for r in resultados_liga:
                    if not r.get("completed"):
                        continue
                    if not (times_equivalentes(r.get("home_team", ""), jogo["home"]) and
                            times_equivalentes(r.get("away_team", ""), jogo["away"])):
                        continue
                    scores = {s["name"]: int(s["score"]) for s in r.get("scores", []) if s.get("score") is not None}
                    placar_casa = next((v for k, v in scores.items() if times_equivalentes(k, jogo["home"])), None)
                    placar_fora = next((v for k, v in scores.items() if times_equivalentes(k, jogo["away"])), None)
                    if placar_casa is None or placar_fora is None:
                        continue
                    jogo["placar"] = f"{placar_casa}x{placar_fora}"
                    jogo["resultado"] = _avaliar_selecao(jogo, placar_casa, placar_fora)
                    encontrado = True
                    break
                if encontrado:
                    break
            if not encontrado:
                todos_resolvidos = False
        if todos_resolvidos:
            entrada["status"] = "verificado"
            recem_verificados.append(entrada)

    salvar_historico(historico)

    if not recem_verificados:
        return None

    todos_graduados = [j for e in historico if e["status"] == "verificado" for j in e["jogos"] if j.get("resultado") in ("green", "red")]
    if not todos_graduados:
        return None
    greens = sum(1 for j in todos_graduados if j["resultado"] == "green")
    total = len(todos_graduados)
    taxa = (greens / total * 100) if total else 0

    linhas = [f"📈 *Resultados verificados agora:*"]
    for entrada in recem_verificados:
        for j in entrada["jogos"]:
            emoji = "✅" if j.get("resultado") == "green" else ("❌" if j.get("resultado") == "red" else "➖")
            linhas.append(f"{emoji} {j['home']} x {j['away']} ({j.get('mercado','?')}: {j.get('selecao','?')}) — {j.get('placar','?')}")
    linhas.append(f"\n*Taxa de acerto histórica (seleções graduáveis): {greens}/{total} = {taxa:.0f}%*")
    return "\n".join(linhas)

# ==========================================
# 9. TELEGRAM E EXECUÇÃO
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
    print("Iniciando Robô Trader (Versão Analítica - Modelo + Histórico)...")

    resumo_resultados = verificar_resultados_pendentes()
    if resumo_resultados:
        enviar_telegram(resumo_resultados)

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
        print(f"Etapa 2: IA checando desfalques e confrontos diretos de {len(escolhidos)} jogo(s)...")
        bilhete_final = refinar_com_google_search(candidata, escolhidos)
    else:
        bilhete_final = candidata

    enviar_telegram(bilhete_final.strip())
    registrar_bilhete(escolhidos)
    print("\nConcluído!")
