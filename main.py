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

# Rotação alinhada com os Secrets do seu GitHub (6 chaves no total)
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

# Chave gratuita do football-data.org (crie a conta em football-data.org/client/register)
FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")

LIGAS = [
    "soccer_brazil_campeonato",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_epl",
    "soccer_uefa_champs_league"
]

# Mapa das suas ligas (Odds API) pro código de competição do football-data.org
# As 5 ligas que você usa estão TODAS cobertas pelo plano gratuito.
MAPA_COMPETICOES_FOOTBALL_DATA = {
    "soccer_brazil_campeonato": "BSA",
    "soccer_spain_la_liga": "PD",
    "soccer_italy_serie_a": "SA",
    "soccer_epl": "PL",
    "soccer_uefa_champs_league": "CL",
}

# ==========================================
# 2. FUNÇÃO: BUSCAR TABELA/FORMA REAL (football-data.org)
#    Dado verificado — reduz a dependência do Gemini "adivinhar"
#    posição/forma via busca de texto.
# ==========================================
def buscar_tabela_competicao(codigo_competicao):
    if not FOOTBALL_DATA_API_KEY or not codigo_competicao:
        return {}

    url = f"https://api.football-data.org/v4/competitions/{codigo_competicao}/standings"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    try:
        resposta = requests.get(url, headers=headers, timeout=10)
        resposta.raise_for_status()
        dados = resposta.json()

        tabela = {}
        for grupo in dados.get("standings", []):
            if grupo.get("type") != "TOTAL":
                continue
            for time in grupo.get("table", []):
                nome = time["team"]["name"]
                forma = time.get("form") or "sem histórico recente"
                resumo = (
                    f"{time['position']}º lugar, {time['points']}pts "
                    f"({time['won']}V-{time['draw']}E-{time['lost']}D), "
                    f"saldo de gols {time['goalDifference']}, forma recente: {forma}"
                )
                tabela[nome.lower()] = resumo
        return tabela
    except requests.exceptions.RequestException as e:
        print(f"Aviso: não consegui buscar a tabela de {codigo_competicao} no football-data.org: {e}")
        return {}

def encontrar_resumo_time(tabela, nome_time):
    if not tabela:
        return "sem dados de tabela disponíveis"
    nome_time_lower = nome_time.lower()
    for nome_tabela, resumo in tabela.items():
        if nome_time_lower in nome_tabela or nome_tabela in nome_time_lower:
            return resumo
    return "time não encontrado na tabela (nome pode divergir entre as fontes)"

# ==========================================
# 3. FUNÇÃO: BUSCAR JOGOS E ODDS (COM TABELA REAL INJETADA)
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    hoje_utc = datetime.now(timezone.utc).date()
    tabelas_cache = {}  # evita buscar a mesma tabela mais de uma vez

    for liga in LIGAS:
        codigo_fd = MAPA_COMPETICOES_FOOTBALL_DATA.get(liga)
        if codigo_fd and codigo_fd not in tabelas_cache:
            print(f"Buscando tabela real de {liga} no football-data.org...")
            tabelas_cache[codigo_fd] = buscar_tabela_competicao(codigo_fd)
        tabela_liga = tabelas_cache.get(codigo_fd, {})

        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h"}
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
                        bm_betano = next((b for b in bookmakers if b['key'] == 'betano'), bookmakers[0])
                        odds = bm_betano['markets'][0]['outcomes']
                        resumo_casa = encontrar_resumo_time(tabela_liga, jogo['home_team'])
                        resumo_fora = encontrar_resumo_time(tabela_liga, jogo['away_team'])
                        info_jogo = (
                            f"LIGA: {liga} | DATA: {data_jogo} | "
                            f"{jogo['home_team']} (mandante — tabela real: {resumo_casa}) vs "
                            f"{jogo['away_team']} (visitante — tabela real: {resumo_fora}) | "
                            f"ODDS (Casa: {bm_betano['title']}): {odds}"
                        )
                        jogos_disponiveis.append(info_jogo)
        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    print(f"Total de jogos encontrados: {len(jogos_disponiveis)}")
    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR TODOS OS BILHETES (CORRIGIDA)
#    Agora tenta TODAS as chaves pra QUALQUER erro,
#    não só 429 — e só desiste depois de esgotar as 6.
# ==========================================
def analisar_com_ia_unificada(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo encontrado para hoje ou amanhã nas ligas selecionadas."

    prompt_master = f"""
    Atue como um Analista Estatístico Sênior e Especialista em Quantitative Sports Trading na Betano.

    SUA MISSÃO:
    Analisar os jogos disponíveis hoje/amanhã com a postura de um 'Advogado do Diabo' (estritamente cético e rigoroso). Em uma ÚNICA resposta, montar TRÊS apostas múltiplas distintas cruzando microfatores táticos (xG, cartões, desfalques, árbitros). REGRA DE OURO: NUNCA alucine ou invente estatísticas. Trabalhe apenas com dados reais pesquisados ou fornecidos. As três múltiplas devem obrigatoriamente ser formadas por jogos da MESMA DATA.

    IMPORTANTE: os dados de "tabela real" (posição, pontos, forma recente V/E/D, saldo de gols) já vêm
    verificados diretamente do football-data.org, ao lado de cada time na lista de jogos abaixo — use-os
    como base confiável de contexto. Cartões, escanteios e xG específicos ainda precisam ser pesquisados
    por você via busca.

    ESTRUTURA DAS MÚLTIPLAS EXIGIDAS:
    1. 🛡️ MÚLTIPLA CONSERVADORA: Odd total máxima de 10. Foco extremo em segurança, favoritos absolutos ou under gols em jogos travados. Stake sugerida: 0,50u.
    2. 🎯 MÚLTIPLA PREMIUM (PADRÃO): Odd total mínima de 20. Foco em EV+ equilibrado, mercados de cartões, cantos e duplas chances. Stake sugerida: 0,20u.
    3. 🚀 MÚLTIPLA MOONSHOT (OUSADA): Odd total mínima de 100. Foco em variância, empates em clássicos, viradas ou combinação longa de mercados. Stake sugerida: 0,05u.

    DIRETRIZES DE PESQUISA E FILTROS (Aplique a todas as múltiplas):
    1. ANÁLISE DE EXPECTATIVA DE GOLS (xG) E DESEMPENHO CASA x FORA (Splits):
       - Não olhe apenas a forma geral. Isole o desempenho do Mandante jogando EM CASA e do Visitante jogando FORA.
       - Avalie o "Strength of Schedule" (Força do Calendário): as vitórias recentes foram contra times do topo ou da base da tabela?
       - Defesa Sólida vs Ataque Ineficiente: Avalie a métrica de "Clean Sheets" (jogos sem sofrer gol) do mandante contra a taxa de conversão do visitante.

    2. TRAVA DE ESCANTEIOS E "GAME SCRIPT":
       - Se o favorito tem alta probabilidade de abrir o placar cedo, PROÍBA cantos a favor dele (o mercado morre). Evite cantos contra defesas em blocos baixos.

    3. PERFIL DO ÁRBITRO E CLIMA DA PARTIDA (Mercado de Cartões):
       - Para validar uma linha alta de cartões, exija cruzamento duplo obrigatório: Árbitro com média historicamente rígida (acima de 5.5) E histórico recente de descontrole disciplinar de ambas as equipes. Se a partida tender a ser de estudo e cautela, fuja dos cartões.
       - Se não houver dados concretos do árbitro, aborte a entrada em cartões.

    4. MOTIVAÇÃO, FADIGA E FATORES EXTERNOS (Game State):
       - Times que viajaram muito ou têm menos de 72h de descanso devem tender a Under Gols.
       - Retrospecto e Game State: Avalie a necessidade real de pontos de cada time e o retrospecto recente no torneio específico.
       - Filtro de Desfalques e Elenco: Garanta a presença dos pilares táticos e evite partidas com rotação excessiva de elenco (time reserva/misto).

    5. VALOR REAL EM ODDS BAIXAS E FUGA DE "TRAP ODDS":
       - Odds baixas são válidas quando refletem um abismo técnico inegável (ex: elite titular em casa vs time de 2ª divisão). No entanto, descarte sumariamente odds esmagadas (como 1.05) que não compensam o risco de variância.

    6. POSTURA ANTI-ALUCINAÇÃO E RIGOR DE AMOSTRA:
       - Não force encaixes. Se a amostra de dados for insuficiente ou a estatística não estiver disponível, recuse o mercado. Só aprove seleções que resistam à ótica rigorosa de risco x retorno.
       - Amostragem Recente (Últimos 10 Jogos): Fundamente cada escolha na média e na frequência dos últimos 10 jogos oficiais de cada equipe e atleta.

    7. TRANSPARÊNCIA E CITAÇÃO DE FONTES OBRIGATÓRIA:
       - Forneça a fonte exata de onde extraiu cada estatística utilizada (ex: FBref, Sofascore, imagens fornecidas, painel Betano).
       - Apresente as médias reais (de escanteios, cartões, xG, etc.) diretamente ligadas ao argumento de validação da perna do bilhete.

    8. VÁLVULA DE ESCAPE (DIAS DE GRADE RUIM E BAIXA LIQUIDEZ):
       - Se a grade de jogos do dia for fraca ou não houver dados sólidos o suficiente para sustentar odds altas de forma estatisticamente segura, você AINDA DEVE montar as Múltiplas Premium e Moonshot para cumprir a ordem.
       - PORÉM, é obrigatório incluir um [⚠️ AVISO DE RISCO DESTACADO] antes do bilhete, alertando o usuário de forma franca que forçar essas odds naquele dia específico é perigoso e contraria o rigor analítico.

    ======================================================================
    FORMATO DA RESPOSTA FINAL (PARA O TELEGRAM):
    ======================================================================
    Monte os três bilhetes na mesma resposta, separando CADA UM DELES estritamente pelo marcador "==========" em uma linha isolada.

    📅 *DATA ESCOLHIDA PARA TODOS OS BILHETES:* [DD/MM/AAAA]

    🔥 BILHETE 1: CONSERVADOR (Odd Máx: 10) 🔥
    [⚠️ AVISO DE RISCO: Insira aqui apenas se a grade não oferecer valor seguro, ou omita esta linha se o dia for bom]
    *Stake:* 0,50u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX

    🔍 *ANÁLISE E FONTES:*
    [Escreva um parágrafo completo explicando a estratégia tática do bilhete, cruzamento de métricas, as médias obtidas e citando obrigatoriamente as fontes consultadas de cada dado.]

    ==========

    🔥 BILHETE 2: PREMIUM (Odd Mín: 20) 🔥
    [⚠️ AVISO DE RISCO: Insira aqui se estiver forçando entradas por falta de jogos bons, ou omita se o dia for bom]
    *Stake:* 0,20u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX

    🔍 *ANÁLISE E FONTES:*
    [Escreva um parágrafo completo explicando a estratégia tática do bilhete, cruzamento de métricas, as médias obtidas e citando obrigatoriamente as fontes consultadas de cada dado.]

    ==========

    🔥 BILHETE 3: MOONSHOT (Odd Mín: 100) 🔥
    [⚠️ AVISO DE RISCO: Insira aqui se a variância for puramente lotérica pela grade fraca, ou omita se tiver embasamento]
    *Stake:* 0,05u
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    3. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX

    🔍 *ANÁLISE E FONTES:*
    [Escreva um parágrafo completo explicando a estratégia tática do bilhete, cruzamento de métricas, as médias obtidas e citando obrigatoriamente as fontes consultadas de cada dado.]

    ======================================================================
    CHECKLIST DE VERIFICAÇÃO OBRIGATÓRIA (FAÇA ANTES DE ENVIAR)
    ======================================================================
    Antes de gerar o relatório final para o Telegram, confirme internamente se você executou todas as etapas abaixo. Inclua este checklist resumido no final da sua resposta para auditoria:

    1. [ ] Analisei o xG e os splits de desempenho Casa x Fora de cada equipe?
    2. [ ] Apliquei a trava de escanteios (proibindo cantos para favoritos que abrem o placar cedo ou contra blocos baixos)?
    3. [ ] Validei o cruzamento duplo do árbitro (>5.5) e o clima disciplinar para os cartões?
    4. [ ] Verifiquei fadiga, viagens ou menos de 72h de descanso (tendência a Under)?
    5. [ ] Eliminei "trap odds" e garanto que todas as pernas pertencem estritamente à MESMA DATA?
    6. [ ] Citei as fontes reais de dados (ex: FBref, Sofascore) para cada estatística utilizada?
    7. [ ] O [⚠️ AVISO DE RISCO] foi incluído caso a grade estivesse fraca e as odds tenham sido forçadas?

    JOGOS DISPONÍVEIS:
    {lista_de_jogos}
    """

    ultimo_erro = None
    for i, key in enumerate(GEMINI_KEYS):
        try:
            print(f"Tentando conexão com o Gemini usando a Chave #{i+1}...")
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=prompt_master,
                config=types.GenerateContentConfig(
                    tools=[{"google_search": {}}],
                    temperature=0.2  # mais baixo = raciocínio mais conservador e consistente
                )
            )
            print(f"Sucesso com a Chave #{i+1}.")
            return response.text
        except Exception as e:
            # CORREÇÃO: agora tenta a PRÓXIMA chave pra QUALQUER tipo de erro,
            # não só 429 — algumas contas podem não ter acesso ao modelo,
            # ter chave inválida, etc. Só desiste depois de esgotar todas.
            print(f"Erro com a Chave #{i+1}: {e}")
            ultimo_erro = e
            continue

    return f"Erro crítico: Todas as {len(GEMINI_KEYS)} chaves falharam. Último erro: {ultimo_erro}"

# ==========================================
# 4. FUNÇÃO: ENVIAR PARA O TELEGRAM (CORRIGIDA)
#    Se o Markdown falhar (texto com * ou [ desbalanceado),
#    tenta de novo em texto puro em vez de perder a mensagem.
# ==========================================
def enviar_telegram(mensagem):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados nos secrets.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    mensagem_formatada = mensagem[:4090] if len(mensagem) > 4096 else mensagem

    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem_formatada, "parse_mode": "Markdown"}
    try:
        resposta = requests.post(url, json=payload)
        resposta.raise_for_status()
        print("Mensagem enviada com sucesso (Markdown).")
        return
    except requests.exceptions.RequestException as e:
        print(f"Falha ao enviar com Markdown ({e}). Tentando de novo em texto puro...")

    # Fallback: manda sem formatação, pra garantir que a mensagem chegue de qualquer jeito
    payload_sem_formato = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem_formatada}
    try:
        resposta = requests.post(url, json=payload_sem_formato)
        resposta.raise_for_status()
        print("Mensagem enviada com sucesso (texto puro, sem formatação).")
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar para o Telegram mesmo em texto puro: {e}")

# ==========================================
# 5. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos...")
    grade_hoje = buscar_jogos_do_dia()

    if not grade_hoje:
        print("Nenhum jogo encontrado. Encerrando execução.")
        exit()

    print("Iniciando análise única com o Gemini 3.6 Flash...")
    resposta_ia = analisar_com_ia_unificada(grade_hoje)

    if "Erro crítico" in resposta_ia or "Erro na análise" in resposta_ia:
        print("Falha ao gerar os bilhetes. Enviando alerta de erro.")
        enviar_telegram(f"❌ {resposta_ia}")
    else:
        # Split mais tolerante: aceita variações de quantidade de "=" e espaços ao redor
        bilhetes = re.split(r'\n\s*=+\s*\n', resposta_ia)

        for bilhete in bilhetes:
            bilhete_limpo = bilhete.strip()
            if bilhete_limpo:
                print("Enviando bilhete fatiado para o Telegram...")
                enviar_telegram(bilhete_limpo)
                time.sleep(3)

    print("\nProcesso concluído com sucesso!")
