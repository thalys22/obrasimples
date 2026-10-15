"""
Roda a cada publicação na Vercel (configurado em pyproject.toml).
1. Cria/atualiza as tabelas do banco (migrate).
2. Cria o usuário administrador na primeira vez, se as variáveis
   DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL e DJANGO_SUPERUSER_PASSWORD existirem.
"""
import os
import sys

import django
from django.core.management import call_command

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

print("Prumo: aplicando migrações…")
call_command("migrate", interactive=False)

usuario = os.environ.get("DJANGO_SUPERUSER_USERNAME")
if usuario and os.environ.get("DJANGO_SUPERUSER_PASSWORD"):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if User.objects.filter(username=usuario).exists():
        print(f"Prumo: administrador '{usuario}' já existe, nada a fazer.")
    else:
        call_command("createsuperuser", interactive=False)
        print(f"Prumo: administrador '{usuario}' criado.")
else:
    print("Prumo: variáveis do administrador não definidas; pulando criação.", file=sys.stderr)
