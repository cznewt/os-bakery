from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('builds', '0002_buildrequest_cluster_buildrequest_tenant'),
    ]

    operations = [
        migrations.AddField(
            model_name='buildrequest',
            name='effective_model',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    'Snapshot of the merged config baked into the image: device '
                    'identity (hardware model/SoC/arch) + recipe defaults + '
                    'per-build options + the joined cluster\'s parameters. Written '
                    'verbatim onto the image as model.yaml and shown on the '
                    'baked-image page.'
                ),
            ),
        ),
    ]
