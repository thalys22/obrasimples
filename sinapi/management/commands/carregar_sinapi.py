import json
import time
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from sinapi import carga, leitor


class Command(BaseCommand):
    help = "Carrega o xlsx oficial do SINAPI (rode fora da Vercel; precisa de requirements-etl.txt)."

    def add_arguments(self, p):
        p.add_argument("--arquivo", required=True)
        p.add_argument("--base", required=True, help="Mês de referência, AAAA-MM (ex.: 2026-09)")
        p.add_argument("--uf", nargs="+", required=True)
        p.add_argument("--regime", nargs="+", default=["sd", "cd"], choices=["sd", "cd", "se"])
        p.add_argument("--json", action="store_true", help="imprime o relatório em JSON no fim")

    def handle(self, *a, **o):
        try:
            ano, mes = map(int, o["base"].split("-"))
            base = date(ano, mes, 1)
        except ValueError:
            raise CommandError("--base deve ser AAAA-MM, ex.: 2026-09")
        t0 = time.time()
        try:
            rel = carga.carregar(o["arquivo"], base, o["uf"], o["regime"], saida=self.stdout.write)
        except (carga.ErroCarga, leitor.ErroLayout) as e:
            raise CommandError(str(e))
        except ImportError:
            raise CommandError("openpyxl não instalado: pip install -r requirements-etl.txt")
        self.stdout.write(self.style.SUCCESS(f"Concluído em {time.time() - t0:.1f}s."))
        if rel.get("unidades_fora_do_mapa"):
            self.stdout.write(self.style.WARNING(f"Unidades fora do mapa: {rel['unidades_fora_do_mapa']}"))
        if o["json"]:
            self.stdout.write(json.dumps(rel, indent=2, ensure_ascii=False, default=str))
