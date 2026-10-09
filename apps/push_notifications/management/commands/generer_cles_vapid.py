from django.core.management.base import BaseCommand

from push_notifications.cles import generate_vapid_keys


class Command(BaseCommand):
    help = "Genere une paire de cles VAPID pour le Web Push (a faire une seule fois)."

    def handle(self, *args, **options):
        publique, privee = generate_vapid_keys()
        self.stdout.write("Copie ces deux lignes dans tes variables d'environnement (jamais dans le code) :\n")
        self.stdout.write(f"PUSH_VAPID_PUBLIC_KEY={publique}")
        self.stdout.write(f"PUSH_VAPID_PRIVATE_KEY={privee}")
        self.stdout.write(
            "\nAttention : changer de cles plus tard invalide tous les abonnements des navigateurs."
        )
