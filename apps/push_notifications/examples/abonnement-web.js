// Abonner le navigateur aux notifications. A appeler depuis un CLIC (bouton « Activer les notifications ») :
// Safari et Firefox refusent une demande de permission sans geste de l'utilisateur.
//
// entetes : l'authentification de ton API.
//   Session Django : { "X-CSRFToken": <valeur du cookie csrftoken> }
//   JWT            : { Authorization: "Bearer <jeton>" }
export async function activerNotifications({ api = "/api/push", entetes = {} } = {}) {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    throw new Error("Ce navigateur ne gere pas le push. Sur iPhone : ajoute d'abord le site a l'ecran d'accueil.");
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Les notifications sont refusees dans ce navigateur.");

  const enregistrement = await navigator.serviceWorker.register("/sw.js");
  await navigator.serviceWorker.ready;

  const { public_key } = await (await fetch(`${api}/cle-vapid/`)).json();
  if (!public_key) throw new Error("Cle VAPID absente cote serveur.");
  const cle = base64UrlEnOctets(public_key);

  let abonnement = await enregistrement.pushManager.getSubscription();
  // Cles VAPID changees cote serveur : l'ancien abonnement est mort, on en refait un.
  if (abonnement && !memesOctets(abonnement.options.applicationServerKey, cle)) {
    await abonnement.unsubscribe();
    abonnement = null;
  }
  if (!abonnement) {
    abonnement = await enregistrement.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: cle });
  }

  const reponse = await fetch(`${api}/appareils/`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...entetes },
    body: JSON.stringify({ kind: "web", subscription: abonnement.toJSON() }),
  });
  if (!reponse.ok) throw new Error(`Le serveur a refuse l'abonnement (HTTP ${reponse.status}).`);
}

function base64UrlEnOctets(texte) {
  const complet = texte + "=".repeat((4 - (texte.length % 4)) % 4);
  const brut = atob(complet.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(brut, (c) => c.charCodeAt(0));
}

function memesOctets(tampon, octets) {
  if (!tampon) return false;
  const a = new Uint8Array(tampon);
  return a.length === octets.length && a.every((v, i) => v === octets[i]);
}
