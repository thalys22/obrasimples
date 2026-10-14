"""
Configurações do ObraSimples.

Tudo que muda entre o seu computador e o servidor vem de variáveis de ambiente:
  DJANGO_SECRET_KEY       chave secreta (obrigatória em produção)
  DJANGO_DEBUG            "1" para desenvolvimento local, "0" (padrão) em produção
  DJANGO_ALLOWED_HOSTS    domínios separados por vírgula, ex.: "meuapp.pythonanywhere.com"
  DJANGO_CSRF_TRUSTED     origens com https, ex.: "https://meuapp.pythonanywhere.com"
  DATABASE_URL            opcional; sem ela usa SQLite (db.sqlite3). Ex.: postgres://usuario:senha@host:5432/banco
                          (na Vercel é obrigatória; a integração Neon preenche sozinha)
"""
import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    "dev-inseguro-troque-em-producao" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("Defina a variável de ambiente DJANGO_SECRET_KEY (veja o README).")

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED", "").split(",") if o.strip()]

# Vercel: aceita automaticamente os endereços .vercel.app do projeto
NA_VERCEL = os.environ.get("VERCEL") == "1"
if NA_VERCEL:
    for var in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = os.environ.get(var)
        if host:
            ALLOWED_HOSTS.append(host)
            CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "obras",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Banco: DATABASE_URL (ou POSTGRES_URL, nome usado por algumas integrações da Vercel).
# Sem nenhuma das duas, usa SQLite local. Na Vercel o SQLite não guarda dados, então lá é obrigatório PostgreSQL.
_db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if NA_VERCEL and not _db_url:
    raise RuntimeError("Na Vercel é preciso um banco PostgreSQL: adicione o Neon em Storage (ele define DATABASE_URL).")
DATABASES = {
    "default": dj_database_url.parse(_db_url, conn_max_age=0 if NA_VERCEL else 600, ssl_require=NA_VERCEL)
    if _db_url else dj_database_url.parse(f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
}
if NA_VERCEL:
    # O endereço do Neon passa por um pooler (PgBouncer em modo transação): sem cursores no servidor
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "app"
LOGOUT_REDIRECT_URL = "login"

# Sessão expira após 14 dias sem uso
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"
    # Ligue (DJANGO_SSL_REDIRECT=1) se o servidor não forçar HTTPS sozinho
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SSL_REDIRECT", "0") == "1"
