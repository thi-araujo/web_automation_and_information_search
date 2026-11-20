"""Busca a cotação de moedas estrangeiras em reais.

Fonte principal: AwesomeAPI (https://docs.awesomeapi.com.br), gratuita e sem
cadastro. Se ela falhar, usa a PTAX do Banco Central (dados abertos), que só
tem cotação em dias úteis, por isso a busca olha os últimos 7 dias.

A função que abre a URL é recebida por parâmetro, o que permite testar o
módulo sem internet.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

TEMPO_LIMITE = 10  # segundos
CABECALHO = {"User-Agent": "atualizador-de-precos/1.0 (Python urllib)"}

MOEDAS = {
    "USD": "Dólar",
    "EUR": "Euro",
    "GBP": "Libra",
}

AbrirUrl = Callable[[str], str]


class ErroCotacao(Exception):
    """Nenhuma fonte conseguiu informar a cotação."""


@dataclass(frozen=True)
class Cotacao:
    moeda: str        # código ISO, ex.: "USD"
    valor: float      # quanto vale 1 unidade da moeda em reais
    data_hora: str    # quando a fonte registrou a cotação
    fonte: str


def abrir_url(url: str) -> str:
    requisicao = urllib.request.Request(url, headers=CABECALHO)
    with urllib.request.urlopen(requisicao, timeout=TEMPO_LIMITE) as resposta:
        return resposta.read().decode("utf-8")


# --------------------------------------------------------------------------
# AwesomeAPI
# --------------------------------------------------------------------------

def url_awesomeapi(moedas: list[str]) -> str:
    pares = ",".join(f"{m}-BRL" for m in moedas)
    return f"https://economia.awesomeapi.com.br/json/last/{pares}"


def ler_awesomeapi(texto: str, moedas: list[str]) -> dict[str, Cotacao]:
    dados = json.loads(texto)
    cotacoes = {}
    for moeda in moedas:
        item = dados.get(f"{moeda}BRL")
        if not item:
            continue
        cotacoes[moeda] = Cotacao(
            moeda=moeda,
            valor=float(item["bid"]),
            data_hora=item.get("create_date", ""),
            fonte="AwesomeAPI",
        )
    return cotacoes


# --------------------------------------------------------------------------
# PTAX - Banco Central
# --------------------------------------------------------------------------

def url_ptax(moeda: str, hoje: date) -> str:
    base = ("https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
            "CotacaoMoedaPeriodo(moeda=@moeda,dataInicial=@dataInicial,"
            "dataFinalCotacao=@dataFinalCotacao)")
    inicio = hoje - timedelta(days=7)
    parametros = {
        "@moeda": f"'{moeda}'",
        "@dataInicial": f"'{inicio:%m-%d-%Y}'",
        "@dataFinalCotacao": f"'{hoje:%m-%d-%Y}'",
        "$format": "json",
        "$orderby": "dataHoraCotacao desc",
        "$top": "1",
    }
    consulta = urllib.parse.urlencode(parametros, safe="@$'", quote_via=urllib.parse.quote)
    return f"{base}?{consulta}"


def ler_ptax(texto: str, moeda: str) -> Cotacao | None:
    valores = json.loads(texto).get("value", [])
    if not valores:
        return None
    item = valores[0]
    return Cotacao(
        moeda=moeda,
        valor=float(item["cotacaoVenda"]),
        data_hora=str(item.get("dataHoraCotacao", ""))[:19],
        fonte="Banco Central (PTAX)",
    )


# --------------------------------------------------------------------------
# Busca com reserva
# --------------------------------------------------------------------------

def buscar_cotacoes(moedas: list[str], abrir: AbrirUrl = abrir_url,
                    hoje: date | None = None) -> dict[str, Cotacao]:
    """Devolve a cotação de cada moeda pedida.

    Tenta a AwesomeAPI para todas de uma vez e completa as que faltarem com a
    PTAX. Levanta ErroCotacao se alguma moeda ficar sem cotação.
    """
    moedas = [m for m in dict.fromkeys(m.upper() for m in moedas) if m != "BRL"]
    if not moedas:
        return {}
    erros: list[str] = []
    cotacoes: dict[str, Cotacao] = {}

    try:
        cotacoes.update(ler_awesomeapi(abrir(url_awesomeapi(moedas)), moedas))
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as erro:
        erros.append(f"AwesomeAPI: {erro}")

    hoje = hoje or datetime.now().date()
    for moeda in moedas:
        if moeda in cotacoes:
            continue
        try:
            cotacao = ler_ptax(abrir(url_ptax(moeda, hoje)), moeda)
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError) as erro:
            erros.append(f"Banco Central ({moeda}): {erro}")
            continue
        if cotacao:
            cotacoes[moeda] = cotacao

    faltando = [m for m in moedas if m not in cotacoes]
    if faltando:
        detalhes = "; ".join(erros) or "nenhuma fonte informou a cotação"
        raise ErroCotacao(f"Sem cotação para {', '.join(faltando)} ({detalhes})")
    return cotacoes
