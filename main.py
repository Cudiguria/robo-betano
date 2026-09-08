import os
import requests
from datetime import datetime, timezone
from twilio.rest import Client

# ==========================================
# 1. CONFIGURAÇÕES E CHAVES DE API
# ==========================================
# Contas necessárias: the-odds-api.com, aistudio.google.com e twilio.com
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "COLOQUE_SUA_CHAVE_ODDS_AQUI")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "COLOQUE_SUA_CHAVE_GEMINI_AQUI")

# Credenciais da Twilio para o WhatsApp
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "COLOQUE_SEU_SID_AQUI")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "COLOQUE_SEU_TOKEN_AQUI")
TWILIO_WHATSAPP_REMETENTE = os.getenv("TWILIO_WHATSAPP_REMETENTE", "whatsapp:+14155238886") # Número padrão do Sandbox
MEU_WHATSAPP = os.getenv("MEU_WHATSAPP", "whatsapp:+5511999999999") # Seu número com DDI e DDD

# Ligas de Elite + Ligas de Valor Estatístico
LIGAS = [
    "soccer_epl", "soccer_uefa_champs", "soccer_brazil_campeonato", "soccer_spain_la_liga", 
    "soccer_netherlands_eerste_divisie", "soccer_england_championship", "soccer_japan_j_league", "soccer_usa_mls"
]

# ==========================================
# 2. FUNÇÃO: BUSCAR JOGOS E ODDS DA BETANO
# ==========================================
def buscar_jogos_do_dia():
    jogos_disponiveis = []
    
    for liga in LIGAS:
        url = f"https://api.the-odds-api.com/v4/sports/{liga}/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "bookmakers": "betano"
        }
        
        try:
            resposta = requests.get(url, params=params)
            resposta.raise_for_status()
            dados = resposta.json()
            
            for jogo in dados:
                data_jogo = datetime.strptime(jogo['commence_time'], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if data_jogo.date() == datetime.now(timezone.utc).date():
                    if jogo.get('bookmakers'):
                        odds = jogo['bookmakers'][0]['markets'][0]['outcomes']
                        info_jogo = f"LIGA: {liga} | {jogo['home_team']} vs {jogo['away_team']} | ODDS 1X2: {odds}"
                        jogos_disponiveis.append(info_jogo)
        
        except requests.exceptions.RequestException as e:
            print(f"Erro ao buscar liga {liga}: {e}")
            continue

    return "\n".join(jogos_disponiveis)

# ==========================================
# 3. FUNÇÃO: PROCESSAR COM O GEMINI 
# ==========================================
def analisar_com_ia(lista_de_jogos):
    if not lista_de_jogos:
        return "Nenhum jogo com odds da Betano encontrado para hoje nas ligas selecionadas."

    url_gemini = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt_master = f"""
    Atue como meu especialista e analista estatístico de apostas esportivas na Betano.
    
    INSTRUÇÃO DE EXECUÇÃO:
    Abaixo está a lista real de jogos de hoje com cotações (odds) da Betano. Selecione os melhores confrontos e monte uma aposta múltipla com odd mínima de 20.
    
    DIRETRIZES TÉCNICAS:
    1. Amostragem Recente (Últimos 10 Jogos): Fundamente nas médias e frequências.
    2. Retrospecto e Game State: Avalie necessidade de vitória.
    3. Filtro de Desfalques e Elenco: Evite times com rotação massiva.
    4. Exploração Ampla de Mercados: Busque a menor variância (Gols, Ambas Marcam, Escanteios, Cartões, Faltas).
    5. Micro-mercados e Coerência: Lógica combinada no mesmo jogo deve fazer sentido tático.
    6. Trava de Valor: Odd mínima de 1,45 por perna.
    7. Gestão: Stake padrão de 0,20u.
    
    Entregue APENAS a tabela final com os jogos, mercados, odds combinadas e justificativa enxuta.
    
    JOGOS DISPONÍVEIS HOJE:
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
# 4. FUNÇÃO: ENVIAR PARA O WHATSAPP (TWILIO)
# ==========================================
def enviar_whatsapp(mensagem):
    try:
        cliente = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        
        # A API da Twilio tem um limite de 1600 caracteres por mensagem.
        # Caso o texto da IA seja maior, enviamos as partes mais cruciais ou cortamos de forma segura.
        mensagem_formatada = mensagem[:1590] if len(mensagem) > 1600 else mensagem
        
        message = cliente.messages.create(
            from_=TWILIO_WHATSAPP_REMETENTE,
            body=mensagem_formatada,
            to=MEU_WHATSAPP
        )
        print(f"Mensagem enviada com sucesso para o WhatsApp. SID: {message.sid}")
    except Exception as e:
        print(f"Erro ao enviar para o WhatsApp: {e}")

# ==========================================
# 5. EXECUÇÃO PRINCIPAL
# ==========================================
if __name__ == "__main__":
    print("Buscando jogos da Betano...")
    grade_hoje = buscar_jogos_do_dia()
    
    print("Analisando dados com a IA e montando múltipla odd 20+...")
    bilhete_final = analisar_com_ia(grade_hoje)
    
    print("Enviando bilhete para o WhatsApp...")
    enviar_whatsapp(bilhete_final)
    print("Processo concluído com sucesso!")
