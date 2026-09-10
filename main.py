import os
import time
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
    os.getenv("GEMINI_API_KEY") # Chave principal como backup final
]
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
# 3. FUNÇÃO: PROCESSAR UM BILHETE POR VEZ COM O GEMINI
# ==========================================
def analisar_com_ia(lista_de_jogos, perfil_descricao):
    if not lista_de_jogos:
        return "Nenhum jogo encontrado para hoje ou amanhã nas ligas selecionadas."

    prompt_master = f"""
    Atue como um Analista Estatístico Sênior e Especialista em Quantitative Sports Trading na Betano.
    
    SUA MISSÃO:
    Analisar os jogos disponíveis hoje/amanhã com a postura de um 'Advogado do Diabo' (estritamente cético e rigoroso). Em uma ÚNICA resposta, montar APENAS UMA aposta múltipla focada estritamente no seguinte perfil:
    
    {perfil_descricao}
    
    REGRA DE OURO: NUNCA alucine ou invente estatísticas. Trabalhe apenas com dados reais pesquisados ou fornecidos. As seleções devem obrigatoriamente pertencer à MESMA DATA.

    DIRETRIZES DE PESQUISA E FILTROS:
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
       - Forneça a fonte exata de onde extraiu cada estatística utilizada (ex: FBref, Sofascore).
       - Apresente as médias reais (de escanteios, cartões, xG, etc.) diretamente ligadas ao argumento de validação da perna do bilhete.

    8. VÁLVULA DE ESCAPE (DIAS DE GRADE RUIM E BAIXA LIQUIDEZ):
       - Se a grade de jogos for fraca ou não houver dados sólidos o suficiente para sustentar odds, você AINDA DEVE montar a múltipla para cumprir a ordem.
       - PORÉM, é obrigatório incluir um [⚠️ AVISO DE RISCO DESTACADO] antes do bilhete, alertando que forçar essas odds naquele dia específico é perigoso.

    ======================================================================
    FORMATO DA RESPOSTA FINAL (PARA O TELEGRAM):
    ======================================================================
    📅 *DATA ESCOLHIDA PARA O BILHETE:* [DD/MM/AAAA]

    [⚠️ AVISO DE RISCO: Insira aqui se a grade for fraca, ou omita se o dia for bom]
    *Stake:* [Preencha com a sugerida no perfil]
    1. [Liga] Jogo | Mercado | Odd: X.XX
    2. [Liga] Jogo | Mercado | Odd: X.XX
    ...
    💰 *ODD TOTAL:* XX.XX
    
    🔍 *ANÁLISE E FONTES:* 
    [Escreva um parágrafo completo explicando a estratégia tática, cruzamento de métricas, as médias obtidas e citando as fontes consultadas de cada dado.]

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
    
    # Prevenção extra caso o relatório ultrapasse o limite de caracteres do Telegram
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
    
    if not grade_hoje:
        print("Nenhum jogo encontrado. Encerrando execução.")
        exit()

    perfis_de_aposta = [
        {
            "nome": "CONSERVADORA", 
            "descricao": "Múltipla CONSERVADORA (Odd total máxima de 10). Foco extremo em segurança, favoritos absolutos ou under gols em jogos travados. Stake sugerida: 0,50u."
        },
        {
            "nome": "PREMIUM", 
            "descricao": "Múltipla PREMIUM (PADRÃO) (Odd total mínima de 20). Foco em EV+ equilibrado, mercados de cartões, cantos e duplas chances. Stake sugerida: 0,20u."
        },
        {
            "nome": "MOONSHOT", 
            "descricao": "Múltipla MOONSHOT (OUSADA) (Odd total mínima de 100). Foco em variância, empates em clássicos, viradas ou combinação longa de mercados. Stake sugerida: 0,05u."
        }
    ]

    print("Iniciando geração sequencial das múltiplas...")
    
    for perfil in perfis_de_aposta:
        print(f"\n--- Gerando bilhete: {perfil['nome']} ---")
        
        bilhete = analisar_com_ia(grade_hoje, perfil["descricao"])
        
        if "Erro crítico" not in bilhete and "Erro na análise" not in bilhete:
            mensagem_telegram = f"🔥 BILHETE {perfil['nome']} 🔥\n\n{bilhete}"
            print(f"Enviando bilhete {perfil['nome']} para o Telegram...")
            enviar_telegram(mensagem_telegram)
        else:
            print(f"Falha ao gerar o bilhete {perfil['nome']}. Enviando alerta de erro.")
            enviar_telegram(f"❌ Falha ao gerar o bilhete {perfil['nome']}:\n{bilhete}")
        
        # Pausa de 15 segundos para proteger o limite de RPM da API gratuita
        print("Pausando 15 segundos para resfriamento da API...")
        time.sleep(15)
        
    print("\nProcesso concluído com sucesso!")
