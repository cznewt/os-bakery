import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0007_alter_integration_token'),
    ]

    operations = [
        migrations.CreateModel(
            name='WireguardIdentity',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('interface', models.CharField(help_text="WireGuard interface this keypair belongs to (e.g. wg0). Matches wireguard.interfaces[].name; emitted to pillar as that interface's private_key.", max_length=15)),
                ('private_key', models.TextField(blank=True, help_text='[Interface] PrivateKey (wg genkey). Spliced into the pillar. Sensitive.')),
                ('public_key', models.TextField(blank=True, help_text='Derived public key (wg pubkey). Authorize this as a [Peer] PublicKey on the WireGuard server/hub.')),
                ('node', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='wireguard_identities', to='tenants.node')),
            ],
            options={
                'verbose_name': 'WireGuard identity',
                'verbose_name_plural': 'WireGuard identities',
                'ordering': ['node', 'interface'],
                'constraints': [models.UniqueConstraint(fields=('node', 'interface'), name='uniq_wg_identity_node_interface')],
            },
        ),
    ]
