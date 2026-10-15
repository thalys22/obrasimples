from django.db import migrations


def carregar(apps, schema_editor):
    from obras.biblioteca import carregar_biblioteca
    carregar_biblioteca(apps.get_model("obras", "Insumo"), apps.get_model("obras", "Composicao"), apps.get_model("obras", "ItemComposicao"))


class Migration(migrations.Migration):

    dependencies = [("obras", "0003_catalogo_e_etapas")]

    operations = [migrations.RunPython(carregar, migrations.RunPython.noop)]
