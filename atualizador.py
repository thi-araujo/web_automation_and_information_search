"""Atualizador de Preços: recalcula em reais os preços de produtos cotados em
moeda estrangeira, usando a cotação do dia.

    python atualizador.py

Requer openpyxl para ler e salvar arquivos .xlsx (pip install -r requirements.txt).
"""

from __future__ import annotations

import platform
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cotacoes as ct
import precos as pr

PASTA_EXEMPLO = Path(__file__).resolve().parent / "exemplo"
SIMBOLOS = {"USD": "US$", "EUR": "€", "GBP": "£", "BRL": "R$"}

CORES = {
    "fundo": "#0f172a",
    "painel": "#1e293b",
    "borda": "#334155",
    "texto": "#e2e8f0",
    "texto_suave": "#94a3b8",
    "destaque": "#38bdf8",
    "verde": "#22c55e",
    "vermelho": "#ef4444",
    "ambar": "#f59e0b",
}

WINDOWS = platform.system() == "Windows"
FONTE = "Segoe UI" if WINDOWS else "Helvetica"
FONTE_MONO = "Consolas" if WINDOWS else "DejaVu Sans Mono"


def valor_moeda(valor: float, moeda: str) -> str:
    texto = pr.formatar_reais(valor)[3:]
    return f"{SIMBOLOS.get(moeda, moeda)} {texto}"


def data_br(texto: str) -> str:
    """ "2026-11-18 17:59:59" -> "18/11/2026 17:59" (devolve o texto original se não reconhecer)."""
    try:
        return datetime.strptime(texto[:16], "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return texto


def configurar_estilo(raiz: tk.Tk) -> None:
    estilo = ttk.Style(raiz)
    estilo.theme_use("clam")
    sem_borda = dict(bordercolor=CORES["painel"], lightcolor=CORES["painel"], darkcolor=CORES["painel"])
    estilo.configure(".", background=CORES["fundo"], foreground=CORES["texto"], font=(FONTE, 10))
    estilo.configure("Painel.TFrame", background=CORES["painel"])
    estilo.configure("Painel.TLabel", background=CORES["painel"])
    estilo.configure("Suave.TLabel", foreground=CORES["texto_suave"])
    estilo.configure("PainelSuave.TLabel", background=CORES["painel"], foreground=CORES["texto_suave"])
    estilo.configure("Titulo.TLabel", background=CORES["painel"], foreground=CORES["destaque"],
                     font=(FONTE, 11, "bold"))
    estilo.configure("TButton", background=CORES["borda"], foreground=CORES["texto"], borderwidth=0,
                     padding=(14, 7), font=(FONTE, 10, "bold"))
    estilo.map("TButton", background=[("disabled", CORES["painel"]), ("active", "#475569")],
               foreground=[("disabled", CORES["texto_suave"])])
    estilo.configure("Destaque.TButton", background=CORES["destaque"], foreground=CORES["fundo"])
    estilo.map("Destaque.TButton", background=[("disabled", CORES["painel"]), ("active", "#0ea5e9")])
    estilo.configure("Verde.TButton", background=CORES["verde"], foreground="#052e16")
    estilo.map("Verde.TButton", background=[("disabled", CORES["painel"]), ("active", "#16a34a")])
    estilo.configure("TEntry", fieldbackground=CORES["fundo"], foreground=CORES["texto"],
                     insertcolor=CORES["texto"], bordercolor=CORES["borda"], lightcolor=CORES["fundo"],
                     darkcolor=CORES["fundo"])
    estilo.configure("Treeview", background=CORES["painel"], fieldbackground=CORES["painel"],
                     foreground=CORES["texto"], borderwidth=0, rowheight=28, **sem_borda)
    estilo.configure("Treeview.Heading", background=CORES["borda"], foreground=CORES["texto_suave"],
                     borderwidth=0, font=(FONTE, 9, "bold"), padding=(6, 5))
    estilo.map("Treeview", background=[("selected", CORES["borda"])],
               foreground=[("selected", CORES["destaque"])])
    estilo.configure("Vertical.TScrollbar", background=CORES["borda"], troughcolor=CORES["painel"],
                     borderwidth=0, arrowcolor=CORES["texto_suave"], **sem_borda)
    estilo.map("Vertical.TScrollbar", background=[("disabled", CORES["painel"]), ("active", "#475569")],
               arrowcolor=[("disabled", CORES["painel"])])


class Aplicativo(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Atualizador de Preços")
        self.geometry("980x640")
        self.minsize(860, 560)
        self.configure(bg=CORES["fundo"])
        configurar_estilo(self)

        self.produtos: list[pr.Produto] = []
        self.precos: list[pr.PrecoCalculado] = []
        self.caminho: Path | None = None
        self.fontes: dict[str, tuple[str, str]] = {}  # moeda -> (valor exibido, origem)
        self.respostas: queue.Queue = queue.Queue()

        self._montar()
        self._atualizar_estado()

    # ------------------------------------------------------------------ tela

    def _montar(self) -> None:
        topo = ttk.Frame(self, padding=(16, 16, 16, 8))
        topo.pack(fill="x")
        ttk.Button(topo, text="Abrir planilha...", style="Destaque.TButton",
                   command=self.abrir).pack(side="left")
        ttk.Button(topo, text="Usar exemplo", command=self.abrir_exemplo).pack(side="left", padx=8)
        self.lbl_arquivo = ttk.Label(topo, text="Nenhuma planilha aberta", style="Suave.TLabel")
        self.lbl_arquivo.pack(side="left", padx=8)

        # Cotações
        painel = ttk.Frame(self, style="Painel.TFrame", padding=14)
        painel.pack(fill="x", padx=16, pady=8)
        cabeca = ttk.Frame(painel, style="Painel.TFrame")
        cabeca.pack(fill="x")
        ttk.Label(cabeca, text="Cotações (R$)", style="Titulo.TLabel").pack(side="left")
        self.btn_buscar = ttk.Button(cabeca, text="Buscar cotações online", command=self.buscar)
        self.btn_buscar.pack(side="right")

        linha = ttk.Frame(painel, style="Painel.TFrame")
        linha.pack(fill="x", pady=(10, 0))
        self.var_cotacoes: dict[str, tk.StringVar] = {}
        self.lbl_fontes: dict[str, ttk.Label] = {}
        for i, (codigo, nome) in enumerate(ct.MOEDAS.items()):
            bloco = ttk.Frame(linha, style="Painel.TFrame")
            bloco.grid(row=0, column=i, sticky="w", padx=(0, 28))
            ttk.Label(bloco, text=f"{nome} ({SIMBOLOS[codigo]})", style="Painel.TLabel",
                      font=(FONTE, 10, "bold")).pack(anchor="w")
            var = tk.StringVar()
            entrada = ttk.Entry(bloco, textvariable=var, width=12, font=(FONTE_MONO, 12))
            entrada.pack(anchor="w", pady=4, ipady=2)
            entrada.bind("<Return>", lambda _e: self.recalcular())
            entrada.bind("<FocusOut>", lambda _e: self.recalcular())
            fonte = ttk.Label(bloco, text="digite ou busque online", style="PainelSuave.TLabel",
                              font=(FONTE, 8))
            fonte.pack(anchor="w")
            self.var_cotacoes[codigo] = var
            self.lbl_fontes[codigo] = fonte

        # Tabela
        meio = ttk.Frame(self, padding=(16, 8, 16, 0))
        meio.pack(fill="both", expand=True)
        colunas = (("produto", "Produto", 220, "w"), ("original", "Preço original", 120, "e"),
                   ("cotacao", "Cotação", 80, "e"), ("compra", "Preço de compra", 130, "e"),
                   ("margem", "Margem", 70, "center"), ("venda", "Preço de venda", 130, "e"))
        self.tabela = ttk.Treeview(meio, columns=[c[0] for c in colunas], show="headings")
        for chave, titulo, largura, ancora in colunas:
            self.tabela.heading(chave, text=titulo, anchor=ancora)
            self.tabela.column(chave, width=largura, anchor=ancora, stretch=chave == "produto")
        self.tabela.tag_configure("pendente", foreground=CORES["texto_suave"])
        barra = ttk.Scrollbar(meio, orient="vertical", command=self.tabela.yview)
        self.tabela.configure(yscrollcommand=barra.set)
        self.tabela.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.lbl_vazio = tk.Label(self.tabela, bg=CORES["painel"], fg=CORES["texto_suave"], font=(FONTE, 11),
                                  text="Abra uma planilha com as colunas\n"
                                       "Produto, Preço Original, Moeda e Margem\n"
                                       "ou clique em \"Usar exemplo\".")

        # Rodapé
        rodape = ttk.Frame(self, padding=16)
        rodape.pack(fill="x")
        self.lbl_status = ttk.Label(rodape, text="", style="Suave.TLabel")
        self.lbl_status.pack(side="left")
        self.btn_exportar = ttk.Button(rodape, text="Exportar planilha atualizada...", style="Verde.TButton",
                                       command=self.exportar)
        self.btn_exportar.pack(side="right")

    def _status(self, texto: str, cor: str = "texto_suave") -> None:
        self.lbl_status.configure(text=texto, foreground=CORES[cor])

    def _atualizar_estado(self) -> None:
        if self.produtos:
            self.lbl_vazio.place_forget()
        else:
            self.lbl_vazio.place(relx=0.5, rely=0.5, anchor="center")
        completo = bool(self.precos) and len(self.precos) == len(self.produtos)
        self.btn_exportar.state(["!disabled"] if completo else ["disabled"])

    # ------------------------------------------------------------------ planilha

    def abrir(self) -> None:
        caminho = filedialog.askopenfilename(
            parent=self, title="Abrir planilha de produtos",
            filetypes=[("Planilhas", "*.xlsx *.xlsm *.csv"), ("Excel", "*.xlsx *.xlsm"), ("CSV", "*.csv")],
        )
        if caminho:
            self.carregar(Path(caminho))

    def abrir_exemplo(self) -> None:
        self.carregar(PASTA_EXEMPLO / "Produtos.xlsx")

    def carregar(self, caminho: Path) -> None:
        try:
            self.produtos = pr.ler_planilha(caminho)
        except (pr.ErroPlanilha, OSError) as erro:
            messagebox.showerror("Não foi possível abrir a planilha", str(erro), parent=self)
            return
        except ImportError:
            messagebox.showerror("Falta o openpyxl", "Para abrir arquivos .xlsx, instale:\n\n"
                                 "pip install -r requirements.txt", parent=self)
            return
        self.caminho = caminho
        self.lbl_arquivo.configure(text=f"{caminho.name}  ·  {len(self.produtos)} produtos")
        usadas = pr.moedas_usadas(self.produtos)
        self._status(f"Moedas na planilha: {', '.join(usadas) or 'só reais'}")
        self.recalcular()
        if any(not self.var_cotacoes[m].get().strip() for m in usadas if m in self.var_cotacoes):
            self.buscar()

    # ------------------------------------------------------------------ cotações

    def _cotacoes_digitadas(self) -> dict[str, float]:
        valores = {}
        for codigo, var in self.var_cotacoes.items():
            texto = var.get().strip()
            if not texto:
                continue
            try:
                valor = pr.numero(texto)
            except ValueError:
                continue
            if valor > 0:
                valores[codigo] = valor
        return valores

    def buscar(self) -> None:
        moedas = pr.moedas_usadas(self.produtos) or list(ct.MOEDAS)
        moedas = [m for m in moedas if m in ct.MOEDAS]
        self.btn_buscar.state(["disabled"])
        self._status(f"Buscando cotações de {', '.join(moedas)}...", "destaque")

        def tarefa():
            try:
                self.respostas.put(ct.buscar_cotacoes(moedas))
            except ct.ErroCotacao as erro:
                self.respostas.put(erro)

        threading.Thread(target=tarefa, daemon=True).start()
        self.after(100, self._receber_cotacoes)

    def _receber_cotacoes(self) -> None:
        try:
            resposta = self.respostas.get_nowait()
        except queue.Empty:
            self.after(100, self._receber_cotacoes)
            return
        self.btn_buscar.state(["!disabled"])
        if isinstance(resposta, Exception):
            self._status("Sem conexão com as fontes de cotação. Digite os valores à mão.", "ambar")
            messagebox.showwarning("Cotações", f"{resposta}\n\nVocê pode digitar as cotações à mão.",
                                   parent=self)
            return
        for codigo, cotacao in resposta.items():
            texto = f"{cotacao.valor:.4f}".replace(".", ",")
            self.var_cotacoes[codigo].set(texto)
            self.fontes[codigo] = (texto, f"{cotacao.fonte}, {data_br(cotacao.data_hora)}")
        self._status(f"Cotações atualizadas às {datetime.now():%H:%M}.", "verde")
        self.recalcular()

    # ------------------------------------------------------------------ cálculo

    def recalcular(self) -> None:
        cotacoes = self._cotacoes_digitadas()
        for codigo, var in self.var_cotacoes.items():
            fonte = self.fontes.get(codigo)
            if fonte and var.get().strip() == fonte[0]:
                self.lbl_fontes[codigo].configure(text=fonte[1], foreground=CORES["verde"])
            elif codigo in cotacoes:
                self.fontes.pop(codigo, None)
                self.lbl_fontes[codigo].configure(text="valor digitado", foreground=CORES["ambar"])
            else:
                self.fontes.pop(codigo, None)
                self.lbl_fontes[codigo].configure(text="digite ou busque online",
                                                  foreground=CORES["texto_suave"])

        self.tabela.delete(*self.tabela.get_children())
        self.precos = []
        for produto in self.produtos:
            original = valor_moeda(produto.preco_original, produto.moeda)
            margem = f"{produto.margem:.2f}".replace(".", ",")
            cotacao = 1.0 if produto.moeda == "BRL" else cotacoes.get(produto.moeda)
            if cotacao is None:
                self.tabela.insert("", "end", tags=("pendente",),
                                   values=(produto.nome, original, "falta", "-", margem, "-"))
                continue
            calculado = pr.calcular([produto], {produto.moeda: cotacao})[0]
            self.precos.append(calculado)
            self.tabela.insert("", "end", values=(
                produto.nome, original, f"{cotacao:.4f}".replace(".", ","),
                pr.formatar_reais(calculado.preco_compra), margem, pr.formatar_reais(calculado.preco_venda)))
        self._atualizar_estado()

    # ------------------------------------------------------------------ exportação

    def exportar(self) -> None:
        if not self.precos or not self.caminho:
            return
        sugestao = f"{self.caminho.stem} atualizado {datetime.now():%Y-%m-%d}.xlsx"
        destino = filedialog.asksaveasfilename(parent=self, title="Salvar planilha atualizada",
                                               initialdir=self.caminho.parent, initialfile=sugestao,
                                               defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx")])
        if not destino:
            return
        cotacoes = self._cotacoes_digitadas()
        info = [(c, cotacoes[c], self.fontes[c][1] if c in self.fontes else "digitado à mão")
                for c in pr.moedas_usadas(self.produtos) if c in cotacoes]
        try:
            pr.exportar_xlsx(self.precos, destino, info)
        except (OSError, ImportError) as erro:
            messagebox.showerror("Não foi possível salvar", str(erro), parent=self)
            return
        self._status(f"Planilha salva em {destino}", "verde")


def main() -> None:
    Aplicativo().mainloop()


if __name__ == "__main__":
    main()
