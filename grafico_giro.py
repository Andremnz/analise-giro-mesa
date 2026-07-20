"""
Gera um grafico ILUSTRATIVO da analise de giro de mesa, com dados sinteticos.
A conclusao real do projeto foi que pedidos com categorias "quentes"
(Yakisoba, Teppanyaki) NAO tiveram permanencia significativamente maior.
Este script reproduz esse padrao apenas para visualizacao.
"""
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

rng = np.random.default_rng(42)

# Duas amostras da mesma distribuicao de base, porque a permanencia nao
# depende de o pedido conter categoria quente. E o cenario "sem efeito real".
com_quente = rng.normal(72, 18, 300).clip(15, 160)
sem_quente = rng.normal(70, 19, 700).clip(15, 160)

t_stat, p = stats.ttest_ind(com_quente, sem_quente, equal_var=False)

fig, ax = plt.subplots(figsize=(8, 5))
ax.boxplot([com_quente, sem_quente],
           tick_labels=["Pedidos com Pratos Quentes", "Pedidos com Pratos Frios"],
           showmeans=True, widths=0.5)
ax.set_ylabel("Permanencia na mesa (min)")
ax.set_title("Permanencia por tipo de pedido (dados sinteticos)\n"
             f"Teste t de Welch p = {p:.3f}, sem diferenca significativa (p > 0,05)")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
fig.savefig("imagens/giro_por_categoria.png", dpi=110)
print(f"Grafico salvo em imagens/giro_por_categoria.png | p-valor = {p:.4f}")
