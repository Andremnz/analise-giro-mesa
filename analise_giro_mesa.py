"""
Análise de Giro de Mesa — Correlação Categorias × Tempo de Permanência
=======================================================================
Dependência : etl_consumer_pdv.py (deve estar na mesma pasta)
Saída       : saida_analise_giro_mesa.xlsx com 5 abas

Pergunta central
----------------
Pedidos com itens das categorias "Yakisoba" e "Teppanyaki" têm tempo de
permanência na mesa matematicamente maior do que os demais?

Escopo da análise
-----------------
Apenas pedidos do tipo Mesa/Comanda são considerados. Pedidos de Balcão
(delivery) são excluídos porque a "permanência" nesses casos representa
tempo de sistema aberto, não tempo de ocupação de mesa — o que
contaminaria qualquer análise operacional de giro.

Taxa e Embalagem são excluídas das análises de categoria porque são
categorias administrativas (cobranças e embalagens de delivery), não
categorias de produto que influenciam o comportamento do cliente na mesa.
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from scipy import stats

# =============================================================================
# CONFIGURAÇÃO — edite aqui para ajustar o escopo da análise
# =============================================================================

LIMIAR_LENTO_MIN = 75
CATEGORIAS_QUENTES   = ["Yakisoba", "Teppanyaki", "Guioza", "Hot", "Harumaki", "Misso Shiro"]

# Pedidos mantidos na análise (filtra pela coluna Tipo Ped.)
# Qualquer valor que contenha essa string (case insensitive) é mantido.
FILTRO_TIPO_PEDIDO   = "mesa"

# Categorias excluídas das análises comparativas (não são categorias de produto)
CATEGORIAS_EXCLUIR   = ["Taxa", "Embalagem"]

COL_COD_PED = "Cod. Ped."

# =============================================================================
# IMPORTA O MÓDULO ETL DA MESMA PASTA
# =============================================================================

PASTA = Path(__file__).parent.resolve()
sys.path.insert(0, str(PASTA))

try:
    import etl_consumer_pdv as etl
except ModuleNotFoundError:
    raise SystemExit(
        "etl_consumer_pdv.py não encontrado.\n"
        f"Certifique-se de que ele está em: {PASTA}"
    )

# =============================================================================
# 1. CARGA E FILTRO DE ESCOPO
# =============================================================================

def carregar_dados_tratados() -> pd.DataFrame:
    """
    Extrai e transforma via ETL, depois aplica o filtro de escopo.

    O filtro de Tipo Pedido acontece aqui, antes de qualquer cálculo,
    porque toda a análise posterior só faz sentido para pedidos de mesa.
    Manter os dados de Balcão no DataFrame aumentaria permanências médias
    artificialmente e distorceria a correlação.
    """
    print("[CARGA] Executando ETL para obter dados tratados...")
    caminho    = etl.resolver_arquivo(etl.ARQUIVO_ENTRADA)
    df_bruto   = etl.extrair_dados(caminho)
    df_tratado = etl.transformar(df_bruto)

    # Filtro: mantém apenas Mesa/Comanda
    mascara_mesa = df_tratado[etl.COL_TIPO_PED].str.contains(
        FILTRO_TIPO_PEDIDO, case=False, na=False
    )
    n_total    = len(df_tratado)
    df_mesa    = df_tratado[mascara_mesa].reset_index(drop=True)
    n_excluido = n_total - len(df_mesa)

    print(f"[FILTRO] {n_excluido:,} linhas de Balcão/Delivery removidas do escopo.")
    print(f"[CARGA]  {len(df_mesa):,} linhas de Mesa disponíveis para análise.\n")
    return df_mesa


# =============================================================================
# 2. CONSTRUÇÃO DO NÍVEL DE PEDIDO
# =============================================================================

def construir_nivel_pedido(df: pd.DataFrame) -> pd.DataFrame:
    """
    Colapsa o DataFrame de itens (uma linha por item) para uma linha por pedido.

    Por que colapsar? Porque as perguntas de negócio vivem em níveis diferentes.
    "Quanto esse pedido faturou?" é uma pergunta de pedido, não de item.
    "Quanto tempo essa mesa ficou ocupada?" também. Para respondê-las precisamos
    de um DataFrame onde cada linha = um pedido único.

    O groupby agrupa todas as linhas que compartilham o mesmo Cod. Ped. e o
    .agg() decide o que fazer com cada coluna dentro desse grupo:
    - Permanência: "first" porque é idêntica em todas as linhas do mesmo pedido
    - Faturamento: "sum" porque queremos o total do pedido
    - Categorias: set() para saber quais categorias distintas apareceram
    """
    df = df.copy()
    col_perm = "Permanencia_Min"

    if col_perm not in df.columns:
        if etl.COL_DATA_AB in df.columns and etl.COL_DATA_FEC in df.columns:
            df[col_perm] = (
                (df[etl.COL_DATA_FEC] - df[etl.COL_DATA_AB])
                .dt.total_seconds()
                .div(60)
                .round(1)
            )
        else:
            raise ValueError("Colunas de data não encontradas.")

    agg = df.groupby(COL_COD_PED).agg(
        Permanencia_Min = (col_perm,          "first"),
        Faturamento_Ped = (etl.COL_VLR_TOTAL, "sum"),
        Qtd_Itens       = ("_qtd_num",         "sum"),
        Tipo_Pedido     = (etl.COL_TIPO_PED,   "first"),
        Mesa            = (etl.COL_MESA,       "first"),
        Categorias      = ("Categoria",        lambda x: sorted(set(x))),
        N_Categorias    = ("Categoria",        "nunique"),
    ).reset_index()

    agg["tem_item_quente"] = agg["Categorias"].apply(
        lambda cats: int(any(c in cats for c in CATEGORIAS_QUENTES))
    )
    agg["pedido_lento"] = (agg["Permanencia_Min"] > LIMIAR_LENTO_MIN).astype(int)

    n_invalidos = (agg["Permanencia_Min"] <= 0).sum()
    if n_invalidos:
        print(f"[AVISO] {n_invalidos} pedido(s) com permanência inválida removidos.")
    agg = agg[agg["Permanencia_Min"] > 0].reset_index(drop=True)

    print(f"[PEDIDOS] {len(agg):,} pedidos de mesa | "
          f"Lentos (>{LIMIAR_LENTO_MIN} min): {agg['pedido_lento'].sum():,} | "
          f"Com item quente: {agg['tem_item_quente'].sum():,}\n")
    return agg


# =============================================================================
# 3. ANÁLISE 1 — Correlação estatística (item quente × permanência)
# =============================================================================

def testar_correlacao(df_pedidos: pd.DataFrame) -> dict:
    """
    Testa se ter Yakisoba/Teppanyaki é matematicamente associado a maior permanência.

    Dois testes complementares:
    - Correlação ponto-bisserial (r): força e direção da associação.
      r próximo de 0 = sem associação. r positivo = variável binária=1
      tende a aparecer com valores maiores da contínua.
      IMPORTANTE: r não mede causalidade, apenas co-ocorrência.
    - Teste t de Welch: compara as médias dos dois grupos e calcula a
      probabilidade de a diferença ser aleatória (p-valor).
      p < 0.05 = diferença real com 95% de confiança.
    """
    com_quente = df_pedidos[df_pedidos["tem_item_quente"] == 1]["Permanencia_Min"]
    sem_quente = df_pedidos[df_pedidos["tem_item_quente"] == 0]["Permanencia_Min"]

    r, p_biserial = stats.pointbiserialr(
        df_pedidos["tem_item_quente"],
        df_pedidos["Permanencia_Min"]
    )
    t_stat, p_ttest = stats.ttest_ind(com_quente, sem_quente, equal_var=False)

    resultado = {
        "media_com_quente_min": round(com_quente.mean(), 1),
        "media_sem_quente_min": round(sem_quente.mean(), 1),
        "diferenca_media_min":  round(com_quente.mean() - sem_quente.mean(), 1),
        "n_com_quente":         len(com_quente),
        "n_sem_quente":         len(sem_quente),
        "correlacao_r":         round(r, 4),
        "p_valor_biserial":     round(p_biserial, 6),
        "t_estatistica":        round(t_stat, 4),
        "p_valor_ttest":        round(p_ttest, 6),
        "significativo_95":     p_ttest < 0.05,
    }

    intensidade = "fraca" if abs(r) < 0.1 else "moderada" if abs(r) < 0.3 else "forte"
    direcao     = "positiva" if r > 0 else "negativa"
    sig_texto   = (
        "estatisticamente significativa (p < 0.05)"
        if resultado["significativo_95"]
        else "NÃO estatisticamente significativa (p >= 0.05)"
    )
    resultado["interpretacao"] = (
        f"Correlação {intensidade} e {direcao} (r={r:.4f}). "
        f"COM item quente: média {resultado['media_com_quente_min']} min. "
        f"SEM item quente: média {resultado['media_sem_quente_min']} min. "
        f"Diferença de {resultado['diferenca_media_min']} min — {sig_texto}."
    )
    return resultado


# =============================================================================
# 4. ANÁLISE 2 — Permanência média por categoria (excluindo adm.)
# =============================================================================

def permanencia_media_por_categoria(df: pd.DataFrame, df_pedidos: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada categoria de produto, calcula a permanência média dos pedidos
    que contêm ao menos um item dessa categoria.

    Taxa e Embalagem são excluídas porque não são categorias de produto
    consumido na mesa — incluí-las distorceria o ranqueamento.

    Diferença entre média e mediana aqui:
    - Média é puxada por valores extremos (um pedido de 400 min eleva a média).
    - Mediana é o valor do meio — 50% dos pedidos ficam abaixo, 50% acima.
    Quando média >> mediana, há outliers inflando o número. Fique de olho nisso.
    """
    lookup = df_pedidos[[COL_COD_PED, "Permanencia_Min", "pedido_lento"]].rename(
        columns={"Permanencia_Min": "_perm_ped", "pedido_lento": "_lento_ped"}
    )
    df_enriquecido = (
        df[~df["Categoria"].isin(CATEGORIAS_EXCLUIR)]  # exclui categorias adm.
        .merge(lookup, on=COL_COD_PED, how="left")
        .drop_duplicates(subset=[COL_COD_PED, "Categoria"])
    )

    tabela = (
        df_enriquecido.groupby("Categoria")
        .agg(
            N_Pedidos          = (COL_COD_PED,  "nunique"),
            Permanencia_Media  = ("_perm_ped",  "mean"),
            Permanencia_Median = ("_perm_ped",  "median"),
            Perc_Lentos        = ("_lento_ped", "mean"),
        )
        .reset_index()
    )
    tabela["Permanencia_Media"]  = tabela["Permanencia_Media"].round(1)
    tabela["Permanencia_Median"] = tabela["Permanencia_Median"].round(1)
    tabela["Perc_Lentos"]        = (tabela["Perc_Lentos"] * 100).round(1)
    return tabela.sort_values("Permanencia_Media", ascending=False).reset_index(drop=True)


# =============================================================================
# 5. ANÁLISE 3 — Categorias em mesas lentas vs rápidas
# =============================================================================

def analisar_categorias_em_pedidos_lentos(df: pd.DataFrame, df_pedidos: pd.DataFrame) -> pd.DataFrame:
    """
    Compara a presença de cada categoria entre pedidos lentos e rápidos.

    A métrica Dif_pp (diferença em pontos percentuais) é a mais útil aqui.
    Um Dif_pp alto significa que essa categoria aparece desproporcionalmente
    mais em pedidos lentos do que em rápidos — sinal de correlação operacional.
    """
    df_filtrado = df[~df["Categoria"].isin(CATEGORIAS_EXCLUIR)]

    total_lentos  = df_pedidos["pedido_lento"].sum()
    total_rapidos = (df_pedidos["pedido_lento"] == 0).sum()

    df_enriquecido = df_filtrado.merge(
        df_pedidos[[COL_COD_PED, "pedido_lento"]], on=COL_COD_PED, how="left"
    )

    def freq_grupo(flag, total):
        subset = df_enriquecido[df_enriquecido["pedido_lento"] == flag]
        c = (
            subset.groupby("Categoria")[COL_COD_PED]
            .nunique().reset_index()
            .rename(columns={COL_COD_PED: "N"})
        )
        c["Perc"] = (c["N"] / total * 100).round(1)
        return c

    lentos  = freq_grupo(1, total_lentos).rename(columns={"N": "N_Lentos",  "Perc": "Perc_Lentos"})
    rapidos = freq_grupo(0, total_rapidos).rename(columns={"N": "N_Rapidos", "Perc": "Perc_Rapidos"})

    comp = lentos.merge(rapidos, on="Categoria", how="outer").fillna(0)
    comp["Dif_pp"] = (comp["Perc_Lentos"] - comp["Perc_Rapidos"]).round(1)
    return comp.sort_values("Perc_Lentos", ascending=False).reset_index(drop=True)


# =============================================================================
# 6. ANÁLISE 4 — Desempenho por número de mesa
# =============================================================================

def analisar_desempenho_por_mesa(df_pedidos: pd.DataFrame) -> pd.DataFrame:
    """
    Ranqueia cada número de mesa por faturamento total, volume de pedidos
    e ticket médio por pedido.

    Métricas incluídas:
    - N_Pedidos: volume de atendimentos nessa mesa
    - Faturamento_Total: receita acumulada no período
    - Ticket_Medio: faturamento médio por pedido (Faturamento_Total / N_Pedidos)
    - Permanencia_Media: tempo médio que essa mesa fica ocupada
    - Perc_Lentos: % dos pedidos dessa mesa que ultrapassaram o limiar
    - Receita_Por_Minuto: eficiência da mesa (quanto ela gera por minuto ocupada)

    Receita_Por_Minuto é a métrica de giro mais objetiva: uma mesa que fatura
    R$200 em 40 min é operacionalmente superior a uma que fatura R$250 em 90 min.
    """
    # Exclui linhas sem número de mesa identificado
    df_com_mesa = df_pedidos[df_pedidos["Mesa"].str.strip().ne("") & df_pedidos["Mesa"].notna()]

    tabela = (
        df_com_mesa.groupby("Mesa")
        .agg(
            N_Pedidos         = (COL_COD_PED,       "nunique"),
            Faturamento_Total = ("Faturamento_Ped",  "sum"),
            Permanencia_Media = ("Permanencia_Min",  "mean"),
            Perc_Lentos       = ("pedido_lento",     "mean"),
        )
        .reset_index()
    )

    tabela["Ticket_Medio"]       = (tabela["Faturamento_Total"] / tabela["N_Pedidos"]).round(2)
    tabela["Permanencia_Media"]  = tabela["Permanencia_Media"].round(1)
    tabela["Perc_Lentos"]        = (tabela["Perc_Lentos"] * 100).round(1)
    tabela["Receita_Por_Minuto"] = (tabela["Faturamento_Total"] / (tabela["Permanencia_Media"] * tabela["N_Pedidos"])).round(2)

    return tabela.sort_values("Faturamento_Total", ascending=False).reset_index(drop=True)


# =============================================================================
# 7. ANÁLISE 5 — Detalhe dos pedidos lentos
# =============================================================================

def detalhar_pedidos_lentos(df_pedidos: pd.DataFrame) -> pd.DataFrame:
    lentos = df_pedidos[df_pedidos["pedido_lento"] == 1].copy()
    lentos["Categorias"] = lentos["Categorias"].apply(
        lambda x: ", ".join(c for c in x if c not in CATEGORIAS_EXCLUIR)
    )
    return (
        lentos[[COL_COD_PED, "Mesa", "Tipo_Pedido", "Permanencia_Min",
                "Faturamento_Ped", "Qtd_Itens", "tem_item_quente", "Categorias"]]
        .sort_values("Permanencia_Min", ascending=False)
        .reset_index(drop=True)
    )


# =============================================================================
# 8. EXPORTAÇÃO
# =============================================================================

def exportar_excel(
    stats_correlacao: dict,
    perm_categoria:   pd.DataFrame,
    comparativo:      pd.DataFrame,
    desempenho_mesa:  pd.DataFrame,
    pedidos_lentos:   pd.DataFrame,
) -> Path:
    caminho_saida = PASTA / "saida_analise_giro_mesa.xlsx"

    df_stats = pd.DataFrame(
        list(stats_correlacao.items()), columns=["Métrica", "Valor"]
    )

    with pd.ExcelWriter(caminho_saida, engine="openpyxl") as writer:
        df_stats.to_excel(        writer, sheet_name="Correlação Estatística",      index=False)
        perm_categoria.to_excel(  writer, sheet_name="Permanência por Categoria",   index=False)
        comparativo.to_excel(     writer, sheet_name="Categorias Lentos vs Rápidos",index=False)
        desempenho_mesa.to_excel( writer, sheet_name="Desempenho por Mesa",         index=False)
        pedidos_lentos.to_excel(  writer, sheet_name="Detalhe Pedidos Lentos",      index=False)

    print(f"[EXPORT] saida_analise_giro_mesa.xlsx salvo em {PASTA}")
    return caminho_saida


# =============================================================================
# 9. EXECUTOR PRINCIPAL
# =============================================================================

def executar_analise():
    print("=" * 60)
    print("  Análise de Giro de Mesa — Consumer PDV")
    print(f"  Escopo: apenas pedidos contendo '{FILTRO_TIPO_PEDIDO}'")
    print(f"  Limiar lento: > {LIMIAR_LENTO_MIN} min")
    print(f"  Categorias adm. excluídas: {CATEGORIAS_EXCLUIR}")
    print(f"  Categorias quentes: {CATEGORIAS_QUENTES}")
    print("=" * 60 + "\n")

    df          = carregar_dados_tratados()
    df_pedidos  = construir_nivel_pedido(df)

    stats_corr      = testar_correlacao(df_pedidos)
    perm_categoria  = permanencia_media_por_categoria(df, df_pedidos)
    comparativo     = analisar_categorias_em_pedidos_lentos(df, df_pedidos)
    desempenho_mesa = analisar_desempenho_por_mesa(df_pedidos)
    pedidos_lentos  = detalhar_pedidos_lentos(df_pedidos)

    print("=" * 60)
    print("  RESULTADO DA CORRELAÇÃO (somente mesas)")
    print("=" * 60)
    print(stats_corr["interpretacao"])
    print()
    print("  Permanência média por categoria (top 10):")
    print(perm_categoria.head(10).to_string(index=False))
    print()
    print("  Desempenho por mesa (top 10 em faturamento):")
    print(desempenho_mesa.head(10).to_string(index=False))
    print()

    exportar_excel(stats_corr, perm_categoria, comparativo, desempenho_mesa, pedidos_lentos)

    print("=" * 60)
    print("  Análise concluída.")
    print("=" * 60)

    return df_pedidos, stats_corr, perm_categoria, comparativo, desempenho_mesa


# =============================================================================
# PONTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    executar_analise()

