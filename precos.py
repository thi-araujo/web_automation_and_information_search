"""Leitura da planilha de produtos, cálculo dos preços em reais e exportação.

A planilha (.xlsx ou .csv) precisa das colunas:

    Produto | Preço Original | Moeda | Margem

- Moeda: Dólar, Euro, Libra ou Real (também aceita USD, EUR, GBP, BRL).
- Margem: multiplicador sobre o custo (1.5 = vende por 50% a mais que o
  custo) ou percentual ("50%").

O cálculo é o mesmo do projeto original:
    Preço de Compra = Preço Original x Cotação
    Preço de Venda  = Preço de Compra x Margem
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

COLUNAS = {
    "produto": "Produto",
    "precooriginal": "Preço Original",
    "moeda": "Moeda",
    "margem": "Margem",
}

APELIDOS_MOEDA = {
    "USD": {"usd", "dolar", "dolares", "us$", "dolar americano"},
    "EUR": {"eur", "euro", "euros", "€"},
    "GBP": {"gbp", "libra", "libras", "£", "libra esterlina"},
    "BRL": {"brl", "real", "reais", "r$"},
}


class ErroPlanilha(Exception):
    """A planilha não tem o formato esperado."""


@dataclass
class Produto:
    nome: str
    preco_original: float
    moeda: str   # código ISO
    margem: float
    linha: int   # linha na planilha, para mensagens de erro


@dataclass
class PrecoCalculado:
    produto: Produto
    cotacao: float
    preco_compra: float
    preco_venda: float


def _simplificar(texto: str) -> str:
    """Minúsculas, sem acentos e sem espaços: "Preço Original" -> "precooriginal"."""
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", sem_acento.lower())


def normalizar_moeda(texto: str) -> str:
    chave = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().strip().lower()
    original = str(texto).strip().lower()
    for codigo, apelidos in APELIDOS_MOEDA.items():
        if chave in apelidos or original in apelidos:
            return codigo
    raise ValueError(f"moeda desconhecida: {texto}")


def numero(valor) -> float:
    """Converte 1234.5, "1.234,50", "R$ 1.234,50" ou "1234.50" em float."""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    texto = re.sub(r"[^\d,.\-]", "", str(valor))
    if not texto:
        raise ValueError(f"número inválido: {valor!r}")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")  # formato brasileiro
    return float(texto)


def margem(valor) -> float:
    if isinstance(valor, str) and "%" in valor:
        return 1 + numero(valor) / 100
    resultado = numero(valor)
    if resultado <= 0:
        raise ValueError(f"margem precisa ser maior que zero: {valor!r}")
    return resultado


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------

def _ler_linhas_xlsx(caminho: Path) -> list[list]:
    from openpyxl import load_workbook

    livro = load_workbook(caminho, read_only=True, data_only=True)
    try:
        aba = livro.active
        return [list(linha) for linha in aba.iter_rows(values_only=True)]
    finally:
        livro.close()


def _ler_linhas_csv(caminho: Path) -> list[list]:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = caminho.read_text(encoding=codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ErroPlanilha("não foi possível ler o arquivo CSV (codificação desconhecida)")
    try:
        dialeto = csv.Sniffer().sniff(texto.splitlines()[0] if texto else "", delimiters=";,\t")
    except csv.Error:
        dialeto = csv.excel
    return [linha for linha in csv.reader(texto.splitlines(), dialeto)]


def ler_planilha(caminho: str | Path) -> list[Produto]:
    caminho = Path(caminho)
    sufixo = caminho.suffix.lower()
    if sufixo in (".xlsx", ".xlsm"):
        linhas = _ler_linhas_xlsx(caminho)
    elif sufixo == ".csv":
        linhas = _ler_linhas_csv(caminho)
    else:
        raise ErroPlanilha(f"formato não suportado: {sufixo or 'sem extensão'} (use .xlsx ou .csv)")

    linhas = [l for l in linhas if any(c not in (None, "") for c in l)]
    if not linhas:
        raise ErroPlanilha("a planilha está vazia")

    cabecalho = [_simplificar(c or "") for c in linhas[0]]
    indices = {}
    for chave, nome in COLUNAS.items():
        if chave not in cabecalho:
            raise ErroPlanilha(f"coluna \"{nome}\" não encontrada. Colunas necessárias: "
                               + ", ".join(COLUNAS.values()))
        indices[chave] = cabecalho.index(chave)

    produtos = []
    erros = []
    for numero_linha, linha in enumerate(linhas[1:], start=2):
        celula = lambda chave: linha[indices[chave]] if indices[chave] < len(linha) else None  # noqa: E731
        nome = str(celula("produto") or "").strip()
        if not nome:
            continue
        try:
            produtos.append(Produto(
                nome=nome,
                preco_original=numero(celula("precooriginal")),
                moeda=normalizar_moeda(celula("moeda") or ""),
                margem=margem(celula("margem")),
                linha=numero_linha,
            ))
        except ValueError as erro:
            erros.append(f"linha {numero_linha} ({nome}): {erro}")
    if erros:
        raise ErroPlanilha("dados inválidos:\n" + "\n".join(erros[:10]))
    if not produtos:
        raise ErroPlanilha("nenhum produto encontrado")
    return produtos


# --------------------------------------------------------------------------
# Cálculo e exportação
# --------------------------------------------------------------------------

def moedas_usadas(produtos: list[Produto]) -> list[str]:
    return sorted({p.moeda for p in produtos if p.moeda != "BRL"})


def calcular(produtos: list[Produto], cotacoes: dict[str, float]) -> list[PrecoCalculado]:
    resultado = []
    for produto in produtos:
        cotacao = 1.0 if produto.moeda == "BRL" else cotacoes.get(produto.moeda)
        if cotacao is None:
            raise ValueError(f"falta a cotação de {produto.moeda}")
        compra = produto.preco_original * cotacao
        resultado.append(PrecoCalculado(produto, cotacao, compra, compra * produto.margem))
    return resultado


def formatar_reais(valor: float) -> str:
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def exportar_xlsx(precos: list[PrecoCalculado], caminho: str | Path,
                  info_cotacoes: list[tuple[str, float, str]]) -> None:
    """Salva a tabela calculada e, numa segunda aba, as cotações usadas."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    livro = Workbook()
    aba = livro.active
    aba.title = "Preços"
    cabecalho = ["Produto", "Preço Original", "Moeda", "Cotação", "Preço de Compra", "Margem",
                 "Preço de Venda"]
    aba.append(cabecalho)
    for p in precos:
        aba.append([p.produto.nome, p.produto.preco_original, p.produto.moeda, p.cotacao,
                    p.preco_compra, p.produto.margem, p.preco_venda])

    reais = '"R$" #,##0.00'
    formatos = {2: "#,##0.00", 4: "0.0000", 5: reais, 6: "0.00", 7: reais}
    for coluna, formato in formatos.items():
        for (celula,) in aba.iter_rows(min_row=2, min_col=coluna, max_col=coluna):
            celula.number_format = formato
    destaque = PatternFill("solid", fgColor="1E293B")
    for celula in aba[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = destaque
        celula.alignment = Alignment(horizontal="center")
    larguras = [max(len(str(c.value or "")) for c in coluna) for coluna in aba.columns]
    for i, largura in enumerate(larguras, start=1):
        aba.column_dimensions[get_column_letter(i)].width = min(max(largura + 4, 12), 50)
    aba.freeze_panes = "A2"

    aba_cot = livro.create_sheet("Cotações")
    aba_cot.append(["Moeda", "Cotação (R$)", "Fonte"])
    for linha in info_cotacoes:
        aba_cot.append(list(linha))
    for celula in aba_cot[1]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = destaque
    for (celula,) in aba_cot.iter_rows(min_row=2, min_col=2, max_col=2):
        celula.number_format = "0.0000"
    for letra, largura in (("A", 10), ("B", 14), ("C", 45)):
        aba_cot.column_dimensions[letra].width = largura

    livro.save(caminho)
