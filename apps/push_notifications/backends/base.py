from __future__ import annotations

from dataclasses import dataclass, field

# Ce qu'un fournisseur repond pour UN appareil.
OK = "ok"            # accepte par le fournisseur
GONE = "gone"        # jeton mort (appli desinstallee, abonnement expire) : on supprime l'appareil
FAILED = "failed"    # echec passager ou de configuration : on garde l'appareil et on note l'erreur
SKIPPED = "skipped"  # fournisseur non configure : on ne touche a rien


@dataclass
class PushMessage:
    title: str
    body: str = ""
    url: str = ""
    data: dict = field(default_factory=dict)
    ttl: int = 24 * 3600  # secondes pendant lesquelles le fournisseur garde le message si l'appareil est eteint

    def data_as_strings(self) -> dict[str, str]:
        """Firebase refuse toute valeur non texte dans "data" : tout est converti en chaine."""
        donnees = {str(k): v if isinstance(v, str) else str(v) for k, v in self.data.items()}
        if self.url:
            donnees.setdefault("url", self.url)
        return donnees
