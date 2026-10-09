// Service worker du site. A servir a la RACINE (https://ton-site/sw.js) pour couvrir toutes les pages.

self.addEventListener("push", (event) => {
  const message = event.data ? event.data.json() : { title: "Notification" };
  // Toujours afficher une notification : sans showNotification, Chrome affiche
  // son propre message generique et peut finir par couper les push du site.
  event.waitUntil(
    self.registration.showNotification(message.title, {
      body: message.body || "",
      icon: "/static/icons/192.png",
      data: { url: message.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((fenetres) => {
      for (const fenetre of fenetres) {
        if (fenetre.url.endsWith(url) && "focus" in fenetre) return fenetre.focus();
      }
      return clients.openWindow(url);
    })
  );
});
