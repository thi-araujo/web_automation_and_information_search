import json
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cotacoes as ct  # noqa: E402

# Formatos das respostas reais das APIs (valores ilustrativos).
RESPOSTA_AWESOME = json.dumps({
    "USDBRL": {"code": "USD", "codein": "BRL", "bid": "5.4321", "ask": "5.4331",
               "create_date": "2026-11-18 17:59:59"},
    "EURBRL": {"code": "EUR", "codein": "BRL", "bid": "6.1234", "ask": "6.1300",
               "create_date": "2026-11-18 17:59:58"},
})
RESPOSTA_PTAX = json.dumps({
    "@odata.context": "https://olinda.bcb.gov.br/...",
    "value": [{"paridadeCompra": 1.0, "paridadeVenda": 1.0, "cotacaoCompra": 7.0011,
               "cotacaoVenda": 7.0017, "dataHoraCotacao": "2026-11-18 13:09:30.123",
               "tipoBoletim": "Fechamento"}],
})


class AbrirFalso:
    """Simula a internet: devolve respostas conforme o endereço pedido."""

    def __init__(self, awesome=RESPOSTA_AWESOME, ptax=RESPOSTA_PTAX):
        self.awesome, self.ptax = awesome, ptax
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        resposta = self.awesome if "awesomeapi" in url else self.ptax
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class TestFontes(unittest.TestCase):
    def test_url_awesomeapi(self):
        self.assertEqual(ct.url_awesomeapi(["USD", "EUR"]),
                         "https://economia.awesomeapi.com.br/json/last/USD-BRL,EUR-BRL")

    def test_url_ptax(self):
        url = ct.url_ptax("USD", date(2026, 11, 18))
        self.assertIn("@moeda='USD'", url)
        self.assertIn("@dataInicial='11-11-2026'", url)
        self.assertIn("@dataFinalCotacao='11-18-2026'", url)
        self.assertIn("$format=json", url)
        self.assertIn("$orderby=dataHoraCotacao%20desc", url)

    def test_ler_awesomeapi(self):
        cotacoes = ct.ler_awesomeapi(RESPOSTA_AWESOME, ["USD", "EUR", "GBP"])
        self.assertEqual(cotacoes["USD"].valor, 5.4321)
        self.assertEqual(cotacoes["EUR"].data_hora, "2026-11-18 17:59:58")
        self.assertNotIn("GBP", cotacoes)

    def test_ler_ptax(self):
        cotacao = ct.ler_ptax(RESPOSTA_PTAX, "GBP")
        self.assertEqual(cotacao.valor, 7.0017)
        self.assertEqual(cotacao.data_hora, "2026-11-18 13:09:30")
        self.assertIsNone(ct.ler_ptax('{"value": []}', "GBP"))


class TestBuscar(unittest.TestCase):
    def test_awesomeapi_resolve_tudo(self):
        abrir = AbrirFalso()
        cotacoes = ct.buscar_cotacoes(["usd", "EUR", "USD", "BRL"], abrir, date(2026, 11, 18))
        self.assertEqual(set(cotacoes), {"USD", "EUR"})
        self.assertEqual(len(abrir.urls), 1)  # uma única chamada

    def test_completa_com_ptax(self):
        abrir = AbrirFalso()
        cotacoes = ct.buscar_cotacoes(["USD", "GBP"], abrir, date(2026, 11, 18))
        self.assertEqual(cotacoes["USD"].fonte, "AwesomeAPI")
        self.assertEqual(cotacoes["GBP"].fonte, "Banco Central (PTAX)")

    def test_awesomeapi_fora_do_ar(self):
        abrir = AbrirFalso(awesome=urllib.error.URLError("timeout"))
        cotacoes = ct.buscar_cotacoes(["USD"], abrir, date(2026, 11, 18))
        self.assertEqual(cotacoes["USD"].valor, 7.0017)

    def test_resposta_invalida_usa_reserva(self):
        abrir = AbrirFalso(awesome="<html>erro</html>")
        self.assertEqual(ct.buscar_cotacoes(["EUR"], abrir, date(2026, 11, 18))["EUR"].fonte,
                         "Banco Central (PTAX)")

    def test_sem_internet(self):
        erro = urllib.error.URLError("sem rede")
        with self.assertRaises(ct.ErroCotacao) as contexto:
            ct.buscar_cotacoes(["USD", "EUR"], AbrirFalso(awesome=erro, ptax=erro), date(2026, 11, 18))
        self.assertIn("USD, EUR", str(contexto.exception))

    def test_lista_vazia(self):
        self.assertEqual(ct.buscar_cotacoes(["BRL"], AbrirFalso()), {})


if __name__ == "__main__":
    unittest.main()
