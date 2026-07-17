"""
ETL Pipeline - Relatório PDV Consumer (restaurante japonês (dados anonimizados))
====================================================
Autoria: pipeline gerado para substituir tratamento manual em Excel.
Entrada : arquivo .xlsx ou .csv exportado diretamente do Consumer.
Saída   : df_financeiro (Curva ABC) e df_operacional (tempos de permanência).

Execução rápida:
    python etl_consumer_pdv.py

O script detecta automaticamente o primeiro .xlsx encontrado na mesma pasta
que ele mesmo. Se houver mais de um arquivo, defina ARQUIVO_ENTRADA abaixo.
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path

# =============================================================================
# CONFIGURAÇÃO CENTRAL — edite só aqui
# =============================================================================

# Deixe vazio ("") para detecção automática do primeiro .xlsx na pasta do script.
# Se quiser fixar um arquivo específico, coloque só o nome (sem caminho):
#   ARQUIVO_ENTRADA = "meu_relatorio.xlsx"
ARQUIVO_ENTRADA = ""

SEPARADOR_CSV = ";"         # usado se a entrada for .csv
ENCODING_CSV  = "utf-8-sig" # BOM do Windows — padrão Consumer

# Nomes das colunas conforme exportação real do Consumer PDV
COL_NOME      = "Nome Prod"
COL_QTD       = "Qtd."              # Consumer exporta com ponto
COL_VLR_UNIT  = "Valor Un. Item"
COL_VLR_TOTAL = "Valor. Tot. Item"
COL_DATA_AB   = "Data Ab. Ped."
COL_DATA_FEC  = "Data Fec. Ped."
COL_TIPO_PED  = "Tipo Ped."
COL_MESA      = "Núm. Mesa/Com."

# =============================================================================
# UTILITÁRIO — localização do arquivo de entrada
# =============================================================================

# Pasta onde o script está salvo (independente de onde o terminal foi aberto)
PASTA_SCRIPT = Path(__file__).parent.resolve()


def resolver_arquivo(nome: str) -> Path:
    """
    Resolve o caminho absoluto do arquivo de entrada.
    Ordem de tentativas:
      1. Nome fixo definido em ARQUIVO_ENTRADA (se preenchido)
      2. Argumento de linha de comando: py etl_consumer_pdv.py meu_arquivo.xlsx
      3. Detecção automática do primeiro .xlsx na pasta do script
    """
    # Prioridade 1: nome fixo no código
    if nome:
        p = PASTA_SCRIPT / nome
        if p.exists():
            return p
        raise FileNotFoundError(
            f"Arquivo definido em ARQUIVO_ENTRADA não encontrado: {p}\n"
            f"Verifique se o arquivo está em: {PASTA_SCRIPT}"
        )

    # Prioridade 2: argumento de linha de comando
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if not p.is_absolute():
            p = PASTA_SCRIPT / p
        if p.exists():
            return p
        raise FileNotFoundError(f"Arquivo passado como argumento não encontrado: {p}")

    # Prioridade 3: detecção automática
    candidatos = sorted(PASTA_SCRIPT.glob("*.xlsx")) + sorted(PASTA_SCRIPT.glob("*.csv"))
    # Ignora saídas do pipeline e arquivos temporários do Excel (~$...)
    candidatos = [
        c for c in candidatos
        if not c.stem.startswith("saida_") and not c.name.startswith("~$")
    ]
    # Remove duplicatas por nome normalizado (mesmo arquivo, encoding diferente no nome)
    vistos, sem_dup = set(), []
    for c in candidatos:
        chave = c.name.encode("ascii", errors="ignore")
        if chave not in vistos:
            vistos.add(chave)
            sem_dup.append(c)
    candidatos = sem_dup
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum arquivo .xlsx ou .csv encontrado em:\n  {PASTA_SCRIPT}\n"
            "Coloque o relatório do Consumer na mesma pasta do script."
        )
    if len(candidatos) > 1:
        nomes = "\n  ".join(str(c.name) for c in candidatos)
        print(
            f"[AVISO] Mais de um arquivo encontrado. Usando o primeiro:\n"
            f"  {candidatos[0].name}\n"
            f"Outros ignorados:\n  {nomes}\n"
            f"Para escolher outro, defina ARQUIVO_ENTRADA no topo do script."
        )
    return candidatos[0]


# =============================================================================
# 1. EXTRACT — leitura do arquivo bruto
# =============================================================================

def extrair_dados(caminho: Path) -> pd.DataFrame:
    """
    Lê o relatório do Consumer independente do formato.
    Retorna um DataFrame bruto sem nenhuma transformação.
    """
    if caminho.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(caminho, dtype=str)  # dtype=str preserva zeros à esquerda
    else:
        df = pd.read_csv(caminho, sep=SEPARADOR_CSV, encoding=ENCODING_CSV, dtype=str)

    print(f"[EXTRACT] {len(df):,} linhas lidas de '{caminho.name}'.")
    return df


# =============================================================================
# 2. TRANSFORM — limpeza e enriquecimento
# =============================================================================

# ---- 2a. Regras de categorização -----------------------------------------

# Mapeamento em ordem de prioridade: (lista_de_substrings, categoria)
# A verificação é feita de cima para baixo — a primeira que bater vence.
REGRAS_CATEGORIA = [
    (["EMBAL"],                                                          "Embalagem"),
    (["TAXA"],                                                           "Taxa"),
    (["COCA", "GUARAN", "SKOL", "SAKE", "KOMBUCHA", "CORONA",
      "HEINEKEN", "STELLA", "AGUA", "ÁGUA", "H20", "SUCO",
      "FANTA", "ENERG", "CERVEJA", "BUDWEISER", "BECK", "ORIGINAL"],    "Bebidas"),
    (["MISSO"],                                                          "Misso Shiro"),
    (["GUIOZA"],                                                         "Guioza"),
    (["YAKISOBA"],                                                       "Yakisoba"),
    (["TEPPANYAKI"],                                                     "Teppanyaki"),
    (["FUTOMAKI"],                                                       "Futomaki"),
    (["URAMAKI"],                                                        "Uramaki"),
    (["NIGUIRI"],                                                        "Niguiri"),
    (["HOSSOMAKI"],                                                      "Hossomaki"),
    (["HOT"],                                                            "Hot"),
    (["CARPACCIO"],                                                      "Carpaccio"),
    (["SASHIMI"],                                                        "Sashimi"),
    (["JOY"],                                                            "Joy"),
    (["COMBO", "COMBINADO"],                                             "Combo"),
    (["TEMAKI"],                                                         "Temaki"),
    (["TATAKI"],                                                         "Tataki"),
    (["CEVICHE"],                                                        "Ceviche"),
    (["SUNOMONO"],                                                       "Sunomono"),
    (["POKE"],                                                           "Poke"),
    (["OISHII"],                                                         "Oishii"),
    (["GUNKAN"],                                                         "Gunkan"),
    (["HARUMAKI"],                                                       "Harumaki"),
]


def classificar_categoria(nome: str) -> str:
    """
    Recebe o nome do produto e retorna a categoria.
    Percorre as regras na ordem de prioridade definida acima.
    """
    nome_upper = str(nome).upper()
    for substrings, categoria in REGRAS_CATEGORIA:
        if any(sub in nome_upper for sub in substrings):
            return categoria
    return "Outros"


# ---- 2b. Verificação de integridade de faturamento -----------------------

def _parse_monetario(serie: pd.Series) -> pd.Series:
    """
    Converte colunas numéricas do Consumer para float.

    O Consumer pode gravar valores de duas formas dependendo do formato de exportação:

    Formato A — texto com padrão brasileiro: "1.234,56"
      O ponto é separador de milhar e a vírgula é decimal.
      Nesse caso: remove o ponto, troca vírgula por ponto â†’ 1234.56

    Formato B — número real do Excel lido como string: "1234.56" ou "128.9"
      O pandas lê o float do Excel e converte para string com ponto decimal.
      Nesse caso: o valor já está correto e NÃO deve ter o ponto removido.
      Se removermos o ponto aqui, "128.9" vira "1289", multiplicando por 10.

    Regra de distinção:
      - Se a string contém vírgula â†’ Formato A (brasileiro em texto)
      - Se a string contém ponto mas não vírgula â†’ Formato B (já é decimal)
      - Se não contém nenhum â†’ número inteiro, converte direto
    """
    def converter(valor: str) -> float:
        v = str(valor).strip()
        if "," in v:
            # Formato A: "1.234,56" â†’ remove ponto de milhar, troca vírgula
            v = v.replace(".", "").replace(",", ".")
        # Formato B: "128.9" — não faz nada, já está correto
        try:
            return float(v)
        except ValueError:
            return float("nan")

    return serie.apply(converter)


def verificar_integridade_faturamento(df: pd.DataFrame) -> pd.DataFrame:
    """
    Recalcula Valor Total como Qtd × Valor Unitário.
    Se houver divergência, sobrescreve com o valor correto e emite aviso.
    """
    qtd       = pd.to_numeric(df[COL_QTD].astype(str).str.replace(",", "."), errors="coerce")
    vlr_unit  = _parse_monetario(df[COL_VLR_UNIT])
    vlr_total = _parse_monetario(df[COL_VLR_TOTAL])

    recalculado  = (qtd * vlr_unit).round(2)
    divergencias = ~np.isclose(recalculado, vlr_total, rtol=0.01, equal_nan=True)
    n_div        = divergencias.sum()

    if n_div > 0:
        print(f"[INTEGRIDADE] {n_div} linha(s) com divergência entre Qtd×Unit e Total. "
              "Valores corrigidos automaticamente.")
        print(df.loc[divergencias, [COL_NOME, COL_QTD, COL_VLR_UNIT, COL_VLR_TOTAL]].head())

    df[COL_VLR_TOTAL]   = recalculado
    df["_qtd_num"]      = qtd
    df["_vlr_unit_num"] = vlr_unit
    return df


# ---- 2c. Pipeline de transformação principal -----------------------------

def transformar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica todas as regras de limpeza, integridade e categorização.
    """
    df = df.copy()

    # Regra 1: remove produtos excluídos e taxas operacionais (Taxa de Entrega, Embalagem)
    mascara_excluido = df[COL_NOME].str.contains("exclu", case=False, na=False)
    termos_filtro = ["taxa", "embalagem", "serviço"]
    mascara_taxa = df[COL_NOME].str.contains("|".join(termos_filtro), case=False, na=False)
    
    n_removidos = mascara_excluido.sum()
    n_taxas = mascara_taxa.sum()
    
    df = df[~(mascara_excluido | mascara_taxa)].reset_index(drop=True)
    print(f"[TRANSFORM] {n_removidos} linha(s) com 'Excluído' removidas.")
    print(f"[TRANSFORM] {n_taxas} linha(s) de taxas operacionais (Entrega/Embalagem) removidas.")

    # Regra 2: padronização do nome
    df[COL_NOME] = (
        df[COL_NOME]
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
        .str.title()
    )

    # Regra 3: integridade de faturamento
    df = verificar_integridade_faturamento(df)

    # Categorização
    df["Categoria"] = df[COL_NOME].apply(classificar_categoria)

    # Conversão de datas
    for col in [COL_DATA_AB, COL_DATA_FEC]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")

    print(f"[TRANSFORM] Transformação concluída. {len(df):,} linhas válidas.")
    return df


# =============================================================================
# 3. LOAD — geração dos DataFrames de saída
# =============================================================================

def gerar_df_financeiro(df: pd.DataFrame) -> pd.DataFrame:
    """
    DF 1 — Visão Financeira (Curva ABC).
    """
    df_fin = (
        df
        .groupby([COL_NOME, "Categoria"], sort=False)
        .agg(
            Quantidade_Total  = ("_qtd_num",    "sum"),
            Faturamento_Total = (COL_VLR_TOTAL, "sum"),
        )
        .reset_index()
        .sort_values("Faturamento_Total", ascending=False)
        .reset_index(drop=True)
    )

    total = df_fin["Faturamento_Total"].sum()
    df_fin["Part_%"]      = (df_fin["Faturamento_Total"] / total * 100).round(2)
    df_fin["Part_Acum_%"] = (df_fin["Faturamento_Total"].cumsum() / total * 100).round(2)
    df_fin["Classe_ABC"]  = pd.cut(
        df_fin["Part_Acum_%"],
        bins=[0, 80, 95, 100.05],
        labels=["A", "B", "C"],
        include_lowest=True
    )

    print(f"[LOAD] df_financeiro: {len(df_fin)} produtos únicos.")
    return df_fin


def gerar_df_operacional(df: pd.DataFrame) -> pd.DataFrame:
    """
    DF 2 — Visão Operacional com tempo de permanência em minutos.
    """
    colunas = [c for c in [COL_DATA_AB, COL_DATA_FEC, COL_TIPO_PED, COL_MESA] if c in df.columns]
    df_op   = df[colunas + ["Categoria", COL_NOME, "_qtd_num"]].copy()
    df_op   = df_op.rename(columns={"_qtd_num": "Qtd_Num"})

    if COL_DATA_AB in df_op.columns and COL_DATA_FEC in df_op.columns:
        df_op["Permanencia_Min"] = (
            (df_op[COL_DATA_FEC] - df_op[COL_DATA_AB])
            .dt.total_seconds()
            .div(60)
            .round(1)
        )
        n_inv = (df_op["Permanencia_Min"] < 0).sum()
        if n_inv > 0:
            print(f"[OPERACIONAL] {n_inv} pedido(s) com data de fechamento anterior à abertura.")

    print(f"[LOAD] df_operacional: {len(df_op):,} linhas.")
    return df_op


# =============================================================================
# 4. EXECUTOR PRINCIPAL
# =============================================================================

def executar_pipeline():
    print("=" * 60)
    print("  Pipeline ETL — Consumer PDV")
    print("=" * 60)

    caminho        = resolver_arquivo(ARQUIVO_ENTRADA)
    print(f"[INFO] Arquivo: {caminho}")

    df_bruto       = extrair_dados(caminho)
    df_tratado     = transformar(df_bruto)
    df_financeiro  = gerar_df_financeiro(df_tratado)
    df_operacional = gerar_df_operacional(df_tratado)

    # Exporta os resultados na mesma pasta do script
    saida_fin = PASTA_SCRIPT / "saida_financeiro.xlsx"
    saida_op  = PASTA_SCRIPT / "saida_operacional.xlsx"
    df_financeiro.to_excel(saida_fin,  index=False)
    df_operacional.to_excel(saida_op, index=False)
    print(f"[EXPORT] saida_financeiro.xlsx  salvo em {PASTA_SCRIPT}")
    print(f"[EXPORT] saida_operacional.xlsx salvo em {PASTA_SCRIPT}")

    print("=" * 60)
    print("  Pipeline concluído com sucesso.")
    print("=" * 60)
    return df_financeiro, df_operacional


# =============================================================================
# 5. PONTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    df_fin, df_op = executar_pipeline()

    print("\n--- Visão Financeira (top 10) ---")
    print(df_fin.head(10).to_string(index=False))

    print("\n--- Visão Operacional (primeiras 5 linhas) ---")
    print(df_op.head(5).to_string(index=False))

