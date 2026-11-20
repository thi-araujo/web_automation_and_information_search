import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import precos as pr  # noqa: E402

try:
    import openpyxl
except ImportError:  # os testes de .xlsx são pulados sem openpyxl
    openpyxl = None

EXEMPLO = Path(__file__).resolve().parent.parent / "exemplo" / "Produtos.xlsx"


class TestConversoes(unittest.TestCase):
    def test_numero(self):
        casos = {"1.234,56": 1234.56, "R$ 99,90": 99.9, "1234.5": 1234.5, "10": 10.0, 7: 7.0, 2.5: 2.5}
        for entrada, esperado in casos.items():
            self.assertAlmostEqual(pr.numero(entrada), esperado, msg=entrada)
        with self.assertRaises(ValueError):
            pr.numero("abc")

    def test_margem(self):
        self.assertEqual(pr.margem(1.5), 1.5)
        self.assertEqual(pr.margem("50%"), 1.5)
        self.assertEqual(pr.margem("1,8"), 1.8)
        with self.assertRaises(ValueError):
            pr.margem(0)

    def test_moeda(self):
        for texto, codigo in (("Dólar", "USD"), ("dolar", "USD"), ("US$", "USD"), ("Euro", "EUR"),
                              ("€", "EUR"), ("Libra", "GBP"), ("Real", "BRL"), ("R$", "BRL")):
            self.assertEqual(pr.normalizar_moeda(texto), codigo, texto)
        with self.assertRaises(ValueError):
            pr.normalizar_moeda("Iene")

    def test_formatar_reais(self):
        self.assertEqual(pr.formatar_reais(1234567.891), "R$ 1.234.567,89")
        self.assertEqual(pr.formatar_reais(0.5), "R$ 0,50")


class TestCalculo(unittest.TestCase):
    def test_formula_do_projeto_original(self):
        produtos = [pr.Produto("Câmera", 1000.0, "USD", 1.5, 2), pr.Produto("Cabo", 10.0, "BRL", 2.0, 3)]
        camera, cabo = pr.calcular(produtos, {"USD": 5.0})
        self.assertEqual(camera.preco_compra, 5000.0)   # 1000 x 5
        self.assertEqual(camera.preco_venda, 7500.0)    # 5000 x 1,5
        self.assertEqual(cabo.cotacao, 1.0)
        self.assertEqual(cabo.preco_venda, 20.0)

    def test_falta_cotacao(self):
        with self.assertRaises(ValueError):
            pr.calcular([pr.Produto("Relógio", 10.0, "GBP", 1.2, 2)], {"USD": 5.0})

    def test_moedas_usadas(self):
        produtos = [pr.Produto("a", 1, "EUR", 1, 2), pr.Produto("b", 1, "USD", 1, 3),
                    pr.Produto("c", 1, "BRL", 1, 4), pr.Produto("d", 1, "USD", 1, 5)]
        self.assertEqual(pr.moedas_usadas(produtos), ["EUR", "USD"])


class TestPlanilhas(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.TemporaryDirectory()
        self.dir = Path(self.pasta.name)

    def tearDown(self):
        self.pasta.cleanup()

    def test_csv_brasileiro(self):
        arquivo = self.dir / "produtos.csv"
        arquivo.write_text("produto;preço original;moeda;margem\n"
                           "Notebook;1.180,00;Euro;1,35\n"
                           ";;;\n"
                           "Mouse;29,90;Dólar;50%\n", encoding="cp1252")
        produtos = pr.ler_planilha(arquivo)
        self.assertEqual([p.nome for p in produtos], ["Notebook", "Mouse"])
        self.assertEqual(produtos[0].preco_original, 1180.0)
        self.assertEqual(produtos[1].margem, 1.5)

    def test_coluna_faltando(self):
        arquivo = self.dir / "produtos.csv"
        arquivo.write_text("Produto,Preço,Moeda\nA,1,Dólar\n", encoding="utf-8")
        with self.assertRaises(pr.ErroPlanilha) as contexto:
            pr.ler_planilha(arquivo)
        self.assertIn("Preço Original", str(contexto.exception))

    def test_linha_invalida_indica_onde(self):
        arquivo = self.dir / "produtos.csv"
        arquivo.write_text("Produto,Preço Original,Moeda,Margem\nA,abc,Dólar,1.5\nB,2,Iene,1.5\n",
                           encoding="utf-8")
        with self.assertRaises(pr.ErroPlanilha) as contexto:
            pr.ler_planilha(arquivo)
        self.assertIn("linha 2 (A)", str(contexto.exception))
        self.assertIn("linha 3 (B)", str(contexto.exception))

    def test_formato_nao_suportado(self):
        with self.assertRaises(pr.ErroPlanilha):
            pr.ler_planilha(self.dir / "produtos.txt")

    @unittest.skipUnless(openpyxl, "openpyxl não instalado")
    def test_exemplo_e_exportacao(self):
        produtos = pr.ler_planilha(EXEMPLO)
        self.assertEqual(len(produtos), 8)
        self.assertEqual(pr.moedas_usadas(produtos), ["EUR", "GBP", "USD"])
        precos = pr.calcular(produtos, {"USD": 5.0, "EUR": 6.0, "GBP": 7.0})
        destino = self.dir / "saida.xlsx"
        pr.exportar_xlsx(precos, destino, [("USD", 5.0, "teste")])

        livro = openpyxl.load_workbook(destino)
        aba = livro["Preços"]
        self.assertEqual(aba["A1"].value, "Produto")
        self.assertEqual(aba["G1"].value, "Preço de Venda")
        self.assertAlmostEqual(aba["G2"].value, 999.99 * 5.0 * 1.4)
        self.assertEqual(aba.max_row, 9)
        self.assertEqual(livro["Cotações"]["C2"].value, "teste")


if __name__ == "__main__":
    unittest.main()
