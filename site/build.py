# -*- coding: utf-8 -*-
"""Genere le catalogue statique de la librairie (site/dist/), deploye sur Vercel.

Source de verite : CATALOG.md (table des templates) + le README/SETTINGS de
chaque app. Zero framework : du HTML statique genere ici, donc rien a casser
et un deploiement Vercel instantane. Relancer apres tout changement de
template : python site/build.py
"""
import html
import re
import shutil
from pathlib import Path

import markdown

RACINE = Path(__file__).resolve().parent.parent
DIST = RACINE / "site" / "dist"
DEMO_URL = "https://web-production-7b1cc.up.railway.app"
REPO_URL = "https://github.com/TokDar2410621/django-templates"

MD = markdown.Markdown(extensions=["fenced_code", "tables", "toc"])

PITCHES = {}  # slug -> premiere phrase utile du README


def lire(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def parse_catalog():
    """Les lignes de la table de CATALOG.md -> [{slug, version, mode, source, deps}]."""
    apps = []
    for ligne in lire(RACINE / "CATALOG.md").splitlines():
        m = re.match(r"\| `([a-z0-9-]+)` \| ([\d.]+) \| ([A-Z-]+) \| (.*?) \| (.*?) \| (\w+) \|", ligne)
        if m:
            apps.append({
                "slug_kebab": m.group(1),
                "slug": m.group(1).replace("-", "_"),
                "version": m.group(2),
                "mode": m.group(3),
                "source": m.group(4).strip(),
                "deps": [d.strip() for d in m.group(5).split(",") if d.strip()],
                "statut": m.group(6),
            })
    return apps


def parse_snippets():
    rows = []
    bloc = lire(RACINE / "CATALOG.md").split("## Snippets")[1]
    for ligne in bloc.splitlines():
        m = re.match(r"\| `([a-z0-9_.]+)` \| (.*?) \| (.*?) \|", ligne)
        if m and m.group(1) != "File":
            rows.append({"fichier": m.group(1), "quoi": m.group(2).replace("\\|", "|"), "source": m.group(3)})
    return rows


def verbose_name(slug: str) -> str:
    txt = lire(RACINE / "apps" / slug / "apps.py")
    m = re.search(r'verbose_name = "(.*?)"', txt)
    nom = m.group(1) if m else slug
    return nom.replace(" — ", " : ").replace("—", " : ")


def pitch(slug: str) -> str:
    """Premier paragraphe de prose du README, hors bloc de metadonnees."""
    corps = lire(RACINE / "apps" / slug / "README.md")
    corps = re.sub(r"═+.*?═+", "", corps, flags=re.S)  # plaque de metadonnees
    for para in corps.split("\n\n"):
        p = para.strip()
        if p and not p.startswith(("#", "|", "```", "-", "*", ">")):
            p = re.sub(r"\s+", " ", p)
            # Les vieux README portent des em-dashes ; pas sur NOS pages.
            p = p.replace(" — ", " : ").replace("—", " : ")
            return p if len(p) <= 220 else p[:217] + "..."
    return ""


STYLE = """
:root{
  --fond:#0a1410; --fond2:#0e1a15; --carte:#101f18; --lisiere:#1d3328;
  --encre:#ede8dc; --encre2:#a8b5a0; --vert:#44b78b; --vert-fonce:#0c4b33;
  --ambre:#e5a63b; --mono:'IBM Plex Mono',ui-monospace,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--fond);color:var(--encre);font-family:Archivo,system-ui,sans-serif;
  line-height:1.6;font-size:16px;
  background-image:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(68,183,139,.08),transparent),
    repeating-linear-gradient(0deg,transparent,transparent 47px,rgba(68,183,139,.03) 48px);}
a{color:var(--vert);text-decoration:none}
a:hover{text-decoration:underline}
.page{max-width:1080px;margin:0 auto;padding:0 24px}
header.hero{padding:72px 0 48px;border-bottom:1px solid var(--lisiere)}
.sur-titre{font-family:var(--mono);font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--vert)}
h1.titre{font-family:Fraunces,serif;font-weight:900;font-size:clamp(40px,7vw,76px);
  line-height:1.02;margin:14px 0 18px;text-wrap:balance}
h1.titre em{font-style:italic;color:var(--vert)}
.pitch-hero{max-width:56ch;color:var(--encre2);font-size:18px}
.stats{display:flex;gap:32px;margin-top:32px;flex-wrap:wrap}
.stat{font-family:var(--mono)}
.stat b{display:block;font-size:32px;color:var(--encre);font-weight:500}
.stat span{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:var(--encre2)}
.liens-hero{margin-top:28px;display:flex;gap:14px;flex-wrap:wrap}
.btn{font-family:var(--mono);font-size:13px;padding:10px 18px;border:1px solid var(--lisiere);
  border-radius:6px;color:var(--encre);background:var(--carte)}
.btn:hover{border-color:var(--vert);text-decoration:none}
.btn.plein{background:var(--vert-fonce);border-color:var(--vert-fonce);color:#dff5ea}
h2.section{font-family:Fraunces,serif;font-weight:600;font-size:28px;margin:64px 0 8px}
.note-section{color:var(--encre2);margin-bottom:24px;max-width:70ch}
.grille{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:16px}
.carte{background:var(--carte);border:1px solid var(--lisiere);border-radius:10px;
  padding:20px;display:flex;flex-direction:column;gap:10px;transition:border-color .15s, transform .15s}
.carte:hover{border-color:var(--vert);transform:translateY(-2px)}
.carte a.couvre{color:inherit}
.carte a.couvre:hover{text-decoration:none}
.plaque{display:flex;justify-content:space-between;font-family:var(--mono);font-size:11px;
  color:var(--encre2);letter-spacing:.06em}
.plaque .mode{color:var(--ambre)}
.carte h3{font-family:Fraunces,serif;font-weight:600;font-size:20px;line-height:1.2}
.carte .slug{font-family:var(--mono);font-size:12px;color:var(--vert)}
.carte p{font-size:14px;color:var(--encre2);flex:1}
.deps{display:flex;flex-wrap:wrap;gap:6px}
.dep{font-family:var(--mono);font-size:11px;padding:2px 8px;border:1px solid var(--lisiere);
  border-radius:99px;color:var(--encre2)}
table.snips{width:100%;border-collapse:collapse;font-size:14px}
.defil{overflow-x:auto}
table.snips th{font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.14em;
  color:var(--encre2);text-align:left;padding:10px 12px;border-bottom:1px solid var(--lisiere)}
table.snips td{padding:10px 12px;border-bottom:1px solid var(--lisiere);vertical-align:top}
table.snips code{font-family:var(--mono);color:var(--vert);font-size:13px}
.modes{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px}
.mode-carte{border:1px solid var(--lisiere);border-radius:10px;padding:18px;background:var(--fond2)}
.mode-carte b{font-family:var(--mono);color:var(--ambre);letter-spacing:.08em}
.mode-carte p{font-size:14px;color:var(--encre2);margin-top:8px}
footer{margin-top:80px;padding:32px 0 48px;border-top:1px solid var(--lisiere);
  font-family:var(--mono);font-size:12px;color:var(--encre2);display:flex;gap:24px;flex-wrap:wrap}
/* pages de detail */
.retour{font-family:var(--mono);font-size:13px;display:inline-block;margin:32px 0 0}
.doc h1,.doc h2,.doc h3{font-family:Fraunces,serif;margin:36px 0 12px;line-height:1.2}
.doc h1{font-size:34px}.doc h2{font-size:24px;border-bottom:1px solid var(--lisiere);padding-bottom:8px}
.doc p,.doc li{color:#cfd8c8;max-width:78ch}
.doc ul,.doc ol{padding-left:24px;margin:12px 0}
.doc pre{background:#07100c;border:1px solid var(--lisiere);border-radius:8px;padding:16px;
  overflow-x:auto;margin:16px 0;font-size:13px}
.doc code{font-family:var(--mono);font-size:.92em;color:#8fd4b6}
.doc pre code{color:#c8d6cc}
.doc table{border-collapse:collapse;margin:16px 0;font-size:14px;display:block;overflow-x:auto}
.doc th,.doc td{border:1px solid var(--lisiere);padding:8px 12px;text-align:left}
.doc blockquote{border-left:3px solid var(--vert);padding-left:16px;color:var(--encre2);margin:16px 0}
.bandeau-doc{font-family:var(--mono);font-size:12px;color:var(--encre2);margin-top:8px}
.badge-fichier{font-family:var(--mono);font-size:11px;letter-spacing:.18em;text-transform:uppercase;
  color:var(--ambre);margin:48px 0 0;display:block}
"""

TETE = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<meta name="description" content="{desc}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:ital,wght@0,600;0,900;1,900&family=Archivo:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{style}</style>
</head>
<body><div class="page">
"""

PIED = """
<footer>
  <span>django-templates : librairie privée de Darius Tokam</span>
  <a href="{repo}">GitHub (accès requis)</a>
  <a href="{demo}">Vitrine live (Railway)</a>
</footer>
</div></body></html>
"""


def page_index(apps, snippets):
    cartes = []
    for a in apps:
        deps = "".join(f'<span class="dep">{html.escape(d)}</span>' for d in a["deps"])
        cartes.append(f"""
<article class="carte">
  <div class="plaque"><span>v{a['version']} · <span class="mode">{a['mode']}</span></span><span>{a['statut']}</span></div>
  <a class="couvre" href="apps/{a['slug']}.html"><h3>{html.escape(a['verbose'])}</h3></a>
  <span class="slug">{a['slug']}</span>
  <p>{html.escape(a['pitch'])}</p>
  <div class="deps">{deps}</div>
</article>""")
    snips = "".join(
        f"<tr><td><code>{html.escape(s['fichier'])}</code></td><td>{html.escape(s['quoi'])}</td><td>{html.escape(s['source'])}</td></tr>"
        for s in snippets
    )
    corps = f"""
<header class="hero">
  <span class="sur-titre">Catalogue · Django 5 / DRF · production-ready</span>
  <h1 class="titre">Des apps Django<br>qu'on <em>copie</em>,<br>pas qu'on réécrit.</h1>
  <p class="pitch-hero">Chaque template est une app complète extraite de projets en production :
  modèles, services, vues, tests, migrations propres, admin. On la copie dans un projet,
  on la renomme, on suit son SETTINGS.md, et on passe à autre chose.</p>
  <div class="stats">
    <div class="stat"><b>{len(apps)}</b><span>apps complètes</span></div>
    <div class="stat"><b>{len(snippets)}</b><span>snippets</span></div>
    <div class="stat"><b>100%</b><span>testées pytest</span></div>
  </div>
  <div class="liens-hero">
    <a class="btn plein" href="{DEMO_URL}">Vitrine live : les {len(apps)} apps montées</a>
    <a class="btn" href="{REPO_URL}">Repo GitHub (privé)</a>
    <a class="btn" href="#workflow">Comment s'en servir</a>
  </div>
</header>

<h2 class="section">Les apps</h2>
<p class="note-section">Cliquer une carte ouvre sa documentation complète : ce qu'elle fait,
son intégration pas à pas, ses variables d'environnement.</p>
<div class="grille">{''.join(cartes)}</div>

<h2 class="section">Les snippets</h2>
<p class="note-section">Des utilitaires à fichier unique : copier-coller dans settings, middleware ou utils.</p>
<div class="defil"><table class="snips">
<tr><th>Fichier</th><th>Rôle</th><th>Source</th></tr>{snips}
</table></div>

<h2 class="section" id="workflow">Comment s'en servir</h2>
<p class="note-section">Quatre modes, déclarés avant d'écrire la moindre ligne. Le premier couvre
presque tous les cas.</p>
<div class="modes">
  <div class="mode-carte"><b>REUSE</b><p>Le template existe : on copie <code>apps/&lt;slug&gt;/</code>
  dans le projet, on renomme le module au goût du projet, on suit SETTINGS.md, on migre,
  on lance les tests du template. Aucun code neuf.</p></div>
  <div class="mode-carte"><b>ITERATE</b><p>Le template existe mais un projet l'a amélioré :
  on produit la v1.1 dans la librairie (SemVer + changelog), jamais une copie divergente.</p></div>
  <div class="mode-carte"><b>EXTRACT</b><p>Pas de template, mais un projet a du code éprouvé :
  on choisit entre extraire-abstraire (rapide) et réécrire (propre), puis on l'ajoute ici.</p></div>
  <div class="mode-carte"><b>CREATE</b><p>Personne ne l'a : on conçoit avec un biais réutilisable
  (settings via getattr, AUTH_USER_MODEL, backends interchangeables) et les critères production.</p></div>
</div>
"""
    return TETE.format(titre="Django Templates : le catalogue", desc="13 apps Django production-ready à copier : auth JWT, billing Stripe, RAG pgvector, notifications, e-commerce, newsletters.", style=STYLE) + corps + PIED.format(repo=REPO_URL, demo=DEMO_URL)


def page_app(a):
    morceaux = [f"""
<a class="retour" href="../index.html">← Retour au catalogue</a>
<header style="padding:24px 0 8px">
  <span class="sur-titre">{a['slug']} · v{a['version']} · {a['mode']}</span>
  <h1 class="titre" style="font-size:clamp(30px,5vw,48px)">{html.escape(a['verbose'])}</h1>
  <p class="bandeau-doc">Dépendances : {html.escape(', '.join(a['deps']) or 'aucune')} · Source : {html.escape(a['source'])}</p>
</header>"""]
    for nom, fichier in [("README", "README.md"), ("SETTINGS : intégration pas à pas", "SETTINGS.md")]:
        chemin = RACINE / "apps" / a["slug"] / fichier
        if chemin.exists():
            MD.reset()
            corps = re.sub(r"═+.*?═+", "", lire(chemin), flags=re.S)
            morceaux.append(f'<span class="badge-fichier">{nom}</span><div class="doc">{MD.convert(corps)}</div>')
    return (
        TETE.format(titre=f"{a['slug']} : Django Templates", desc=html.escape(a["pitch"]), style=STYLE)
        + "".join(morceaux)
        + PIED.format(repo=REPO_URL, demo=DEMO_URL)
    )


def main():
    # Table rase SAUF .vercel : c'est le lien du projet Vercel ; l'effacer fait
    # atterrir le prochain deploy dans un projet parasite nomme "dist" (vecu).
    if DIST.exists():
        for enfant in DIST.iterdir():
            if enfant.name == ".vercel":
                continue
            shutil.rmtree(enfant) if enfant.is_dir() else enfant.unlink()
    (DIST / "apps").mkdir(parents=True, exist_ok=True)
    apps = parse_catalog()
    for a in apps:
        a["verbose"] = verbose_name(a["slug"])
        a["pitch"] = pitch(a["slug"])
    snippets = parse_snippets()
    (DIST / "index.html").write_text(page_index(apps, snippets), encoding="utf-8")
    for a in apps:
        (DIST / "apps" / f"{a['slug']}.html").write_text(page_app(a), encoding="utf-8")
    print(f"OK : {len(apps)} apps, {len(snippets)} snippets -> {DIST}")


if __name__ == "__main__":
    main()
